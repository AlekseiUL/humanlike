# Threat Model

This threat model covers Humanlike beta `0.1.x`: the provider-neutral core, local profiles and creative packs, optional SQLite memory, offline conformance runner, and reference Hermes adapter.

## Security goals

1. Do not turn raw conversation text into runtime-owned durable state without explicit consent and validated host records.
2. Keep context and internal metadata bounded.
3. Preserve mandatory AI-truth and no-persistence guidance under context pressure.
4. Isolate profiles, sessions, and memory records.
5. Reject path traversal, unsafe links, unsafe file ownership/modes, and malformed local data at hardened boundaries.
6. Fail neutral at the Hermes hook boundary without leaking rejected payloads or exception details.
7. Run core behavior and conformance checks without model or network access.

## Assets

- current-turn text and host identifiers;
- persona and creative-pack contents;
- rendered behavioral context;
- memory values, evidence references, and SQLite images;
- receipts and fingerprints;
- plugin source and configuration;
- host availability and hook lifecycle integrity.

## Trust boundaries

```text
untrusted user text
        |
        v
trusted host integration ---- untrusted model/tool outputs
        |
        v
validated public contracts
        |
        v
Humanlike runtime ---- rooted local profile/pack ---- optional local memory
        |
        v
bounded context and metadata returned to host
```

The operating-system account, Python interpreter, installed plugin source, and host adapter code are trusted. User messages, recalled values, pack data, model output, hook payloads, fixture files, and filesystem entries encountered during secure opening are treated as potentially malformed.

## Threats and controls

| Threat | Primary controls | Residual risk |
| --- | --- | --- |
| Oversized or malformed turn/payload | Type checks, character limits, identifier bounds, active session/turn limits, fail-neutral hooks | Host can consume resources before the hook is invoked |
| Prompt injection through user text | Deterministic routing; user text is not copied verbatim into normal context fragments; hard truth/privacy tails | A downstream model may still follow malicious user instructions |
| Malicious recalled memory or creative data | Explicit untrusted delimiters, bounded records, validated pack manifests and rights fields | Delimiters are guidance, not a model-enforced security boundary |
| Raw transcript retention | Metadata-only receipts/snapshots/outcomes; no automatic Hermes memory derivation | Host, provider, logs, and backups may retain text and injected context |
| No-save bypass | Strictest scope wins, session propagation, hard policy fragment, write preconditions | External host storage is outside runtime control |
| Cross-profile or cross-session memory access | Profile/session checks on recall and write; rooted state path | A compromised host can instantiate the runtime with another trusted profile |
| Path traversal or symlink escape | Relative rooted paths, component checks, no-follow opens, symlink rejection | Trusted process owner can replace the installation itself |
| Hardlink or permission abuse | Owner checks, exact private modes, link-count checks, descriptor/inode revalidation | Privileged local attackers remain out of scope |
| Concurrent memory corruption | Process/thread locks, bounded snapshots, transactions, quick checks, atomic replacement | Unsupported filesystems may violate locking or replacement assumptions |
| Memory disclosure at rest | Owner-only files and deployment guidance | Database values are plaintext; volume encryption is external |
| Memory remanence after deletion | Field clearing, SQLite rebuild, temporary-image scrub | Filesystem snapshots, SSD behavior, backups, and forensic recovery are external |
| Host lifecycle mismatch | Turn/session matching, interrupted-turn retirement, idempotent receipts, finalization cleanup | A host that never finalizes can retain bounded metadata until eviction/process exit |
| False identity claim in output | Mandatory truth context and one narrow exact-match correction | Paraphrases and other unsafe content are not comprehensively filtered |
| Corrupt or hostile eval suite | Rooted `.jsonl` loading, strict JSON, schema/size/count bounds, temporary state | Passing fixtures measure declared checks, not general model quality |
| Dependency or artifact substitution | No third-party runtime dependencies, locked CI tooling, installed-wheel smoke, and reproducible source archives | Python, build backend, dev tools, repository access, and release channel remain supply-chain risks |

## Abuse cases

### A user requests no-save and then requests saving

Session-level no-save remains the strictest scope until `finalize()`. A later save phrase cannot silently relax it. The host must start a new finalized session for a new consent decision.

### A host passes message text as a memory record

The core validates record shape and write conditions, but it cannot determine whether a scalar value is an over-broad transcript excerpt. The host is trusted to apply data minimization before supplying records. The reference Hermes adapter avoids this risk by supplying no records.

### A profile points outside its directory

Absolute paths, `..` components, symlinks, unsafe parents, unexpected ownership, and group/other-writable profile files are rejected. Loading fails before runtime construction.

### A component raises during preparation

Optional context from memory, creative planning, stance, discourse, or persona is omitted and a bounded error code is retained. Routing has a conservative strict-truth fallback. Hermes returns no mutation when the boundary cannot produce a valid bounded context.

### An attacker gains read access to the process account

They may read profiles, in-memory context, and plaintext memory state. Preventing compromise of the trusted operating-system account is a deployment responsibility.

## Out of scope

- security of the agent host, model provider, tool servers, browser, shell, or network;
- model alignment, jailbreak resistance, factual accuracy, or general content moderation;
- malware running as the same operating-system user or with elevated privileges;
- confidentiality after context or messages are copied into host/provider storage;
- physical attacks, forensic recovery, filesystem snapshots, and backup deletion;
- denial of service before input reaches the runtime;
- cryptographic signing of plugin releases or creative packs;
- native Windows ACL ownership enforcement and a native Windows persistent-memory backend;
- claims that deterministic behavioral guidance makes a model human, conscious, or emotionally safe.

## Residual-risk decisions

- Availability is favored at the Hermes boundary: malformed inputs fail neutral rather than crashing the host.
- Memory is disabled in the example profile because transcript and retention policy belong to the deployment.
- Local memory is plaintext because key management and encryption at rest are deployment concerns.
- Output transformation remains deliberately narrow to avoid broad, unreviewable rewriting.
- Fingerprints support private correlation, not anonymity or long-term identity.

## Verification checklist

- Run all unit tests and lint checks on the release commit.
- Run `humanlike doctor` against the exact deployed profile.
- Run the bundled offline conformance suite.
- Verify repository, profile, state directory, database, and lock ownership/modes.
- Exercise symlink, traversal, malformed payload, interrupted turn, and session-finalize cases.
- Confirm memory remains absent when disabled and during no-save sessions.
- Confirm the host's transcript and provider-retention behavior independently.
- Verify that logs and crash reports do not include turn text, rendered context, or memory values.
- Re-run these checks after host, Python, filesystem, or Hermes upgrades.
