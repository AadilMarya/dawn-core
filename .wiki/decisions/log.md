# Decisions log

> Append-only ADRs, newest first. One entry per architectural decision: context, decision, rationale, consequences, status.

---

## ADR-0016 — The public repository starts at 0.1.0 with a clean history (2026-10-19)

**Context.** The internal repository's history held the private DAWN surface: the
arrangement writer, the browser loader, the master/return handlers, the rich note
protocols, the verified-mutation layer, the session snapshot, the `dawn_community` package
and the `dawn_c` framework fork. A visibility flip on that repository would have published
all of it, because the objects stay reachable from the old commits.

**Decision.** Publish a new repository, `github.com/AadilMarya/dawn-core`, built from a
fresh `git init` over an export of the sanitized tree. Its history is four commits —
transport, agent, gates, docs — with no shared ancestor to the internal history. The
internal repository stays private and keeps the full record, including the tag that
preserves the private surface. The public baseline is version **0.1.0**, not the internal
0.3.0: the public project starts its own numbering at its first release.

**Rationale.** A public repository's history is permanent and forks copy it wholesale.
Starting from a clean history makes "the private surface is not public" a property of the
object graph rather than a promise, and it can be verified by walking every blob.

**Consequences.** The public version is 0.1.0 across both distributions, the changelog and
the docs. The PyPI publish moved out of the tag workflow into a manually triggered
`publish.yml`, so tagging a release creates a GitHub release and cannot publish to PyPI
before the trusted publisher is configured. The internal repository is not a publish
target and must never be made public.

**Evidence.** The public history contains 162 objects and no private-surface path; a scan
of every blob finds upstream names only in the two notices files and no private
identifiers. Each of the four commits passes pytest, ruff, the format check, mypy, the
catalog freshness check and a build on its own.

**Status.** Accepted.

---

## ADR-0015 — The open surface is a stripped upstream fork; the private surface is preserved (2026-10-19)

**Context.** The open repo shipped the same full control surface as the private DAWN app,
including the arrangement writer, browser loader, master/return handlers, rich note
protocols, verified-mutation layer and session snapshot. That leaks product surface and
couples the two releases.

**Decision.** The open repo ships a DAWN-branded fork of the upstream OSC control surface:
the upstream `/live/*` handlers plus the DAWN HMAC envelope and exactly two DAWN metadata
endpoints (`/dawn/version`, `/dawn/security/status`). The catalog drops from 636 to 496
addresses. The full surface is preserved for the private DAWN app, which owns its own
script.

**Consequences.** The open tools drop `load_device` and `set_track_volume` (no browser
loader, no calibrated dB). The open surface keeps HMAC, loopback-only transport. The
private app stopped pointing at the open `dawn-osc` script and vendors the preserved
surface in its own tree, overlaying its protocol-2.33 files on top. One `DAWN` surface
name is used; installing the open package and the private app on the same Live install
replaces one with the other.

**Status.** Accepted.

---

## ADR-0013 — Delete the vendored agent framework; use the upstream runtime (2026-10-19)

**Context.** `dawn_c` was a 19 MB generated fork of an upstream MIT agent framework, renamed
and vendored. It made every install of the Ableton layer carry a framework, and it made
"swap the agent" impossible without editing the fork. The reference agent was the only
consumer; the DAWN app never imported it.

**Decision.** Delete `dawn_c` from the workspace and depend on `pydantic-ai-slim` as an
ordinary runtime dependency of `dawn-core`. Keep the provider SDKs as extras. Preserve the
fork at tag `v0.1.0-fork` for recoverability.

**Rationale.** An open-source base should not ship a renamed framework. Upstream gives
contributors documentation, provider support and a release cadence. The cost is a public
dependency and provider extras, which the quickstart documents.

**Consequences.** `dawn-core` depends on `pydantic-ai-slim>=2,<3`; `openai`, `anthropic`,
`google` and `ollama` are extras. The notices list the runtime dependency instead of derived
code. The licensing scan no longer bans the upstream framework's name, only the two projects
whose code is actually derived or vendored.

**Status.** Accepted.

---

## ADR-0012 — Remove the CLI and MCP surfaces from the open core (2026-10-19)

**Context.** The product had four CLI commands (`chat`, `run`, `install-script`, `doctor`)
and an MCP server for authoring tools. Neither is the agent. The CLI forced an agent runtime
and a provider into every install; the MCP server added a protocol layer with no consumer in
the new design.

**Decision.** Delete `cli.py`, `dawn_core.sdk`, the `mcp` dependency, the CLI entry point and
the MCP docs/examples/tests. Installation and health checks become library functions:
`install_script()`, `check_install()` and `check_install_async()`. The harness calls them
directly.

**Rationale.** The host owns the process, the model and the UI. A library can be embedded;
a CLI cannot. Removal also makes `pip install dawn-core` lean and keeps the public surface
small enough to document.

**Consequences.** No `dawn-core` console script. `test.sh` invokes Python for install and
checks. The DAWN app's own MCP server is a separate feature and is unaffected.

**Status.** Accepted.

---

## ADR-0011 — The repository is the music agent, not a generic control plane (2026-10-19)

**Context.** DAWN Core had drifted toward a product shell: a generated catalog, a generic
group-tool surface, a CLI, an MCP SDK and a vendored framework. The question was whether to
keep widening the SDK or to ship the thing the project is actually for: an agent that makes
music in Ableton.

**Decision.** The repository ships **the agent**: `MusicAgent`, a producer's system prompt,
curated musical tools and a consent-gated session. DAWN embeds it in-process. Users can swap
the model, the expertise subset, the prompt or the tool list, or use the tools and prompt
with their own loop.

**Rationale.** The moat is the tuning and the verified control, not a protocol. A generic
control plane would be a smaller, less useful product and would compete with every agent
framework. An agent with a clear taste is a better base and a better demo.

**Consequences.** The public API is `MusicAgent`, `build_tools`, `SYSTEM_PROMPT`,
`OscSession`, `Consent` and the install helpers. The generic `<group>_get/_set/_call` tools
are replaced by 27 curated tools plus `catalog_call`. The prompt becomes part of the product
and is budget-tested. The event stream and arrangement tools are deferred to a later
release.

**Status.** Accepted.

---

## ADR-0009 — People plug in their own agents through MCP, not through imports (2026-10-17)

**Context.** DAWN Core is published so people can build their own agents and use them in DAWN.
The closed application must never import this repo (ADR-0675 boundary), so the plug-in contract
cannot be a Python API loaded into DAWN's process. DAWN already has an MCP host that connects to
servers it is told about, with per-call audit and untrusted-result shaping.

**Decision.** `dawn_core.sdk` lets an author write typed tools with a risk class and serve them
as an MCP server (stdio, or loopback HTTP). DAWN connects through its existing MCP host; nothing
new is added to the application. Consent is the existing fail-closed `Consent`, applied to every
tool call, and a refusal is reported to the client as a tool error with its reason.

**Rationale.** Process isolation keeps third-party code out of DAWN's process and keys out of its
reach; any MCP client works, not only DAWN; the SDK stays a thin layer over `dawn_c` and
`dawn_core.safety`. `mcp` is allowed across `>=1.20,<3` because the application's host runs 1.x
while the workspace lock resolves 2.x.

**Consequences.** Adds the `mcp` dependency. A tool crash or hang is the author's process, not
DAWN's. Whether a DAWN build ships MCP server support is a release decision outside this repo.
An in-application plug-in contract (manifest, in-process agents) is deferred.

**Evidence.** 400 tests; a real stdio subprocess round-trip; DAWN's MCP host (client `mcp` 1.29)
connected to the example server (`mcp` 2.3), listed both tools and called `word_count` (result 4)
with untrusted-data shaping applied. Not run: a live DAWN chat turn using the tool, Ableton.

**Status.** Superseded by ADR-0012.

---

## ADR-0008 — The workspace is DAWN Core; `dawn_community` becomes `dawn_core` (2026-10-17)

**Context.** The repo is being published as the open agent framework people build on and plug
into DAWN, not as a "community edition" of a product. `dawn_c` (the framework) already reads as
"DAWN Core".

**Decision.** The product name is DAWN Core. The package, distribution and CLI are `dawn_core` /
`dawn-core` / `dawn-core`; the environment variables are `DAWN_CORE_*`. `dawn_c` and `dawn_osc` are
unchanged. The repo directory moves to `dawn-core` as a separate, last step.

**Consequences.** Pre-release, so no deprecation shim. ADR-0001..0007 keep the old name as written.
Anything outside this repo that depends on the old names (path sources, scripts, env vars) must
follow.

**Evidence.** 381 tests, ruff, format, mypy and the catalog freshness check pass after the rename.

**Status.** Accepted.

---

## ADR-0007 — Installed-script comparison skips Live-written runtime files (2026-10-13)

**Context.** `script_matches()` hashed every file under the installed `DAWN` folder. After
Live ran once, its `logs/dawn_osc.log` and `dawn_instance.json` were present, so the folder
never matched the packaged tree again: `doctor` reported a healthy install as different and
advised `install-script --force`, and `./test.sh` would have asked to replace a good copy.

**Decision.** Compare the deployable tree only, skipping exactly the names the Remote
Script's own revision digest skips (`_REVISION_PRUNED_DIRS` / `_REVISION_SKIPPED_FILES` /
suffixes / prefixes in `DAWN/__init__.py` — the list its comments declare a wire contract
with the host-side installer, ADR-0476 upstream). A regression test writes every runtime
artifact into an installed copy and asserts `script_matches` stays true.

**Consequences.** A used install compares equal; `doctor` and the harness stop crying wolf.
The two skip lists are a contract: change them together with the script's digest. Runtime
files still do not ship: a fresh install copies the packaged tree only.

**Status.** Accepted.

---

## ADR-0006 — Python support: widen to `>=3.11`, no upper cap (2026-10-13)

**Context.** `dawn_osc` and `dawn_community` declared `requires-python = ">=3.11,<3.13"`,
so users on 3.13+ could not install them.

**Decision.** Relax both to `>=3.11` with no upper bound; re-lock the workspace so
`uv.lock` spans 3.13/3.14 (e.g. the resolution now picks a different datetime package on
3.13+). Validated by running the full suite on CPython 3.13 and 3.14 — both green.

**Consequences.** Install works on any current Python. No CI exists yet (ADR-0005), so
future 3.15 support rests on the same manual matrix run. `.python-version` still pins 3.12
for local work.

**Status.** Accepted.

---

## ADR-0005 — Release approach: repo readiness now, no tag or publish (2026-10-13)

**Context.** The repository is pre-release with no tags. "Make it ready to release" could
mean an immediate tagged release or readiness work only.

**Decision.** Keep version **0.1.0** across all packages; do the readiness work (package
READMEs, project URLs, docs, `CHANGELOG.md`, `./test.sh`, wiki, Python-support widening);
do **not** tag, merge, push a PR, or publish now. GitHub Actions CI is deferred.

**Rationale.** The owner wants the option to release at any time, not a release today.

**Consequences.** README says "release-ready; not yet published", changelog says
"0.1.0 — unreleased". A future tag must be cut from a commit where all gates pass; the
harness and gates are documented in [[modules/harness-and-gates]].

**Status.** Superseded by ADR-0016 — the repository is now public and tagged `v0.1.0`.

---

## ADR-0004 — Consent is a fail-closed gate in front of every datagram (initial design)

**Context.** An agent driving Live can delete clips, scenes and tracks.

**Decision.** `OscSession` authorizes every call in a fixed order — catalog membership,
argument types, then `Consent` — before sending. `Consent` allows reads always, writes
unless `read_only`, and destructive calls only with `yes` or a synchronous `confirm`
returning exactly `True`. Unknown risk, callback exceptions and non-`True` answers deny.
The CLI's `chat` asks on the terminal; `run` denies unless `--yes`.

**Rationale.** Fail closed: the default (`Consent()`) must never be able to destroy work,
and the framework must not be able to bypass the user's policy (`build_agent` pins the
session's `Consent` instance).

**Consequences.** A new destructive endpoint must classify as `destructive` in the
generator ([[modules/catalog]]) or the policy cannot see it.

**Status.** Accepted.

---

## ADR-0003 — The OSC catalog is generated from the Remote Script AST and gated on freshness (initial design)

**Context.** The agent needs an exact, typed index of every OSC address the Remote Script
serves; keeping a hand-written list in sync with ~20 handler modules is error-prone.

**Decision.** Generate `_catalog_data.py` from the script source with `ast` only (the
script cannot be imported outside Live), commit it, and fail a gate
(`python -m dawn_community._gen_catalog --check`) when it is stale or has unresolved call
sites. `OscSession` refuses any address not in the catalog.

**Rationale.** One source of truth; a divergence is a build error, not a runtime surprise.

**Consequences.** Handler registrations must stay statically analyzable (loops over known
iterables; last registration wins). `ALLOWED_UNRESOLVED` stays empty by policy. Per-address
index overrides live in `_EXTRA_INDEX_ARGS` when a wrapper hides an argument.

**Status.** Accepted.

---

## ADR-0002 — Remote Script: neutral names; attribution only in the notices (2026-10-08, `dcee7d1`)

**Context.** The script began as a fork of a third-party OSC control surface; its internal
names (handler package, base class, logger, log file, log prefixes) still carried the
upstream project's identity.

**Decision.** Rename internals neutrally (`handlers/`, `OscHandler`, logger `dawn_osc`,
`logs/dawn_osc.log`), keep behaviour identical, and let `THIRD_PARTY_NOTICES.md` carry the
attribution (winning over upstream names appearing in code). `REPLY_TIMEOUT_PREFIX` is
exported so transport and agent share one timeout text.

**Consequences.** The licensing scan ([[modules/harness-and-gates]]) enforces the split:
upstream names outside notices fail the suite. Notices "Used in" paths must track renames.

**Status.** Accepted.

---

## ADR-0001 — `dawn_c` is a generated rebrand of an upstream MIT framework (2026-10-08, `9985be9`)

**Context.** The product needs a full agent framework (models, tools, streaming, durable
execution); building that from scratch was out of scope.

**Decision.** Vendor a rebranded copy as `dawn_c` (package `dawn-c`), generated by a rebrand
script whose output is committed; package/module/distribution names, product names and
environment variables are renamed, upstream docs links and deprecated shims are stripped.
Provenance, license and modification notes live in `THIRD_PARTY_NOTICES.md`; the upstream
license block is copied verbatim there and in the root notices.

**Rationale.** Reuse a proven MIT-licensed framework while keeping the public surface
coherent and the attribution exact.

**Consequences.** `dawn_c/src` is excluded from lint, format and the upstream-name scan
(still scanned for private identifiers); never hand-edit generated files expecting them to
survive regeneration ("edit the generator, not this file").

**Status.** Superseded by ADR-0013.

## Related

- [[index]] · [[architecture/overview]] · [[modules/harness-and-gates]]
