# Compatibility

This document describes the verified code contract for beta `0.1.x`. It is deliberately narrower than what may happen to work in an individual environment.

## Runtime baseline

| Area | `0.1.0` status | Notes |
| --- | --- | --- |
| Python | 3.11+ | Declared by package metadata; CPython is the expected interpreter |
| Third-party runtime packages | None | Standard library only at runtime |
| Model providers | Host-neutral | Core makes no LLM or network call |
| Languages | RU and EN routing rules | Other locales use the same deterministic API but are not a declared routing-quality target |
| Packaging | Source tree, editable install, wheel/sdist design | Build tooling is a development extra |
| Native Windows | Core, CLI, profile loader, memory-off Hermes plugin | Optional SQLite memory ledger is not enabled on Windows in `0.1.x` |
| Persistent memory | POSIX local filesystem only | Requires `fcntl`, owner/mode semantics, local locking, and atomic replacement |

## Operating systems

### Linux and macOS

These are the intended beta environments for the complete runtime, hardened profile loader, Hermes adapter, offline suite, and optional SQLite memory backend. Deploy on a local filesystem owned by the service account.

An intended environment is not automatically a certified platform. Run the full tests, `humanlike doctor`, and `humanlike eval` on the exact Python and filesystem used in deployment.

### Native Windows

Native Windows supports the standard-library core, `humanlike route`, `humanlike eval`, `humanlike doctor`, read-only persona/config/foundation loading, and the wheel-installed Hermes plugin with memory disabled. Windows loaders reject lexical traversal, symlinks, junctions and other reparse points, enforce file bounds, and compare file identity before and after opening.

The optional `SQLiteMemoryLedger` remains unavailable on native Windows in `0.1.x`. It depends on POSIX owner/mode checks, descriptor-relative traversal, `flock`, and directory durability semantics. Enabling `memory_enabled = true` on Windows fails closed instead of silently using weaker storage guarantees.

WSL2 provides the POSIX interfaces required by the complete stack. Keep memory state on the WSL Linux filesystem rather than a mounted Windows or synchronized directory.

## Filesystems

Supported memory storage assumptions:

- local filesystem;
- stable inode identity;
- working advisory `flock` semantics;
- atomic same-directory replacement;
- owner and mode enforcement;
- no symlink or hardlink indirection.

Network filesystems, cloud-synchronized folders, shared volumes, removable drives, container bind mounts with altered ownership semantics, and backup staging directories are not supported for the SQLite ledger unless independently validated. Core routing with memory disabled does not have this storage dependency.

## Hermes host contract

The reference adapter uses a version-neutral boundary around the directory-plugin hook surface. The `0.1.0` reference plugin's manifest, import, and four-hook registration were doctor-smoke-tested with Hermes `v0.21.0`; this is an integration checkpoint, not a promise of compatibility with every `0.21.x` distribution. It registers exactly:

- `pre_llm_call`
- `transform_llm_output`
- `post_llm_call`
- `on_session_finalize`

The manifest schema version is `1`, the plugin kind is `standalone`, and the profile schema is `humanlike-hermes/v1`.

Hermes distributions can change installer commands, payload fields, hook semantics, and transcript behavior independently. Before using another Hermes release:

1. Install the complete repository root as the plugin directory.
2. Run `humanlike doctor --config examples/hermes-humanlike/humanlike.toml`.
3. Confirm all four hooks register.
4. Exercise first turn, sequential turns, cancelled turns, malformed payloads, output transformation, and session finalization in a non-production profile.
5. Confirm the host's transcript behavior and no-save expectations.
6. Run `humanlike eval` (or pass `--cases-dir` for a reviewed custom suite).

Passing `doctor` validates the local profile; it does not prove host-version compatibility.

## CLI compatibility

All commands write one JSON object to standard output.

| Command | Success | Behavioral failure | Invalid input/config |
| --- | --- | --- | --- |
| `humanlike route` | `0` | Not applicable | `2` |
| `humanlike doctor` | `0` | Not applicable | `2` |
| `humanlike eval` | `0` | `1` | `2` |

Error responses use fixed labels and do not echo rejected text or paths. JSON field order is stable, but the beta line does not promise that every field will remain unchanged in later versions.

## Profile compatibility

`humanlike-hermes/v1` accepts only these top-level fields:

- `schema`
- `profile_id`
- `persona_path`
- `memory_enabled`
- `acknowledge_host_context_persistence`
- `state_path`
- `normal_context_chars`
- `deep_context_chars`

Unknown fields are rejected. Persona and state paths must be relative and stay inside the profile root. Context limits are validated by `RuntimeConfig`; deep context cannot be smaller than normal context.

## Upgrade policy during beta

- Treat every minor beta change as potentially incompatible.
- Keep profile, pack, and fixture changes in the same reviewed commit as the runtime change they require.
- Run unit tests, lint, doctor, offline conformance, package build, and an isolated install before deployment.
- Roll out to a non-production profile first.
- Keep a recoverable copy of the prior plugin directory and state image, subject to the same privacy controls as production state.
- Do not downgrade a memory image unless the target version explicitly supports that schema.
