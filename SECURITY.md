# Security policy

## Supported versions

The latest release receives security fixes.

## Reporting

Open a private security advisory on GitHub:
<https://github.com/AadilMarya/dawn-core/security/advisories/new>

Do not open a public issue. Include the version, a minimal reproduction, and the impact.

## Model

DAWN Core controls Ableton Live on the local machine.

- OSC is loopback-only and HMAC-authenticated; unsigned, replayed and non-loopback traffic
  is rejected.
- The shared secret is an owner-only session file.
- Destructive tools are refused unless the session's `Consent` allows them.
- The Remote Script runs inside Live with the full Live Object Model. Review it before
  installing.

See [`docs/security.md`](docs/security.md) for the full threat model.
