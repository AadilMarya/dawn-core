# Module: testing & MiniLive

> Offline in-process fake of the control surface, the test layout, and the agent evals.

## MiniLive (`dawn_core/testing/mini_live.py`)

- Ships in the package (`dawn_core.testing`); a threading UDP server that speaks the
  real authenticated envelope (HMAC, replay window, correlation) and follows the Remote
  Script's dispatch semantics:
  - a request carrying `dawn_request:<id>` gets its reply prefixed `dawn_reply:<id>`;
  - a handler returning `None` sends no reply (most setters);
  - unknown address or raising handler → `/live/error`.
- Built-ins: `/live/test`, `/dawn/security/status`, song tempo/is_playing/
  start/stop/num_tracks, track name/mute/volume (get+set).
- `serve(address, handler)` adds or replaces an address; `listen_port` and `reply_port`
  expose the chosen ports; `silent_addresses` makes handlers emit no reply.
- Records: `requests` (every authenticated request as `RecordedRequest`), and
  `rejected_datagrams` for auth failures.
- Reports `PROTOCOL = "2.32.0"`, matching `DAWN_PROTOCOL_VERSION`.

## Fixtures (`dawn_core/tests/conftest.py`)

- `isolated_runtime` (autouse): points `DAWN_RUNTIME_DIR` at a per-test tmp dir and resets the
  process session — tests never touch `~/.dawn`.
- `ports` / `free_port`: OS-allocated loopback ports.
- `live_factory` / `live`: start `MiniLive`s on given ports; all stopped at teardown.

## Layout & facts

- `dawn_osc/tests/` — control-surface behaviour (`structural_mock_surface.py` fakes the Live
  facade against real host helpers), tick budget, cue safety, browser, device toggle,
  standalone transport tests. `conftest.py` exposes the payload as `control_surface.DAWN`.
- `dawn_core/tests/` — catalog, generator, session, safety, tools, call replies, remote
  script, licensing, prompt, agent and evals.
- `test_agent.py` — scripted `FunctionModel`, tool call, streaming, prompt selection.
- `test_evals.py` — six agent-flow scenarios: tempo, create/name a track, mute, read-only
  refusal, destructive refusal, unknown address.
- `test_tools.py` — every curated tool against `MiniLive`, including refusals and the device
  parameter wire shape.
- `test_prompt.py` — doctrine lines, order, subset selection, 10,000-character budget.
- 264 tests at 0.1.0. `dawn_core` runs pytest with `filterwarnings = error`; async mode
  is `auto` only when pytest's rootdir is `dawn_core/`; from the repo root, mark async tests with
  `@pytest.mark.asyncio`.
- The whole suite is offline: no network, no Live, no API keys.

## Related

- [[modules/tools]] · [[modules/agent]] · [[architecture/data-flow]] · [[modules/harness-and-gates]]
