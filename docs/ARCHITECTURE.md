# Architecture

Humanlike is an in-process behavioral planning library. It sits between an agent host and that host's model call, but it does not replace either one.

## System boundary

```text
user turn
   |
   v
agent host ---- host-owned transcript, tools, model, network
   |
   | TurnInput
   v
HumanlikeRuntime.prepare()
   |-- deterministic route and social move
   |-- optional scoped memory recall
   |-- discourse, creative, stance, and drift guidance
   |-- persona and mandatory truth/privacy tails
   v
bounded TurnPlan.render_context()
   |
   v
agent host assembles prompt and calls its model
   |
   | TurnOutcome plus optional validated records/probes
   v
HumanlikeRuntime.observe() -> BehaviorReceipt
   |
   v
HumanlikeRuntime.finalize() drops session metadata
```

Core owns deterministic planning and bounded metadata. The host owns message delivery, model inference, tool execution, credentials, transcript storage, and operational policy.

## Public contracts

The primary immutable contracts are defined in `src/humanlike_agent/models.py`:

- `TurnInput` — current text plus bounded turn/session identifiers, locale, elapsed time, and memory scope.
- `RouteDecision` — cognitive mode, social move, response budget, candidate count, constraints, confidence, and truth/tool flags.
- `ContextFragment` — one ranked context block with hard, tail, and truncation properties.
- `TurnPlan` — route plus fragments and a hard character limit.
- `TurnOutcome` — host-reported response metadata; it has no assistant-text field.
- `BehaviorReceipt` — route, fragment, rule, memory, tool, and error metadata plus a keyed turn fingerprint.
- `SessionRef` — opaque host session reference used for cleanup.

Contracts are frozen dataclasses and serialize to JSON-safe dictionaries through `to_dict()`.

## Component map

| Component | Responsibility | Persistent state |
| --- | --- | --- |
| `router.py` | Deterministic RU/EN cognitive-mode and social-move selection | None |
| `persona.py` | Safe persona parsing, bounded anchor, mandatory AI-truth contract | None |
| `discourse.py` | Bounded tactic history and repetition avoidance | In-memory session metadata |
| `stance.py` | Deterministic correction, challenge, and verification guidance | None |
| `drift.py` | Probe scoring and re-anchor requests | In-memory session metadata |
| `creative.py` | Mechanism-diverse planning and rights-aware pack loading | Local read-only pack files |
| `memory.py` | Typed evidence-aware records, recall, supersession, and deletion | Optional local SQLite image |
| `runtime.py` | Orchestration, budgets, isolation, receipts, and lifecycle | Bounded in-memory metadata; optional memory port |
| `evals.py` | Strict offline fixture loading and conformance reporting | Temporary per-run state |
| `adapters/hermes.py` | Translation between four Hermes hooks and core contracts | Bounded in-memory active-turn map |

## Prepare path

`HumanlikeRuntime.prepare()` performs these steps under a re-entrant lock:

1. Validate identifiers, text size, scope, session count, and active-turn count.
2. Route the turn; if routing fails, use a conservative strict-truth fallback.
3. Propagate session-level no-save state.
4. Build trusted route and discourse fragments.
5. Add a hard no-persistence tail when required.
6. Recall scoped memory only when memory is configured and the route allows it.
7. Add creative or stance guidance only for relevant routes and explicit probes.
8. Add persona guidance and an untruncatable AI-truth tail.
9. Rank fragments and render within the configured normal or deep character limit.
10. Retain only bounded metadata and a keyed fingerprint for observation.

Hard fragments must fit in the configured limit. Optional fragments are ranked, skipped, or truncated. Mandatory tail fragments render last and cannot be silently dropped.

## Observe and finalize paths

`observe()` matches an outcome to a prepared turn, filters tactic/tool/error identifiers through allowlists, optionally consumes a drift probe, and returns an idempotent receipt. A durable memory write is possible only when all of the following are true:

- the host reports a successful outcome;
- the original turn explicitly requested saving;
- neither turn nor session is in no-save mode;
- a memory backend is configured;
- no component or host error blocks the write;
- the host supplies a tuple of validated records for the same profile and session.

The reference Hermes adapter always supplies an empty record tuple, so it never derives durable memories from message text.

`finalize()` removes the session's discourse/drift state, pending turns, completed receipts, identifiers, and fingerprints. Durable records already accepted by a configured memory backend are not session metadata and are not deleted by finalization.

## Hermes adapter

The root-level directory-plugin shim loads the bundled core in an installation-specific private module namespace and rejects symlinked source-tree entries before execution. The adapter registers exactly:

1. `pre_llm_call` — returns a single bounded `context` string.
2. `transform_llm_output` — corrects only an exact full-response claim of biological humanity; otherwise returns no change.
3. `post_llm_call` — reports response length and conservative host status without retaining response text.
4. `on_session_finalize` — retires runtime-owned ephemeral session metadata.

Malformed or unsupported hook payloads fail neutral. A broken profile still registers neutral callbacks so plugin loading does not break the host lifecycle.

## Memory architecture

`SQLiteMemoryLedger` stores typed atoms with profile/session scope, kind, key/value, confidence, validity window, evidence digest, tags, and supersession references. It is a POSIX local-filesystem backend, not a general database service.

The ledger uses owner-only directories/files, advisory locking, bounded serialized SQLite images, integrity checks, atomic replacement, and explicit rejection of symlinks and hardlinks. Values are plaintext inside the local database image; encryption at rest belongs to the deployment environment.

## Error model

Optional behavior components fail open by omitting their context and adding bounded error codes to the eventual receipt. Mandatory truth and privacy controls use hard fragments or conservative fallback plans. Hermes hook boundaries catch malformed payloads and runtime failures, returning no mutation rather than exposing exception text to the host.

This error model protects host availability. It does not mean a deployment can ignore diagnostics: receipts, CLI exit codes, and conformance results should be monitored during integration testing.

## Extension points

- Construct `HumanlikeRuntime` with another memory port implementing compatible `recall` and `remember` behavior.
- Supply a validated `FoundationPack` for creative planning.
- Pass `StanceProbe` and `BehaviorProbe` values from a trusted host classifier.
- Build another host adapter around `prepare`, `observe`, and `finalize`.

Extensions must preserve bounded input/output, profile isolation, explicit memory consent, and the mandatory truth/privacy tails.
