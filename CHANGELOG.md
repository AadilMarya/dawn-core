# Changelog

## 0.1.0 — 2026-10-19

First public release. DAWN Core is the agent itself: an open-source AI music producer for
Ableton Live. The CLI, the MCP server and the vendored agent framework are gone. The agent
is a library that DAWN and any other host can embed.

### Added

- `MusicAgent` and `build_agent` on upstream `pydantic-ai-slim`. Swap the model, the
  expertise subset or the tool list.
- `dawn_core.prompt`: six doctrine sections (persona, production, arrangement, mixing, sound
  design, Ableton) composed into a system prompt with a token budget.
- 27 curated musical tools: session and transport, tracks, clips and notes, scenes, devices,
  plus `catalog_call` for the 496-address long tail. Every write is read back.
- `check_install()` / `check_install_async()` and `InstallReport`, replacing the `doctor`
  command.
- `MiniLive` is documented as the offline development double.
- Six agent-flow evals and a prompt contract test.
- CI for Python 3.11–3.13, a macOS harness job, and a PyPI trusted-publishing workflow.
- `docs/`: quickstart, architecture, tool reference, prompt guide, embedding, security,
  troubleshooting.
- `dawn_osc`: the `DAWN` Remote Script — a DAWN-branded fork of the upstream OSC control
  surface plus the HMAC envelope — with two DAWN endpoints, `/dawn/version` and
  `/dawn/security/status`.

### Changed

- The catalog records the `parameter_index` on the device parameter endpoints, and
  reclassifies browser listings as reads. This fixes device parameter writes.
- The open catalog is **496 addresses**. The Remote Script is the upstream handler surface
  plus the DAWN HMAC envelope: no arrangement writer, browser loader, master/return
  handlers, rich note protocols, verified-mutation layer or session snapshot.
- `default_remote_scripts_dir()` is cross-platform and honours
  `DAWN_CORE_REMOTE_SCRIPTS_DIR`.
- `dawn-core` depends on `dawn-osc`, `pydantic` and `pydantic-ai-slim`; provider SDKs are
  extras (`[openai]`, `[anthropic]`, `[google]`, `[ollama]`, `[all]`).
- `load_device` and `set_track_volume` are not part of the open tools. The script exposes
  the upstream linear `volume` property, not calibrated dB.

### Removed

- The `dawn-core` CLI (`chat`, `run`, `install-script`, `doctor`). Installation and checks
  are library functions; `examples/` shows the calls.
- `dawn_core.sdk` and the `mcp` dependency.
- `dawn_c`, the generated agent framework.

### Fixed

- `/live/device/set/parameter/value` and the parameter getters now declare the index the
  Remote Script handler actually consumes.
- A read-only session can list the browser.
