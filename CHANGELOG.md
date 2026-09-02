# Changelog

All notable changes to Humanlike are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The `0.1.x` beta line does not yet promise API stability.

## [Unreleased]

### Added

- Added a bilingual Hermes wheel-entry-point installation path with runtime validation, commit pinning, rollback, and removal.
- Added a memory-off starter runtime that Hermes discovers from the installed Python package.

### Changed

- Prepared the repository documentation for public beta availability under the MIT License.
- Shortened the public product and repository name to **Humanlike** while keeping the `humanlike-agent-kit` package and plugin identifiers stable for compatibility.

## [0.1.1] - 2026-09-01

### Changed

- Relicensed the repository and bundled foundation pack under the MIT License.
- Reworked the README into an English/Russian product guide with verified quickstart commands, project boundaries, author links, and attribution links.
- Added contributor guidance, third-party acknowledgements, security-reporting guidance, and complete package metadata.
- Reconciled stale proprietary-distribution wording with the MIT license while preserving the private-beta repository status.

### Fixed

- Synchronized foundation-pack rights declarations and manifest hashes with the repository license.
- Fixed installed-wheel `humanlike eval` on Linux environments where package installers use hardlinks for bundled data, while keeping external pack loading single-link strict.
- Added regression checks that prevent proprietary metadata from reappearing in an MIT release.

## [0.1.0] - 2026-09-01

### Added

- Immutable host/runtime contracts for turns, plans, outcomes, receipts, and sessions.
- Deterministic RU/EN routing across cognitive modes and social moves.
- Bounded context composition with mandatory AI-truth and no-persistence policies.
- Persona loading and anchoring with root-confined file access.
- Discourse repetition controls, stance guidance, drift probes, and conditional re-anchoring.
- Deterministic creative planning with a bundled, rights-declared foundation pack.
- Optional evidence-aware SQLite memory with explicit-consent writes, validity windows, supersession, conflict inspection, and privacy-oriented storage checks.
- Provider-neutral orchestration that makes no model or network calls.
- Reference Hermes directory plugin for four lifecycle hooks.
- Stable JSON CLI commands: `route`, `doctor`, and `eval`.
- Offline conformance reports for route, social move, privacy, context budget, policy, disclosure, stance, memory, and drift.
- Architecture, privacy, compatibility, security, and threat-model documentation.

### Security

- Added bounded parsing, path confinement, symlink and unsafe-permission rejection, metadata allowlists, fail-neutral host behavior, and owner-only POSIX memory storage.

### Known limitations

- The hardened profile loader and SQLite memory backend are POSIX-oriented and are not supported on native Windows.
- Runtime `no-save` does not control copies retained by an agent host or model provider.
- The Hermes output transform is intentionally narrow and is not a general safety or policy filter.
