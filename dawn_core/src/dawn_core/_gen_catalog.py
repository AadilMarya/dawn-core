"""Generate the committed OSC catalog module from the DAWN Remote Script source.

    python -m dawn_core._gen_catalog           regenerate _catalog_data.py
    python -m dawn_core._gen_catalog --check   exit 1 if it is stale, or if any
                                                    add_handler call site is unresolved

The Remote Script runs inside Ableton Live and cannot be imported here, so the source
is read with :mod:`ast` only. Each ``add_handler(address, callback)`` call is walked in
statement order. ``for`` loops over statically known iterables are unrolled, so
``"/live/track/%s" % prop`` yields one address per loop value. Iterables are lists,
tuples, ``range`` calls and ``+`` concatenations of those, bound to names in scope.
A call site whose address cannot be expanded is reported as unresolved and fails the
check, unless it appears in ``ALLOWED_UNRESOLVED`` with a written justification.

Registration semantics follow the Remote Script: ``add_handler`` is a dict assignment,
so the last registration for an address wins. The catalog keeps that winner.

Risk classes, applied in order; the first rule that matches wins:

1. read   -- ``/live/test``, ``/dawn/version``, ``/dawn/health``, ``/dawn/security/status``.
2. read   -- verbs ``get``, ``start_listen`` and ``stop_listen``. Listeners only subscribe.
3. write  -- verified-mutation endpoints under ``/dawn/`` (``execute_verified*``,
             ``verified/result``, ``startup``). Policy: they are never classed
             destructive here, even though their payloads can carry any mutation. The
             safety layer cannot see inside those payloads.
4. destructive -- a ``/`` or ``_`` delimited token ``delete``, ``remove``, ``clear``,
             ``replace`` or ``crop``, or a ``set/notes`` endpoint (wholesale overwrite of
             every note in a clip). Stopping playback removes nothing, so the
             ``stop_all_clips`` endpoints are writes, not destructive.
5. write  -- everything else, including any shape the rules above do not recognise.

``replies`` says whether the handler returns a value, so Live answers a correlated request.
The callback is resolved from the AST only: ``self.<name>`` (a method of the enclosing
class, or of its single base class in the same file), a name bound by a ``def`` in an
enclosing function or at module level, and a lambda. A handler replies when a ``return``
outside any nested definition returns something other than ``None``. Anything else is
unknown (None): ``partial``, wrapper factories, loop variables, imported names, decorated
handlers and coroutines.
"""

from __future__ import annotations

import argparse
import ast
import itertools
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeGuard

from ._catalog_types import RISK_CLASSES, ArgSpec, CatalogEntry, RiskClass

OUTPUT_PATH = Path(__file__).resolve().with_name("_catalog_data.py")

# "<label>:<line>" -> justification. A call site listed here may stay unresolved.
# Empty by design: every registration in the Remote Script must be expanded.
ALLOWED_UNRESOLVED: dict[str, str] = {}

_MAX_PRODUCT = 4096
_MAX_LOOP_ITEMS = 4096
# Env key prefix that remembers the source expression bound to a name.
_EXPR_KEY = "\0expr:"
_VERB_WORDS = frozenset({"get", "set", "start_listen", "stop_listen"})
_READ_ADDRESSES = frozenset(
    {
        "/live/test",
        "/dawn/version",
        "/dawn/health",
        "/dawn/security/status",
        # Browser listing traverses the Browser; it does not change the Set.
        "/live/browser/list/devices",
        "/live/browser/list/presets",
        "/live/browser/list/drum_rack_presets",
        "/live/browser/list/drum_samples",
    }
)
_READ_VERBS = frozenset({"get", "start_listen", "stop_listen"})
_VERIFIED_PREFIXES = ("/dawn/execute_verified", "/dawn/verified/", "/dawn/startup")
_DESTRUCTIVE_TOKEN = re.compile(r"(?:^|[/_])(?:delete|remove|clear|replace|crop)(?=[/_]|$)")

# Callback wrappers in the Remote Script and the index parameters each one consumes
# before its own arguments. Derived from the wrapper bodies, which unpack these
# indices from ``params`` first.
_WRAPPER_INDEX: dict[str, tuple[str, ...]] = {
    "create_track_callback": ("track_index",),
    "create_return_track_callback": ("track_index",),
    "create_clip_callback": ("track_index", "clip_index"),
    "create_clip_slot_callback": ("track_index", "clip_slot_index"),
    "create_device_callback": ("track_index", "device_index"),
    "create_scene_callback": ("scene_index",),
    "create_master_callback": (),
}

# Endpoints whose handler consumes an index the wrapper table cannot see. The handler
# receives ``params[2:]`` and unpacks the extra index itself, so the wire signature is
# wider than ``_WRAPPER_INDEX`` reports. Values are the missing int argument names, in
# order. For setters the missing indices go immediately before the ``value`` argument.
_EXTRA_INDEX_ARGS: dict[str, tuple[str, ...]] = {
    "/live/device/get/parameter/name": ("parameter_index",),
    "/live/device/get/parameter/value": ("parameter_index",),
    "/live/device/get/parameter/value_string": ("parameter_index",),
    "/live/device/set/parameter/value": ("parameter_index",),
    "/live/return_device/get/parameters/value": ("device_index",),
    "/live/return_device/set/parameter/value": ("device_index", "parameter_index"),
}


class _Unknown:
    """Sentinel for a value the generator cannot determine statically."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN: Final = _Unknown()


@dataclass(frozen=True, slots=True)
class _Seq:
    """A statically known iterable bound to a name."""

    items: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Site:
    """One ``add_handler`` call expression in the Remote Script source."""

    label: str
    lineno: int
    col: int
    expr: str


@dataclass(frozen=True, slots=True)
class Registration:
    """One concrete address produced by one call site."""

    address: str
    site: Site
    callback: ast.expr | None
    replies: bool | None = None


@dataclass(frozen=True, slots=True)
class Unresolved:
    """A call site whose address could not be expanded."""

    site: Site
    reason: str
    allowed: bool


@dataclass(frozen=True, slots=True)
class CatalogBuild:
    entries: tuple[CatalogEntry, ...]
    unresolved: tuple[Unresolved, ...]
    call_sites: int
    concrete_addresses: int
    duplicate_addresses: tuple[str, ...]

    @property
    def failing(self) -> tuple[Unresolved, ...]:
        return tuple(item for item in self.unresolved if not item.allowed)


# ---------------------------------------------------------------------------
# Static evaluation of addresses
# ---------------------------------------------------------------------------


def _is_add_handler(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_handler"
    )


def known(value: object) -> TypeGuard[list[Any]]:
    """True when ``value`` is a statically evaluated value rather than ``UNKNOWN``.

    A type guard, so a caller's ``if known(x):`` narrows ``x`` to a concrete list.
    """
    return isinstance(value, list)


def _position(node: ast.AST) -> tuple[int, int]:
    return (node.lineno, node.col_offset)  # type: ignore[attr-defined]


def _product(parts: Sequence[Any]) -> list[tuple[Any, ...]] | _Unknown:
    size = 1
    for part in parts:
        if part is UNKNOWN:
            return UNKNOWN
        size *= len(part)
        if size > _MAX_PRODUCT:
            return UNKNOWN
    return list(itertools.product(*parts))


def _assigned_names(stmts: Iterable[ast.AST]) -> set[str]:
    names: set[str] = set()
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
    return names


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _param_names(args: ast.arguments) -> list[str]:
    names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


# ---------------------------------------------------------------------------
# Reply analysis: does a registered callback return a value?
# ---------------------------------------------------------------------------

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
_ScopeNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
_Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
# Names bound directly in one scope, and the function definitions among them.
_Bindings = tuple[frozenset[str], tuple[_FunctionNode, ...]]
# A return inside one of these belongs to that inner scope, not to the handler.
_NESTED_BODIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_MAX_BASE_DEPTH = 8


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _returns_value(body: Sequence[ast.stmt]) -> bool:
    """True when a ``return`` in ``body`` yields something other than the constant None."""
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Return) and node.value is not None and not _is_none(node.value):
            return True
        if not isinstance(node, _NESTED_BODIES):
            pending.extend(ast.iter_child_nodes(node))
    return False


def _scope_bindings(body: Sequence[ast.stmt]) -> _Bindings:
    """Names bound directly in one scope and its function definitions, nested scopes skipped."""
    stores: set[str] = set()
    defs: list[_FunctionNode] = []
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, _FUNCTION_NODES):
            defs.append(node)
            continue
        if isinstance(node, ast.ClassDef):
            stores.add(node.name)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            stores.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            stores.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            stores.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            stores.update(node.names)
        pending.extend(ast.iter_child_nodes(node))
    return frozenset(stores), tuple(defs)


def _innermost_class(scopes: Sequence[_ScopeNode]) -> ast.ClassDef | None:
    for scope in reversed(scopes):
        if isinstance(scope, ast.ClassDef):
            return scope
    return None


class _ReplyResolver:
    """Decides whether a registered callback returns a value, from one module's source.

    Nothing is imported or run. A callback resolves to one definition in this file, or the
    answer is None: a name that could be bound to something else is never guessed.
    """

    def __init__(self, module: ast.Module) -> None:
        self._module = module
        self._facts: dict[int, _Bindings] = {}
        self._self_stores: dict[int, frozenset[str]] = {}

    def replies(self, callback: ast.expr | None, scopes: Sequence[_ScopeNode]) -> bool | None:
        """Whether ``callback`` returns a value. ``scopes`` are the enclosing defs and classes."""
        target = self._target(callback, scopes)
        if target is None:
            return None
        if isinstance(target, ast.Lambda):
            return not _is_none(target.body)
        if isinstance(target, ast.AsyncFunctionDef) or target.decorator_list:
            # A decorator or a coroutine can change what the call returns.
            return None
        return _returns_value(target.body)

    def _target(
        self, callback: ast.expr | None, scopes: Sequence[_ScopeNode]
    ) -> ast.Lambda | _FunctionNode | None:
        if isinstance(callback, ast.Lambda):
            return callback
        if isinstance(callback, ast.Name):
            return self._lexical(callback.id, scopes)
        if (
            isinstance(callback, ast.Attribute)
            and isinstance(callback.value, ast.Name)
            and callback.value.id == "self"
        ):
            owner = _innermost_class(scopes)
            return None if owner is None else self._method(owner, callback.attr, depth=0)
        return None

    def _lexical(self, name: str, scopes: Sequence[_ScopeNode]) -> _FunctionNode | None:
        """The one def a bare name refers to, searching the enclosing scopes innermost first."""
        for scope in reversed(scopes):
            if isinstance(scope, ast.ClassDef):
                # Method bodies cannot see class-level names, so a clash stays unknown.
                if self._binds(scope, name):
                    return None
                continue
            params = _param_names(scope.args)
            if self._binds(scope, name, params):
                return self._only_def(scope, name, params)
        if self._binds(self._module, name):
            return self._only_def(self._module, name, [])
        return None

    def _method(self, cls: ast.ClassDef, attr: str, depth: int) -> _FunctionNode | None:
        """The method ``self.<attr>`` reaches through ``cls``, or None when not certain."""
        stores, defs = self._bindings(cls)
        if attr in stores or attr in self._assigned_on_self(cls):
            return None  # an instance or class attribute of that name shadows the method
        matches = [d for d in defs if d.name == attr]
        if matches:
            return matches[0] if len(matches) == 1 else None
        # Not defined here: only a single base class from this same file can supply it.
        if depth >= _MAX_BASE_DEPTH or len(cls.bases) != 1:
            return None
        base = cls.bases[0]
        if not isinstance(base, ast.Name):
            return None
        parent = self._module_class(base.id)
        return None if parent is None else self._method(parent, attr, depth + 1)

    def _binds(self, scope: _Scope, name: str, params: Sequence[str] = ()) -> bool:
        stores, defs = self._bindings(scope)
        return name in stores or name in params or any(d.name == name for d in defs)

    def _only_def(self, scope: _Scope, name: str, params: Sequence[str]) -> _FunctionNode | None:
        stores, defs = self._bindings(scope)
        matches = [d for d in defs if d.name == name]
        if name in stores or name in params or len(matches) != 1:
            return None
        return matches[0]

    def _bindings(self, scope: _Scope) -> _Bindings:
        key = id(scope)
        if key not in self._facts:
            self._facts[key] = _scope_bindings(scope.body)
        return self._facts[key]

    def _assigned_on_self(self, cls: ast.ClassDef) -> frozenset[str]:
        """Every attribute some method of ``cls`` assigns on ``self``."""
        key = id(cls)
        if key not in self._self_stores:
            self._self_stores[key] = frozenset(
                node.attr
                for node in ast.walk(cls)
                if isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
            )
        return self._self_stores[key]

    def _module_class(self, name: str) -> ast.ClassDef | None:
        matches = [n for n in self._module.body if isinstance(n, ast.ClassDef) and n.name == name]
        return matches[0] if len(matches) == 1 else None


class _Walker:
    """Walks one module, tracking statically known bindings in statement order."""

    def __init__(self, label: str, module: ast.Module) -> None:
        self.label = label
        self.registrations: list[Registration] = []
        self.unresolved: dict[tuple[int, int], Unresolved] = {}
        self.reached: set[tuple[int, int]] = set()
        self._resolver = _ReplyResolver(module)
        # Enclosing defs and classes, outermost first, for resolving callbacks.
        self._scopes: list[_ScopeNode] = []

    # -- statements -------------------------------------------------------

    def run(self, tree: ast.Module) -> None:
        module_env: dict[str, Any] = {}
        # Module-level constants may be used by classes defined above them.
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    self._bind(target, stmt.value, module_env)
        self._block(tree.body, dict(module_env))

    def _block(self, stmts: Sequence[ast.stmt], env: dict[str, Any]) -> None:
        for stmt in stmts:
            self._stmt(stmt, env)

    def _stmt(self, stmt: ast.stmt, env: dict[str, Any]) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = dict(env)
            for name in _param_names(stmt.args):
                inner[name] = UNKNOWN
            self._nested(stmt, inner)
        elif isinstance(stmt, ast.ClassDef):
            self._nested(stmt, dict(env))
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._for(stmt, env)
        elif isinstance(stmt, ast.While):
            self._scan(stmt.test, env)
            self._opaque_loop(stmt.body, env, target=None)
        elif isinstance(stmt, ast.If):
            self._scan(stmt.test, env)
            self._block(stmt.body, dict(env))
            self._block(stmt.orelse, dict(env))
            self._forget(_assigned_names([*stmt.body, *stmt.orelse]), env)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                self._scan(item.context_expr, env)
            self._block(stmt.body, env)
        elif isinstance(stmt, ast.Try):
            branches = [stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody]
            for branch in branches:
                self._block(branch, dict(env))
            self._forget(_assigned_names([s for b in branches for s in b]), env)
        elif isinstance(stmt, ast.Assign):
            self._scan(stmt.value, env)
            for target in stmt.targets:
                self._bind(target, stmt.value, env)
        elif isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None:
                self._scan(stmt.value, env)
                self._bind(stmt.target, stmt.value, env)
        elif isinstance(stmt, ast.AugAssign):
            self._scan(stmt.value, env)
            self._forget(_assigned_names([stmt]), env)
        else:
            self._scan(stmt, env)

    def _nested(self, scope: _ScopeNode, env: dict[str, Any]) -> None:
        """Walk a def or class body with ``scope`` as the innermost enclosing scope."""
        self._scopes.append(scope)
        self._block(scope.body, env)
        self._scopes.pop()

    def _for(self, stmt: ast.For | ast.AsyncFor, env: dict[str, Any]) -> None:
        self._scan(stmt.iter, env)
        items = self._sequence(stmt.iter, env)
        if not known(items) or len(items) > _MAX_LOOP_ITEMS:
            self._opaque_loop(stmt.body, env, target=stmt.target)
        elif not items:
            # A statically empty loop never runs its body: its call sites register
            # nothing, which is a valid outcome, not an unresolved one.
            for sub in ast.walk(ast.Module(body=list(stmt.body), type_ignores=[])):
                if _is_add_handler(sub):
                    self.reached.add(_position(sub))
        else:
            for item in items:
                inner = dict(env)
                for name in _assigned_names(stmt.body):
                    inner[name] = UNKNOWN
                if not self._bind_value(stmt.target, item, inner):
                    self._forget(_names_in(stmt.target), inner)
                self._block(stmt.body, inner)
        self._block(stmt.orelse, dict(env))
        self._forget(_assigned_names(stmt.body) | _names_in(stmt.target), env)

    def _opaque_loop(
        self, body: Sequence[ast.stmt], env: dict[str, Any], target: ast.expr | None
    ) -> None:
        # One pass with unknown bindings: literal addresses still register, any address
        # that depends on the loop value is reported as unresolved.
        inner = dict(env)
        self._forget(_assigned_names(body), inner)
        if target is not None:
            self._forget(_names_in(target), inner)
        self._block(body, inner)
        self._forget(_assigned_names(body), env)

    @staticmethod
    def _forget(names: Iterable[str], env: dict[str, Any]) -> None:
        for name in names:
            env[name] = UNKNOWN
            env.pop(_EXPR_KEY + name, None)

    # -- bindings ---------------------------------------------------------

    def _bind(self, target: ast.expr, value: ast.expr, env: dict[str, Any]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = self._binding(value, env)
            # Keep the source expression too, so ``add_handler(addr, callback)`` can
            # see the wrapper behind a callback variable.
            env[_EXPR_KEY + target.id] = value
            return
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
            and not any(isinstance(e, ast.Starred) for e in (*target.elts, *value.elts))
        ):
            for sub_target, sub_value in zip(target.elts, value.elts, strict=True):
                self._bind(sub_target, sub_value, env)
            return
        self._forget(_names_in(target), env)

    def _binding(self, node: ast.expr, env: dict[str, Any]) -> Any:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Call, ast.BinOp, ast.Name)):
            items = self._sequence(node, env)
            if known(items):
                return _Seq(tuple(items))
        return self._scalar(node, env)

    def _bind_value(self, target: ast.expr, value: Any, env: dict[str, Any]) -> bool:
        if isinstance(target, ast.Name):
            env[target.id] = [value]
            env.pop(_EXPR_KEY + target.id, None)
            return True
        if isinstance(target, (ast.Tuple, ast.List)):
            if not isinstance(value, tuple) or len(value) != len(target.elts):
                return False
            if any(isinstance(e, ast.Starred) for e in target.elts):
                return False
            items: list[Any] = list(value)
            return all(
                self._bind_value(sub, item, env)
                for sub, item in zip(target.elts, items, strict=True)
            )
        return True

    # -- evaluation -------------------------------------------------------

    def _sequence(self, node: ast.expr, env: dict[str, Any]) -> list[Any] | _Unknown:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            if any(isinstance(e, ast.Starred) for e in node.elts):
                return UNKNOWN
            out: list[Any] = []
            for element in node.elts:
                values = self._scalar(element, env)
                if not known(values):
                    return UNKNOWN
                out.extend(values)
            return out
        if isinstance(node, ast.Name):
            bound = env.get(node.id, UNKNOWN)
            return list(bound.items) if isinstance(bound, _Seq) else UNKNOWN
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._sequence(node.left, env)
            right = self._sequence(node.right, env)
            if not known(left) or not known(right):
                return UNKNOWN
            return [*left, *right]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and not node.keywords
            and node.func.id == "range"
            and 1 <= len(node.args) <= 3
        ):
            bounds = [self._scalar(a, env) for a in node.args]
            if any(not known(b) or len(b) != 1 for b in bounds):
                return UNKNOWN
            numbers: list[int] = [b[0] for b in bounds if known(b)]
            if any(not isinstance(n, int) for n in numbers):
                return UNKNOWN
            values = list(range(*numbers))
            return values if len(values) <= _MAX_LOOP_ITEMS else UNKNOWN
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and not node.keywords
            and node.func.id in {"list", "tuple"}
            and len(node.args) == 1
        ):
            return self._sequence(node.args[0], env)
        return UNKNOWN

    def _scalar(self, node: ast.expr, env: dict[str, Any]) -> list[Any] | _Unknown:
        if isinstance(node, ast.Constant):
            return [node.value]
        if isinstance(node, ast.Name):
            bound = env.get(node.id, UNKNOWN)
            return list(bound) if isinstance(bound, list) else UNKNOWN
        if isinstance(node, ast.Tuple):
            if any(isinstance(e, ast.Starred) for e in node.elts):
                return UNKNOWN
            return _product([self._scalar(e, env) for e in node.elts])
        if isinstance(node, ast.JoinedStr):
            parts: list[list[str] | _Unknown] = []
            for piece in node.values:
                if isinstance(piece, ast.Constant):
                    parts.append([str(piece.value)])
                    continue
                if not isinstance(piece, ast.FormattedValue) or piece.format_spec is not None:
                    return UNKNOWN
                if piece.conversion != -1:
                    return UNKNOWN
                inner = self._scalar(piece.value, env)
                if not known(inner):
                    parts.append(UNKNOWN)
                else:
                    parts.append([str(v) for v in inner])
            combos = _product(parts)
            if not known(combos):
                return UNKNOWN
            return _dedupe("".join(c) for c in combos)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            combos = _product([self._scalar(node.left, env), self._scalar(node.right, env)])
            if not known(combos):
                return UNKNOWN
            if not all(isinstance(a, str) and isinstance(b, str) for a, b in combos):
                return UNKNOWN
            return _dedupe(a + b for a, b in combos)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            return self._percent(node, env)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and not node.keywords
        ):
            combos = _product(
                [self._scalar(node.func.value, env), *(self._scalar(a, env) for a in node.args)]
            )
            if not known(combos):
                return UNKNOWN
            results: list[str] = []
            for template, *args in combos:
                if not isinstance(template, str):
                    return UNKNOWN
                try:
                    results.append(template.format(*args))
                except (IndexError, KeyError, ValueError, TypeError):
                    return UNKNOWN
            return _dedupe(results)
        return UNKNOWN

    def _percent(self, node: ast.BinOp, env: dict[str, Any]) -> list[Any] | _Unknown:
        templates = self._scalar(node.left, env)
        if not known(templates):
            return UNKNOWN
        if isinstance(node.right, ast.Tuple):
            arg_tuples = (
                UNKNOWN
                if any(isinstance(e, ast.Starred) for e in node.right.elts)
                else _product([self._scalar(e, env) for e in node.right.elts])
            )
        else:
            values = self._scalar(node.right, env)
            if not known(values):
                arg_tuples = UNKNOWN
            else:
                arg_tuples = [(v,) for v in values]
        if not known(arg_tuples):
            return UNKNOWN
        results: list[str] = []
        for template in templates:
            if not isinstance(template, str):
                return UNKNOWN
            for args in arg_tuples:
                try:
                    results.append(template % args)
                except (TypeError, ValueError):
                    return UNKNOWN
        return _dedupe(results)

    # -- call sites -------------------------------------------------------

    def _scan(self, node: ast.AST, env: dict[str, Any]) -> None:
        for sub in ast.walk(node):
            if _is_add_handler(sub):
                self._register(sub, env)  # type: ignore[arg-type]

    def _register(self, call: ast.Call, env: dict[str, Any]) -> None:
        key = _position(call)
        self.reached.add(key)
        addr_node = call.args[0] if call.args else _keyword(call, "address")
        callback = call.args[1] if len(call.args) > 1 else _keyword(call, "handler")
        callback = _resolve_callback(callback, env)
        expr = ast.unparse(addr_node) if addr_node is not None else "<missing>"
        site = Site(self.label, call.lineno, call.col_offset, expr)
        if addr_node is None:
            self._unresolve(key, site, "no address argument")
            return
        values = self._scalar(addr_node, env)
        if not known(values):
            names = sorted(
                {
                    n.id
                    for n in ast.walk(addr_node)
                    if isinstance(n, ast.Name) and not isinstance(env.get(n.id), list)
                }
            )
            reason = (
                f"depends on unresolved name(s): {', '.join(names)}"
                if names
                else "unsupported expression"
            )
            self._unresolve(key, site, reason)
            return
        if not all(isinstance(v, str) for v in values):
            self._unresolve(key, site, "address is not a string")
            return
        replies = self._resolver.replies(callback, self._scopes)
        for value in values:
            self.registrations.append(Registration(value, site, callback, replies))

    def _unresolve(self, key: tuple[int, int], site: Site, reason: str) -> None:
        label = f"{site.label}:{site.lineno}"
        allowed = label in ALLOWED_UNRESOLVED
        self.unresolved[key] = Unresolved(site, reason, allowed)


def _resolve_callback(node: ast.expr | None, env: dict[str, Any]) -> ast.expr | None:
    """Follow one level of name binding so a callback variable shows its expression."""
    if isinstance(node, ast.Name):
        source = env.get(_EXPR_KEY + node.id)
        if isinstance(source, ast.expr):
            return source
    return node


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _dedupe(values: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


# ---------------------------------------------------------------------------
# Address classification
# ---------------------------------------------------------------------------


def classify_address(address: str) -> tuple[str, str, str | None]:
    """Return ``(group, verb, prop)`` for an address."""
    segments = address.strip("/").split("/")
    if address == "/live/test":
        return "live", "test", None
    if segments[0] == "dawn":
        tail = segments[1:]
        if len(tail) >= 2 and tail[0] == "get":
            return "dawn", "get", "/".join(tail[1:])
        if tail and tail[0].startswith("execute_verified"):
            return "dawn", "call", None
        return "dawn", "other", None
    group, tail = segments[1], segments[2:]
    if len(tail) >= 2 and tail[0] in _VERB_WORDS:
        return group, tail[0], "/".join(tail[1:])
    return group, "call", None


def classify_risk(address: str, verb: str) -> RiskClass:
    """Apply the module-level risk rules, in order."""
    if address in _READ_ADDRESSES:
        return "read"
    if verb in _READ_VERBS:
        return "read"
    if address.startswith(_VERIFIED_PREFIXES):
        return "write"
    if _DESTRUCTIVE_TOKEN.search(address) or address.endswith("/set/notes"):
        return "destructive"
    return "write"


# ``partial(self.<helper>, target, prop)`` registrations: (helper, verb) -> arguments.
# ``_set_property`` takes exactly the value; getters and listeners take nothing extra.
_PARTIAL_HELPER_ARGS: dict[tuple[str, str], tuple[ArgSpec, ...]] = {
    ("_set_property", "set"): (ArgSpec("value", "any"),),
    ("_get_property", "get"): (),
    ("_start_listen", "start_listen"): (),
    ("_stop_listen", "stop_listen"): (),
}


def _wrapper_name(callback: ast.expr | None) -> str | None:
    """Name of the single callback wrapper a registration uses, if there is one.

    A conditional callback (``a if cond else b``) counts when every wrapper call in
    its branches names the same wrapper; plain function references are ignored.
    """
    pending: list[ast.expr | None] = [callback]
    names: set[str] = set()
    while pending:
        node = pending.pop()
        if isinstance(node, ast.IfExp):
            pending.extend((node.body, node.orelse))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names.pop() if len(names) == 1 else None


def _signature(verb: str, callback: ast.expr | None) -> tuple[ArgSpec, ...]:
    if verb == "test":
        return ()
    if isinstance(callback, ast.Call) and isinstance(callback.func, ast.Name):
        if callback.func.id == "partial" and callback.args:
            target = callback.args[0]
            helper = target.attr if isinstance(target, ast.Attribute) else ""
            if (helper, verb) in _PARTIAL_HELPER_ARGS:
                return _PARTIAL_HELPER_ARGS[(helper, verb)]
            return (ArgSpec("args", "any", variadic=True),)
    wrapper = _wrapper_name(callback)
    if wrapper not in _WRAPPER_INDEX:
        return (ArgSpec("args", "any", variadic=True),)
    indices = tuple(ArgSpec(name, "int") for name in _WRAPPER_INDEX[wrapper])
    if verb in {"get", "start_listen", "stop_listen"}:
        return indices
    if verb == "set":
        return (*indices, ArgSpec("value", "any"))
    return (*indices, ArgSpec("args", "any", variadic=True))


def _with_extra_index_args(address: str, args: tuple[ArgSpec, ...]) -> tuple[ArgSpec, ...]:
    """Insert the index arguments a handler unpacks but its wrapper does not declare."""
    missing = _EXTRA_INDEX_ARGS.get(address)
    if not missing:
        return args
    extras = tuple(ArgSpec(name, "int") for name in missing)
    value_at = next((index for index, arg in enumerate(args) if arg.name == "value"), None)
    if value_at is None:
        return (*args, *extras)
    return (*args[:value_at], *extras, *args[value_at:])


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def default_root() -> Path:
    """The Remote Script package directory, found through the dawn_osc package."""
    from dawn_osc import script_dir

    return Path(script_dir())


def _source_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "pythonosc" not in p.relative_to(root).parts)


def _label(path: Path, root: Path) -> str:
    """Source label such as ``handlers/track.py``, relative to the Remote Script root."""
    return "/".join(path.relative_to(root).parts)


def build_catalog(root: Path | None = None) -> CatalogBuild:
    """Parse every Remote Script module under ``root`` and build the catalog."""
    root = default_root() if root is None else Path(root)
    registrations: list[Registration] = []
    unresolved: list[Unresolved] = []
    call_sites = 0
    for path in _source_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        expected = {_position(n) for n in ast.walk(tree) if _is_add_handler(n)}
        call_sites += len(expected)
        walker = _Walker(_label(path, root), tree)
        walker.run(tree)
        registrations.extend(walker.registrations)
        unresolved.extend(walker.unresolved.values())
        for key in sorted(expected - walker.reached):
            site = Site(_label(path, root), key[0], key[1], "<not reached by walker>")
            unresolved.append(Unresolved(site, "statement context not supported", False))

    winners: dict[str, Registration] = {}
    counts: Counter[str] = Counter()
    for reg in registrations:
        counts[reg.address] += 1
        winners[reg.address] = reg  # add_handler is a dict assignment: last wins

    entries: list[CatalogEntry] = []
    for address in sorted(winners):
        reg = winners[address]
        group, verb, prop = classify_address(address)
        entries.append(
            CatalogEntry(
                address=address,
                group=group,
                verb=verb,  # type: ignore[arg-type]
                prop=prop,
                args=_with_extra_index_args(address, _signature(verb, reg.callback)),
                risk=classify_risk(address, verb),
                source=f"{reg.site.label}:{reg.site.lineno}",
                replies=reg.replies,
            )
        )
    duplicates = tuple(sorted(a for a, n in counts.items() if n > 1))
    return CatalogBuild(
        entries=tuple(entries),
        unresolved=tuple(sorted(unresolved, key=lambda u: (u.site.label, u.site.lineno))),
        call_sites=call_sites,
        concrete_addresses=len(registrations),
        duplicate_addresses=duplicates,
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_HEADER = (
    "# generated - do not edit. Regenerate with: python -m dawn_core._gen_catalog\n"
    "# Source: the Remote Script's add_handler registrations (see _gen_catalog.py).\n"
)


def _arg_source(arg: ArgSpec) -> str:
    return f'ArgSpec(name="{arg.name}", kind="{arg.kind}", variadic={arg.variadic})'


def render(entries: Sequence[CatalogEntry]) -> str:
    """Render the committed module text. Output is deterministic and ruff-formatted."""
    lines = [_HEADER, "from ._catalog_types import ArgSpec, CatalogEntry", ""]
    if not entries:
        lines.append("ENTRIES: tuple[CatalogEntry, ...] = ()")
    else:
        lines.append("ENTRIES: tuple[CatalogEntry, ...] = (")
        for entry in entries:
            lines.append("    CatalogEntry(")
            lines.append(f'        address="{entry.address}",')
            lines.append(f'        group="{entry.group}",')
            lines.append(f'        verb="{entry.verb}",')
            lines.append(f"        prop={_none_or_str(entry.prop)},")
            lines.extend(_args_lines(entry.args))
            lines.append(f'        risk="{entry.risk}",')
            lines.append(f'        source="{entry.source}",')
            lines.append(f"        replies={_replies_text(entry.replies)},")
            lines.append("    ),")
        lines.append(")")
    return "\n".join(lines) + "\n"


def _args_lines(args: Sequence[ArgSpec]) -> list[str]:
    """Lay out ``args=`` the way ruff format would, so the committed module is stable."""
    if not args:
        return ["        args=(),"]
    if len(args) == 1:
        one_line = f"        args=({_arg_source(args[0])},),"
        if len(one_line) <= 100:
            return [one_line]
    lines = ["        args=("]
    lines.extend(f"            {_arg_source(a)}," for a in args)
    lines.append("        ),")
    return lines


def _none_or_str(value: str | None) -> str:
    return "None" if value is None else f'"{value}"'


def _replies_text(value: bool | None) -> str:
    return "None" if value is None else str(value)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _report(build: CatalogBuild) -> None:
    print(f"add_handler call sites:        {build.call_sites}")
    print(f"concrete addresses produced:   {build.concrete_addresses}")
    print(f"unique catalog addresses:      {len(build.entries)}")
    if build.duplicate_addresses:
        print(f"addresses registered twice:    {len(build.duplicate_addresses)} (last wins)")
    per_group = Counter(e.group for e in build.entries)
    print("per group: " + ", ".join(f"{g}={per_group[g]}" for g in sorted(per_group)))
    per_risk = Counter(e.risk for e in build.entries)
    print("per risk: " + ", ".join(f"{r}={per_risk[r]}" for r in RISK_CLASSES))
    per_replies = Counter(e.replies for e in build.entries)
    print(
        f"replies: True={per_replies[True]}, False={per_replies[False]}, None={per_replies[None]}"
    )
    for item in build.unresolved:
        status = "allowed" if item.allowed else "UNRESOLVED"
        print(
            f"{status} {item.site.label}:{item.site.lineno}: {item.site.expr}  ({item.reason})",
            file=sys.stderr if not item.allowed else sys.stdout,
        )


def main(argv: Sequence[str] | None = None, *, output_path: Path = OUTPUT_PATH) -> int:
    parser = argparse.ArgumentParser(prog="python -m dawn_core._gen_catalog")
    parser.add_argument("--check", action="store_true", help="fail if the module is stale")
    parser.add_argument("--root", type=Path, default=None, help="Remote Script package dir")
    args = parser.parse_args(argv)
    build = build_catalog(args.root)
    _report(build)
    if build.failing:
        print(
            f"error: {len(build.failing)} add_handler call site(s) could not be expanded",
            file=sys.stderr,
        )
        return 1
    text = render(build.entries)
    if args.check:
        current = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        if current != text:
            print(f"stale: {output_path} differs; run python -m dawn_core._gen_catalog")
            return 1
        print("catalog is fresh")
        return 0
    output_path.write_text(text, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
