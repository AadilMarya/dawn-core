import errno
import logging
import re
import socket
import time
import traceback
from collections import deque
from typing import Callable, Tuple

from ..pythonosc.osc_bundle import OscBundle
from ..pythonosc.osc_message import OscMessage, ParseError
from ..pythonosc.osc_message_builder import BuildError, OscMessageBuilder
from .constants import OSC_LISTEN_PORT, OSC_RESPONSE_PORT
from .security import OscSecurityError, SecureOscTransport

# The control surface runs on Live's script thread.  These bounds are deliberately
# local to one host tick: they prevent a burst of authenticated UDP traffic from
# monopolising the audio-adjacent control-surface callback without imposing a
# policy cap on DAWN's agent work.
#
# ``MAX_TICK_SECONDS`` is the real audio-safety bound and must remain the binding
# constraint: ``_process_pending`` and the receive loop both re-check the monotonic
# deadline between every message, so a tick cannot overrun it regardless of the
# count caps below.  The counts exist only to stop one pathological burst from
# starving the next tick's fair share.
#
# The counts were previously 4/16.  Against Live's fixed 100 ms tick that capped the
# entire transport at ~40 OSC messages/second and put ~50 ms of average scheduling
# latency on every request/reply — the dominant term in DAWN's per-action latency,
# and pure throttle rather than protection, because the time budget already bounds
# tick CPU.  Raising them lets a normal burst drain inside the same 15 ms budget.
MAX_MESSAGES_PER_TICK = 32
MAX_DATAGRAMS_PER_TICK = 64
MAX_TICK_SECONDS = 0.015
MAX_PENDING_MESSAGES = 64

# A handler that loops internally (``/dawn/execute_verified_batch`` applies N
# mutations inside ONE ``process_message`` call) is invisible to the checks
# above: they only run *between* messages.  Such a handler must consult the
# live tick budget itself, so the deadline is published on the server.

class OSCServer:
    def __init__(self,
                 local_addr: Tuple[str, int] = ('127.0.0.1', OSC_LISTEN_PORT),
                 remote_addr: Tuple[str, int] = ('127.0.0.1', OSC_RESPONSE_PORT),
                 security_transport=None):
        """
        Class that handles OSC server responsibilities, including support for sending
        reply messages.

        Implemented because pythonosc's OSC server causes a beachball when handling
        incoming messages. To investigate, as it would be ultimately better not to have
        to roll our own.

        Args:
            local_addr: Local address and port to listen on. The production
                        default is IPv4 loopback and must never be widened.
            remote_addr: Remote address to send replies to, by default. Can be overridden in send().
        """

        if local_addr[0] != "127.0.0.1" or remote_addr[0] != "127.0.0.1":
            raise ValueError("DAWN OSC transport is restricted to IPv4 loopback")
        self._local_addr = local_addr
        self._remote_addr = remote_addr
        self._response_port = remote_addr[1]
        self._security = security_transport or SecureOscTransport()

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(0)
        self._socket.bind(self._local_addr)
        self._callbacks = {}
        self._pending_messages = deque()
        self._clock = getattr(time, "monotonic", time.time)
        # Monotonic deadline of the tick currently being processed, or None when
        # no tick is in flight. Read by handlers that loop internally.
        self._tick_deadline = None
        self._last_tick_processed = 0
        self._last_tick_deferred = 0
        self._last_tick_oldest_deferred_seconds = 0.0
        self._overload_dropped_messages = 0

        self.logger = logging.getLogger("dawn_osc")
        self.logger.info("Starting OSC server (local %s, response port %d)",
                         str(self._local_addr), self._response_port)

    def add_handler(self, address: str, handler: Callable) -> None:
        """
        Add an OSC handler.

        Args:
            address: The OSC address string
            handler: A handler function, with signature:
                     params: Tuple[Any, ...]
        """
        self._callbacks[address] = handler

    def clear_handlers(self) -> None:
        """
        Remove all existing OSC handlers.
        """
        self._callbacks = {}

    def send(self,
             address: str,
             params: Tuple = (),
             remote_addr: Tuple[str, int] = None) -> None:
        """
        Send an OSC message.

        Args:
            address: The OSC address (e.g. /frequency)
            params: A tuple of zero or more OSC params
            remote_addr: The remote address to send to, as a 2-tuple (hostname, port).
                         If None, uses the default remote address.
        """
        msg_builder = OscMessageBuilder(address)
        for param in params:
            msg_builder.add_arg(param)

        try:
            msg = msg_builder.build()
            if remote_addr is None:
                remote_addr = self._remote_addr
            for secured in self._security.wrap_response_many(msg.dgram):
                self._socket.sendto(secured, remote_addr)
        except OscSecurityError as exc:
            # Security readiness can legitimately lag Live/Remote-Script startup.
            # Keep this below ERROR so the /live/error log handler cannot recurse
            # through send() while no authenticated app session exists.
            self.logger.warning("DAWN: Secure reply dropped: %s" % exc)
        except BuildError:
            self.logger.error("DAWN: OSC build error: %s" % (traceback.format_exc()))
        except OSError as exc:
            # A failed send must not escape process() and abort the rest of this
            # tick's non-blocking receive drain.  In particular, EMSGSIZE used
            # to starve later replies until the next Live tick.
            self.logger.warning("DAWN: Secure reply send failed: %s" % exc)

    def process_message(self, message, remote_addr):
        params = message.params
        reply_prefix = ()
        if params and isinstance(params[0], str) and params[0].startswith("dawn_request:"):
            match = re.fullmatch(r"dawn_request:([0-9a-f]{32})", params[0])
            if match is None:
                return  # malformed reserved identity must not enter a callback
            reply_prefix = ("dawn_reply:" + match.group(1),)
            params = params[1:]
        response_addr = (remote_addr[0], self._response_port)
        if reply_prefix and "*" in message.address:
            # One logical request cannot consume several wildcard replies.
            self.send(
                "/live/error", reply_prefix + (message.address, "correlated wildcard queries are unsupported"),
                remote_addr=response_addr,
            )
            return

        def dispatch(callback_address, callback, wildcard=False):
            try:
                rv = callback(params)
                if rv is not None:
                    if not isinstance(rv, tuple):
                        raise TypeError("OSC callbacks must return tuples")
                    # Identity is explicit here, never ambient in send(): a
                    # listener can fire during or after this callback and must
                    # remain an unsolicited notification.
                    self.send(callback_address, reply_prefix + rv, remote_addr=response_addr)
            except Exception as exc:
                if wildcard and isinstance(exc, (ValueError, AttributeError)):
                    return  # preserve legacy wildcard discovery's optional handlers
                self.logger.error(
                    "DAWN: Handler failed for %s: %s" %
                    (callback_address, traceback.format_exc())
                )
                self.send(
                    "/live/error", reply_prefix + (message.address, "handler failed"),
                    remote_addr=response_addr,
                )

        if message.address in self._callbacks:
            dispatch(message.address, self._callbacks[message.address])
        elif "*" in message.address:
            regex = message.address.replace("*", "[^/]+")
            for callback_address, callback in self._callbacks.items():
                if re.fullmatch(regex, callback_address):
                    dispatch(callback_address, callback, wildcard=True)
        else:
            self.logger.error("DAWN: Unknown OSC address: %s" % message.address)
            self.send(
                "/live/error", reply_prefix + (message.address, "unknown OSC address"),
                remote_addr=response_addr,
            )

    def process_bundle(self, bundle, remote_addr):
        for i in bundle:
            if OscBundle.dgram_is_bundle(i.dgram):
                self.process_bundle(i, remote_addr)
            else:
                self.process_message(i, remote_addr)

    def parse_bundle(self, data, remote_addr):
        if OscBundle.dgram_is_bundle(data):
            try:
                bundle = OscBundle(data)
                self.process_bundle(bundle, remote_addr)
            except ParseError:
                self.logger.error("DAWN: Error parsing OSC bundle: %s" % (traceback.format_exc()))
        else:
            try:
                message = OscMessage(data)
                self.process_message(message, remote_addr)
            except ParseError:
                self.logger.error("DAWN: Error parsing OSC message: %s" % (traceback.format_exc()))

    def _send_overload(self, remote_addr):
        """Reply once a parsed request could not enter the bounded tick queue."""
        remote_hostname, _ = remote_addr
        self.send(
            "/live/error",
            ("osc_overloaded", "DAWN control surface is busy; retry shortly"),
            remote_addr=(remote_hostname, self._response_port),
        )

    def _enqueue_message(self, message, remote_addr):
        if len(self._pending_messages) >= MAX_PENDING_MESSAGES:
            self._overload_dropped_messages += 1
            return False
        self._pending_messages.append((message, remote_addr, self._clock()))
        return True

    def _enqueue_bundle(self, bundle, remote_addr):
        """Queue bundle leaves without letting one datagram create unbounded work."""
        for item in bundle:
            if OscBundle.dgram_is_bundle(item.dgram):
                if not self._enqueue_bundle(item, remote_addr):
                    return False
            elif not self._enqueue_message(item, remote_addr):
                return False
        return True

    def _enqueue_packet(self, data, remote_addr):
        try:
            if OscBundle.dgram_is_bundle(data):
                return self._enqueue_bundle(OscBundle(data), remote_addr)
            return self._enqueue_message(OscMessage(data), remote_addr)
        except ParseError:
            self.logger.error("DAWN: Error parsing OSC packet: %s" % (traceback.format_exc()))
            return True

    def remaining_tick_seconds(self):
        """Seconds left in the tick currently being processed.

        Returns ``MAX_TICK_SECONDS`` when no tick is in flight (direct handler
        calls in tests), so a caller outside ``process()`` is never starved.
        A handler that applies several Live operations inside one message must
        consult this: ``_process_pending`` and the receive loop only re-check
        the deadline *between* messages, so nothing else bounds such a handler.
        """
        deadline = getattr(self, "_tick_deadline", None)
        if deadline is None:
            return MAX_TICK_SECONDS
        return deadline - self._clock()

    def _process_pending(self, deadline, remaining):
        """Run only a bounded number of already parsed handler calls this tick."""
        processed = 0
        while self._pending_messages and processed < remaining and self._clock() < deadline:
            message, remote_addr, _queued_at = self._pending_messages.popleft()
            self.process_message(message, remote_addr)
            processed += 1
        return processed

    def process(self) -> None:
        """
        Process a bounded amount of queued OSC work on Live's script thread.

        UDP already has lossy semantics; keeping a small parsed queue gives valid
        requests a fair next-tick chance while surfacing an explicit overload reply
        once that queue is full.  The server never drains the kernel socket without
        a time/message bound.
        """
        deadline = self._clock() + MAX_TICK_SECONDS
        self._tick_deadline = deadline
        processed = self._process_pending(deadline, MAX_MESSAGES_PER_TICK)
        datagrams = 0
        overload_reported = False
        try:
            while (
                processed < MAX_MESSAGES_PER_TICK
                and datagrams < MAX_DATAGRAMS_PER_TICK
                and self._clock() < deadline
            ):
                #--------------------------------------------------------------------------------
                # Receive only a bounded number of datagrams.  Remaining kernel
                # backlog stays available for the next 100ms Live tick.
                #--------------------------------------------------------------------------------
                data, remote_addr = self._socket.recvfrom(65536)
                datagrams += 1
                if remote_addr[0] != "127.0.0.1":
                    self.logger.warning(
                        "DAWN: Rejected non-loopback sender %s" % (remote_addr[0],)
                    )
                    continue
                try:
                    data = self._security.unwrap_request(data)
                except OscSecurityError as exc:
                    self.logger.warning("DAWN: Rejected OSC datagram: %s" % exc)
                    continue
                if data is None:
                    # A complete OSC packet is dispatched only after every
                    # independently authenticated fragment has arrived.
                    continue
                #--------------------------------------------------------------------------------
                # Update the default reply address to the most recent client. Used when
                # sending (e.g) /live/song/beat messages and listen updates.
                #
                # This is slightly ugly and prevents registering listeners from different IPs.
                #--------------------------------------------------------------------------------
                self._remote_addr = ("127.0.0.1", OSC_RESPONSE_PORT)
                if not self._enqueue_packet(data, remote_addr) and not overload_reported:
                    overload_reported = True
                    self._send_overload(remote_addr)
                processed += self._process_pending(
                    deadline,
                    MAX_MESSAGES_PER_TICK - processed,
                )

        except socket.error as e:
            if e.errno == errno.ECONNRESET:
                #--------------------------------------------------------------------------------
                # This benign error seems to occur on startup on Windows
                #--------------------------------------------------------------------------------
                self.logger.warning("DAWN: Non-fatal socket error: %s" % (traceback.format_exc()))
            elif e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                #--------------------------------------------------------------------------------
                # Another benign networking error, throw when no data is received
                # on a call to recvfrom() on a non-blocking socket
                #--------------------------------------------------------------------------------
                pass
            else:
                #--------------------------------------------------------------------------------
                # Something more serious has happened
                #--------------------------------------------------------------------------------
                self.logger.error("DAWN: Socket error: %s" % (traceback.format_exc()))

        except Exception as e:
            self.logger.error("DAWN: Error handling OSC message: %s" % e)
            self.logger.warning("DAWN: %s" % traceback.format_exc())

        self._tick_deadline = None
        self._last_tick_processed = processed
        self._last_tick_deferred = len(self._pending_messages)
        if self._pending_messages:
            self._last_tick_oldest_deferred_seconds = max(
                0.0,
                self._clock() - self._pending_messages[0][2],
            )
        else:
            self._last_tick_oldest_deferred_seconds = 0.0
        if overload_reported:
            self.logger.warning(
                "DAWN: Tick queue overloaded; deferred=%d oldest=%.3fs dropped=%d" %
                (
                    self._last_tick_deferred,
                    self._last_tick_oldest_deferred_seconds,
                    self._overload_dropped_messages,
                )
            )

    def shutdown(self) -> None:
        """
        Shutdown the server network sockets.
        """
        self._socket.close()
