# Changelog

All notable changes to Humanlike Agent Kit are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This private beta does not yet promise semantic-versioning stability.

## [Unreleased]

### Changed

- Continued private-beta hardening and release validation.

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
- Private-beta architecture, privacy, compatibility, security, and threat-model documentation.

### Security

- Added bounded parsing, path confinement, symlink and unsafe-permission rejection, metadata allowlists, fail-neutral host behavior, and owner-only POSIX memory storage.

### Known limitations

- The hardened profile loader and SQLite memory backend are POSIX-oriented and are not supported on native Windows.
- Runtime `no-save` does not control copies retained by an agent host or model provider.
- The Hermes output transform is intentionally narrow and is not a general safety or policy filter.
