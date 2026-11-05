# Privacy

Humanlike minimizes the data it owns, but it operates inside a larger agent host. This document separates runtime behavior from host and model-provider behavior.

## Privacy boundary

The runtime receives current-turn text to classify and prepare guidance. It does not place raw user or assistant messages in `BehaviorReceipt`, `RuntimeSnapshot`, or `TurnOutcome`, and it does not call a network service.

The host may independently retain:

- user and assistant messages;
- system prompts and injected context;
- tool calls and results;
- model-provider request logs;
- application telemetry and backups.

Runtime `no-save`, expiry, deletion, and finalization cannot erase those host-owned copies. Review the host's retention policy separately.

## Data inventory

| Data | Used for | Runtime retention |
| --- | --- | --- |
| Current user text | Routing, lexical memory query, and creative planning | Processed during `prepare()`; raw text is not stored in runtime state |
| Turn and session identifiers | Lifecycle matching and isolation | Bounded in memory until completion, eviction, or `finalize()` |
| Rendered context | Host prompt guidance | Returned to the host; runtime retains only character count and fragment identifiers |
| Route, policy, tactic, tool, and error identifiers | Behavior receipt and diagnostics | Bounded in memory until eviction or `finalize()` |
| Turn fingerprint | Idempotent privacy-oriented correlation | Keyed HMAC in a receipt; no raw text; removed by `finalize()` |
| Persona | Identity, voice, values, and truth boundaries | Loaded from a local rooted profile and held by the runtime instance |
| Creative pack | Rubric and anti-pattern guidance | Loaded from local files; pack content may enter rendered context |
| Memory records | Explicitly approved durable recall | Optional plaintext local SQLite image |

Fingerprints reduce direct exposure but are not anonymization. The default key is generated per runtime instance, so fingerprints are not intended as stable cross-process user identifiers.

## Core no-save behavior

The router recognizes explicit item-level and session-level no-save requests. The strictest scope wins.

For no-save turns:

- a hard `MANDATORY_NO_PERSISTENCE_POLICY` fragment is included in the context;
- durable memory recall and writes are blocked as applicable;
- session-level no-save remains active until `finalize()`;
- using a real ledger still creates no state directory when no write is permitted.

No-save governs runtime-owned durable memory. It cannot force an external host, model provider, logger, shell history, backup system, or observability platform to delete data.

## Durable memory

Durable memory is optional and disabled in the example Hermes profile. When enabled, the core can store only host-supplied `MemoryRecord` values that pass the runtime's consent and validation checks.

Each record contains a typed kind, key, scalar value, confidence, timestamps, validity, evidence reference, optional tags, and optional supersession references. The schema intentionally has no raw-transcript column. A host could still put sensitive or transcript-like text into a record value, so the host must validate and minimize records before submission.

The core behavior hooks do not derive records from message text. Enabling a state path alone therefore does not create conversational memory. The optional [consented host API](PERSONAL_MEMORY.md) captures only explicit authorized atoms; it retains scoped relation metadata, event-ID hashes and durable revocation fences in the same ledger. Its no-save policy blocks capture, while explicitly authorized read-only conversation references remain available.

### Storage properties

- POSIX local filesystem only.
- State directory must be owner-only mode `0700` when writable.
- Database and lock files must be owner-only mode `0600`.
- Symlinks, hardlinks, unsafe owners, unsafe modes, and oversized images are rejected.
- Updates use a verified temporary image and atomic replacement.
- Deletion clears record fields and rebuilds the image, but storage snapshots and media remanence remain outside the runtime's control.
- Values are not encrypted by the library.

Use operating-system or volume encryption when memory confidentiality at rest is required. Do not place the ledger on shared, synchronized, network, or untrusted removable storage.

## Hermes-specific considerations

`pre_llm_call` returns context that Hermes may copy into its transcript. That context can contain persona guidance and recalled memory atoms. The profile therefore requires explicit acknowledgement before a memory state path can be enabled.

`post_llm_call` reads assistant text only to validate payload shape and measure response length; the adapter does not pass the text into `TurnOutcome` or runtime state. The adapter reports a conservative unknown host status rather than treating delivery as proof that persistence was safe.

## Native 0.3.0 memory boundary

The [native bridge](HERMES_INSTALL.md) keeps bounded volatile proposals, one-time
confirmation challenges, admission fingerprints and last-use receipts. Pending
requests expire after five minutes or process/session finalization. Persistent
state is one profile-local ledger, partitioned by hashed transport owner/chat.
Hashing scopes is not anonymization. No state is seeded from the host.

Native no-save prevents new preference captures; recording a privacy-tightening
control may itself write an opaque replay fence/session flag. No-recall separately
blocks injection and does not block owner inspection. Native session flags survive
restart until an explicit confirmed resume; this differs from core-only in-memory
no-save. No control can retract context already sent to Hermes or a provider.

All expanding controls and memory changes require a fresh single-use challenge
because native command metadata lacks forwarded provenance. The token binds the
exact request, session and policy and is not accepted from a model hook. Ordinary
admitted messages can propose a write or tighten privacy, never grant consent.
The host, its admission/auth checks and its real command dispatcher remain trusted;
a compromised host or OS account can bypass this boundary.

Forget removes the selected lineage and its evidence text; opaque event hashes
and sequence/policy fences remain to prevent resurrection. The limited native
inspection view refuses to choose targets beyond its bound; use the paged API.

## Logging and telemetry

Core has no built-in network telemetry. CLI commands emit exactly one JSON object and use fixed error labels that do not echo invalid input or filesystem paths.

Integrators should avoid logging:

- `TurnInput.text`;
- rendered context;
- persona or creative-pack contents;
- memory values or evidence source identifiers;
- complete hook payloads;
- database images and backups.

Safe operational metrics are aggregate counts, fixed error codes, context sizes, duration buckets, and version identifiers, provided they cannot be joined back to individual conversations.

## Recommended deployment checklist

- Keep memory disabled until a retention and deletion policy exists.
- Use synthetic data for tests and vulnerability reports.
- Run the agent host under a dedicated operating-system account.
- Keep profile and state roots outside shared or group-writable locations.
- Configure host and model-provider retention independently.
- Redact context and hook payloads from logs and exception trackers.
- Call `finalize()` for every completed or abandoned session.
- Test no-save end to end, including host transcript behavior.
- Document who can read backups and how they are deleted.
