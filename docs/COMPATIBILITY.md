# Compatibility

This document describes the verified code contract for beta `0.4.x`. It is deliberately narrower than what may happen to work in an individual environment.

## Runtime baseline

| Area | `0.1.0` status | Notes |
| --- | --- | --- |
| Python | 3.11+ | Declared by package metadata; CPython is the expected interpreter |
| Third-party runtime packages | None | Standard library only at runtime |
| Model providers | Host-neutral | Core makes no LLM or network call |
| Languages | RU and EN routing rules | Other locales use the same deterministic API but are not a declared routing-quality target |
| Packaging | Source tree, editable install, wheel/sdist design | Build tooling is a development extra |
| Native Windows | Core, CLI, profile loader, memory-off Hermes plugin | Optional SQLite memory ledger is not enabled on Windows in `0.4.x` |
| Persistent memory | POSIX local filesystem only | Requires `fcntl`, owner/mode semantics, local locking, and atomic replacement |

## Operating systems

### Linux and macOS

These are the intended beta environments for the complete runtime, hardened profile loader, Hermes adapter, offline suite, and optional SQLite memory backend. Deploy on a local filesystem owned by the service account.

An intended environment is not automatically a certified platform. Run the full tests, `humanlike doctor`, and `humanlike eval` on the exact Python and filesystem used in deployment.

### Native Windows

Native Windows supports the standard-library core, `humanlike route`, `humanlike eval`, `humanlike doctor`, read-only persona/config/foundation loading, and the wheel-installed Hermes plugin with memory disabled. Windows loaders reject lexical traversal, symlinks, junctions and other reparse points, enforce file bounds, and compare file identity before and after opening.

The optional `SQLiteMemoryLedger` remains unavailable on native Windows in `0.4.x`. It depends on POSIX owner/mode checks, descriptor-relative traversal, `flock`, and directory durability semantics. Enabling `memory_enabled = true` on Windows fails closed instead of silently using weaker storage guarantees.

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

The original memory-off four-hook checkpoint used Hermes `v0.21.0`.
The 0.4.0 native bridge was exercised against Hermes 0.22.6, source `f0d94882`,
in an isolated synthetic home using real `PluginManager`, `PluginContext`,
`SessionSource` and `invoke_plugin_command` interfaces. This is not a live transport test.

The behavior hooks remain `pre_llm_call`, `transform_llm_output`, `post_llm_call`,
and `on_session_finalize`. A compatible host also gets `/humanlike` and
`post_gateway_admission`. The manifest schema is `1`, kind is `standalone`;
the legacy profile schema remains `humanlike-hermes/v1`.

| Surface | Native support |
|---|---|
| Telegram human DM, no thread | Consent/controls, admitted proposals, bounded memory/context injection |
| Native CLI | Session-local slash controls; no automatic context injection |
| Groups, threads, other transports | Explicit unavailable; memory-off behavior retained |
| Missing command/admission APIs | Memory-off hooks; compatibility response if commands are available |
| Native Windows | Memory-off behavior; persistent controls unavailable |

Transport source, not text fields, scopes identity. Because command metadata lacks
forwarded provenance, expanding permissions or changing a memory requires a fresh
single-use confirmation tied to the exact request, session and policy. Ordinary
admitted text only proposes writes. `/humanlike status` binds a new conversation;
there is no archive/session-database lookup to infer a binding after restart.

For another Hermes distribution, run the [install checks](HERMES_INSTALL.md), the
real-interface smoke, and a separately authorized live delivery canary. Local
`doctor` or a successful import alone does not prove delivery compatibility.

## CLI compatibility

See [0.4.0 stability contracts / EN+RU](STABILITY.md) for neutral routing, exact
conflict replacement, safe diagnostic states and compatible-reader rollback.

### Optional 0.2.0 host API

`PersonalMemory`, `ConversationContext`, `AuthorizedHost` and
`HermesAdapter.prepare_authorized` remain additive developer APIs. Integrators of
that lower-level path still own authorization/history callbacks. The 0.4.0 native
bridge supplies these bindings for its documented supported surface; it does not
change the legacy `memory_enabled` TOML option into owner consent. See the
[developer guide](PERSONAL_MEMORY.md) and [native setup](HERMES_INSTALL.md).

All commands write one JSON object to standard output.

| Command | Success | Behavioral failure | Invalid input/config |
| --- | --- | --- | --- |
| `humanlike route` | `0` | Not applicable | `2` |
| `humanlike doctor` | `0` | Not applicable | `2` |
| `humanlike eval` | `0` | `1` | `2` |
| `humanlike export-plugin` | `0` | Not applicable | `2` |

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
