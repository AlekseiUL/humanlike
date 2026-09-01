# Security Policy

Humanlike Agent Kit is a private beta. Security reports are welcome, but the project does not currently offer a public bug bounty or a public vulnerability tracker.

## Supported versions

Only the current `0.1.x` private-beta line is maintained. Earlier snapshots and uncommitted development states are unsupported.

## Reporting a vulnerability

Report vulnerabilities privately through one of the repository's private maintainer channels:

1. Prefer a private GitHub Security Advisory if that feature is available for the repository.
2. Otherwise contact a maintainer through the same private channel that granted repository access.

Do not include secrets, private transcripts, production memory databases, or personal data in a public issue. Provide the smallest synthetic reproduction that demonstrates the problem.

A useful report includes:

- affected commit and package version;
- operating system and Python version;
- affected component (`core`, `Hermes adapter`, `profile loader`, `memory ledger`, or `conformance runner`);
- impact and expected trust boundary;
- reproduction steps using synthetic data;
- whether a symlink, hardlink, unusual filesystem, or concurrent process is involved.

Maintainers should acknowledge a report before discussing disclosure timing. No fixed response-time guarantee is offered during private beta.

## Security assumptions

- The process owner, plugin directory, profile directory, and installed Python interpreter are trusted.
- The hardened profile loader and SQLite memory ledger require a local POSIX filesystem with owner and mode semantics.
- The host is responsible for model-provider credentials, network controls, tool permissions, transcript retention, and process isolation.
- The runtime treats user text, recalled memory, creative-pack data, and host metadata as potentially malformed.
- A compromised operating-system account or privileged local attacker is outside the protection boundary.

## Built-in controls

- No model or network calls in core.
- Bounded inputs, context packets, identifiers, active sessions, and conformance suites.
- Root-confined profile and state paths with traversal and symlink rejection.
- Owner-only state directory and file modes for durable memory on POSIX.
- Atomic SQLite image replacement, file locking, integrity checks, and bounded database size.
- Metadata-only runtime snapshots and receipts without raw user or assistant messages.
- Explicit consent conditions for memory writes and session-level `no-save` propagation.
- Fail-neutral Hermes hooks for malformed payloads or component failures.
- A narrow output correction for exact false biological-identity claims; it is not a general content filter.

See [Threat model](docs/THREAT_MODEL.md) for scope, controls, and residual risks.

## Deployment guidance

- Keep the repository, profile, and state directory private to the service account.
- Do not run the plugin from a shared or group-writable checkout.
- Do not place the memory ledger on network, synchronized, or untrusted removable storage.
- Keep memory disabled unless the host integration has an explicit consent and retention policy.
- Treat context returned by `pre_llm_call` as sensitive host input.
- Validate a profile with `humanlike doctor` before enabling it in a host.
- Run the offline suite after every behavioral, profile, or pack change.
- Review the host's transcript policy independently; runtime `no-save` cannot delete host copies.

## Dependency and release hygiene

The installed runtime declares no third-party runtime dependencies, but the build backend and development tools are separate supply-chain inputs. Pin and review them in controlled build environments. Private-beta artifacts should be built from a reviewed commit and distributed only through authorized channels.
