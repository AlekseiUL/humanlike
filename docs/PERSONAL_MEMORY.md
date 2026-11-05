# Consented memory and conversation references — developer API

This is the lower-level API introduced in 0.2.0. For callback-free 0.3.1 setup,
use [Native Hermes installation and controls](HERMES_INSTALL.md). The old API
remains available; its English grammar is supplemented by the closed RU/EN
reply-length vocabulary. / Для готового подключения 0.3.1 используйте
[инструкцию EN/RU](HERMES_INSTALL.md); ниже описан прежний API разработчика.

[English](#english) · [Русский](#русский)

## English

### What is available

`PersonalMemory` adds an **explicit, opt-in capture pipeline** to the existing
`SQLiteMemoryLedger`. It does not create a second memory database. An authenticated
human event is parsed into one bounded candidate, checked by code, committed with
source evidence, and available on later turns. `ConversationContext` separately
retrieves bounded references from history explicitly supplied by the host.

Defaults are unchanged: the installed Hermes plugin does not start capturing
personal information. This section describes the programmatic host integration, not the 0.3.1 native
Hermes hook, slash command, TOML flag, or automatic archive reader. The existing
`memory_enabled` option provisions the legacy ledger; it is **not owner consent**
for this pipeline. No cloud memory service, model, credential or network dependency
is installed. Durable storage retains the existing POSIX-only restriction.

### Runnable quickstart

After installing this repository with `python -m pip install .`, run:

```bash
python examples/consented_memory.py
```

The example exercises a real `HumanlikeRuntime` and `HermesAdapter`, writes only a
temporary synthetic ledger, reopens it, corrects and forgets a preference, blocks
replay and no-save, and recalls a synthetic artifact with a **failed** tool receipt.
It asserts results before printing JSON. On Windows it exercises read-only
conversation recall and reports `UNSUPPORTED_PLATFORM` for durable memory.

### Host integration and consent

Construct `PersonalMemory(ledger, owner_id=..., profile_id=..., session_id=...,
authorize=..., resolve=...)` inside trusted host code. Both callbacks are required:

- `authorize(owner_id, profile_id, session_id, operation)` must return the boolean
  `True` only after checking the signed-in owner's rights and the requested action.
  It is called for enable, disable, capture, inspect, recall and forget. Exceptions
  deny access. The example's always-true callback is a synthetic fixture, not an ACL.
- `resolve(event_id)` must resolve an authenticated, immutable `HumanEvent` from
  transport-owned metadata. Never construct it by unpacking an untrusted message
  dictionary, a tool call or a model response. `role=user` and strings claiming
  ownership are insufficient. Mark forwarded/quoted/fictional assertions with
  `asserted_by_owner=False`; internal/system/tool/heartbeat events are not human
  events. The library cannot authenticate a host that lies about these facts.
- `session_id` is a required choice. A string isolates a conversation. Passing
  `None` **explicitly** opts into profile-wide memory for that owner; all sessions
  sharing it must use one monotonic sequence allocator. There is no implicit
  cross-session promotion or cross-owner recall.
- Use stable, opaque event IDs, canonical domain/condition labels, UTC-aware source
  times and increasing positive 64-bit sequences. Reuse the same ID for retries.
  Higher sequence with an older source timestamp cannot replace newer knowledge.
  Concurrent dispatch is conservative: a later reservation makes an earlier
  unfinished capture stale. Future-dated events are denied.

Expose these methods through authenticated UI controls, not model permissions:

| Owner action | Public API | Effect |
|---|---|---|
| Enable with consent | `memory.enable()` | Persists consent; invalidates pending work |
| Inspect | `memory.inspect(after=0, limit=50)` | Versions, sources, scopes and relations; page by last `sequence` |
| Correct | `memory.correct(event_id)` | Requires a fresh explicit correction event and target ID |
| Forget | `memory.forget(record_id)` | Erases the entire key/domain/condition lineage, including confirmations and old versions |
| Native snapshot page (0.3.1) | `memory.inspect_page(after=0, limit=5)` | Tuple: facts, globally active record IDs, has-more flag, snapshot policy |
| Native scoped targets (0.3.1) | `memory.management_targets("reply_length", domain="general")` | Complete bounded group; `whole_lineage=True` returns one representative per domain for forget, including conflicts |
| Disable | `memory.disable()` | Stops capture/recall and revokes pending results; inspect/forget remain available |

`capture(event_id, expected_policy=memory.policy())` (0.3.1) checks the entire
consent/epoch/watermark tuple in the reservation transaction. The existing
`expected_epoch` argument remains supported. These SDK helpers require trusted host
authorization; the native bridge supplies bindings and confirmations. They do not
make model-generated scope arguments trustworthy.

Forget also advances the policy epoch when the requested ID is absent. Scope
checks prevent deleting another owner's record. Disable is not deletion. To remove
all stored facts, page through inspection and forget each remaining lineage.

### Explicit syntax, not inferred personality

A complete command is the durable request; surrounding prose, quotes and multiline
instructions do not match. The capture grammar currently uses English command
words; values may be Unicode. A translated host UI can generate an explicit command
only after the owner confirms the exact atom. It must not silently rewrite free-form
conversation into consent.

```text
Remember my preference: tone = concise
Remember my goal: study = learn geometry
Remember my interest: hobby = astronomy
Change my preference: tone = detailed
Correct my preference: tone = neutral
Confirm my preference: tone = concise
```

Keys use ASCII letters, digits, spaces, `_` and `-`, at most 64 characters; values
are at most 256 characters. This API deliberately does not interpret temporary mood,
psychological traits, incidental remarks or one-off task instructions as durable
memory. An explicit command is an owner assertion, not independent proof that its
content is true. No semantic claim is made about arbitrary text inside a value.
Obvious transient markers and authority-override phrases/keys are conservatively
rejected as `not_explicit`. This bounded lexical guard can reject benign wording;
it is not a general multilingual prompt-injection detector. Host provenance checks
and treating recalled values as data remain mandatory.

`HumanEvent.domain` and `.condition` are host-owned exact labels (defaults:
`general`, `always`). Conditions are not evaluated as code or inferred with a model.
A teaching preference and an email preference have separate groups; neither is an
automatic fallback for the other. `recall(key, domain=..., condition=...)` is an exact
bounded lookup, not an unrestricted semantic search.

Change/correct/confirm require `HumanEvent.target_id` identifying an active atom in
the **same scope, key, domain, condition and kind**. A new assertion of an equal
value confirms it. A new incompatible assertion becomes `contradicts`, leaving both
claims inspectable; confident recall returns no hit until the conflict is resolved.
A change records `supersedes`; a correction records `corrects` and labels the old
claim erroneous. Both hide their target from current recall, but preserve provenance
until forgotten. This is not retroactive rewriting of source history. Confirmations
have their own event evidence and never multiply on replay. Resolve multiple
conflicting targets with separate explicit corrections; the library does not choose
which source to trust.

### Provider-neutral extractor boundary

Without an extractor, the deterministic parser performs extraction; there is no
mock model or simulated natural-language understanding. Optionally pass
`capture(event_id, extractor=callback)`. The callback receives an `ExtractionRequest`
containing **only the complete bounded explicit command** and its code-parsed
`candidate`, never the full conversation or authority metadata. It returns a
`Candidate(operation, kind, key, value)`; `Candidate.from_json(text)` strictly decodes
the four string fields, rejecting unknown/duplicate fields and oversized input.
Code requires the candidate to match the explicit assertion exactly. Inferred,
reworded or broadened claims fail closed. This intentionally restricted interface
is useful for validating a host's provider adapter, not for automatic free-form
personal profiling. Calling a provider is unnecessary on the deterministic path.

The host owns provider choice, deadlines, costs and data-retention consent. No
background worker or retry queue is provided. An exception returns
`extractor_failed`; a schema/value mismatch returns `invalid`. Do not silently retry
with a new ID: ask for a fresh explicit event. `no_save=True` or a host event marked
no-save blocks before dispatch. The event and authorization are rechecked before
storage; changed metadata yields `revoked`.

### Revocation, replay and storage limits

A durable event reservation and sequence watermark are committed **before** an
optional extractor. Reservations contain only an event-ID digest and sequence, not
conversation text. Policy epoch, consent and watermark are rechecked under the
ledger's exclusive snapshot lock. Forget or disable through any instance using the
same ledger invalidates old results; retry/restart cannot resurrect the same event.
Host policy changes during a callback must use these durable controls, not only
change an unrelated in-memory boolean. The host must serialize its own external ACL
changes; the library cannot make another service's ACL atomic with SQLite.

Limits: 8,192 input characters before parsing; one atom per event; 256 live historical
records per key/domain/condition group; 50 inspection records per page; the existing
64 MiB ledger-image cap. At the group limit capture returns `group_full` and existing
records remain inspectable/forgettable. Event replay fences are not automatically
pruned. Storage exhaustion/I/O failure raises an exception: it is not a successful
save. A failure after filesystem replacement can be ambiguous; inspect/reopen before
retrying and never manufacture a new event ID to bypass a reservation.

Forget scrubs plaintext atoms, source IDs/digests and scoped metadata from the
current logical ledger image. Opaque record IDs, semantic tombstones, event-ID
hashes, sequence watermarks and consent epochs remain for replay protection. Hashes
are not encryption or guaranteed anonymization. The ledger cannot erase host
archives, provider retention, previous exports, backups, filesystem snapshots or
physical media remnants. Keep host event IDs opaque and manage those stores under
the host's deletion policy. No encryption at rest is added.

### Bounded conversation context

Construct `ConversationContext(owner_id=..., profile_id=..., session_id=...,
history=callback)`. The callback supplies authorized, newest-first `HistoryItem`
objects. The library never opens a host database. Current human requests must match
an exact anchor cue, for example `Continue outline`, `Revise outline`, `Recall outline`
or `Продолжи outline`. Bare/ambiguous `Continue`, unrelated requests, quoted cues,
wrong scope and nonhuman requests return no confident recall.

Only host-labeled artifacts and real tool receipts are eligible. An assistant's
"the tool succeeded" is not a receipt. A tool item requires `outcome=success|failed|unknown`
and a stable `source_id`; the host must derive that from an actual tool result. It
describes a **past** event, not proof that the current operation succeeded. Same
anchors must name one coherent artifact/task; the host must disambiguate reused
names. No obsolete user/system instructions are reactivated.

Defaults: scan at most 32 entries, emit at most 8 complete references within 2,400
characters including JSON framing. Configurable ceilings: 128 entries and 8,000
characters. Oversized references are omitted, never truncated into misleading tool
outcomes. A host iterator failure discards partial results and returns `host_failed`.
Iteration limits cannot time out a blocking host callback; the host must enforce
its own I/O deadline. No-save does not block this read-only context use.

`AuthorizedHost` binds the memory, conversation and authenticated event resolver.
Call `HermesAdapter.prepare_authorized(event_id, host=host, memory_keys=("tone",))`
instead of `pre_llm_call` for that turn. `memory_keys` is a trusted selection of at
most eight relevant exact keys, not something copied blindly from an old task.
Domain/condition selection is explicit. Use the existing post/finalize hooks after
handling the returned `AuthorizedTurn`. Inspect `status`, `capture.status` and
`conversation_status` separately: a prepared behavior plan is not proof of a save.
Stock hook dictionaries cannot opt in with forged consent flags.

Rendered memory/history is **untrusted reference data**. Deliver it through the
host's appropriate context surface without editing canonical messages or system
prompts. Current instructions win; text in a recalled artifact never grants tool
permissions. JSON framing reduces ambiguity but is not a universal prompt-injection
filter. An overflow returns base context with `context_overflow`; integration errors
return `integration_failed`. If capture already committed before a later context
failure, its successful capture receipt remains visible.
An exception during capture itself is reported as `capture.status=storage_unknown`;
inspect the ledger before deciding whether to retry. The bridge also honors the
runtime's item/session no-save scope. After runtime finalization or host restart,
the host must continue supplying its applicable no-save policy; it must not assume
ephemeral runtime metadata survives a restart.

### Migration, rollback and evidence

The core ledger's v1 tables and existing APIs remain unchanged. Three additive tables
(`personal_policy`, `personal_events`, `personal_records`) are created only on an
explicit personal-memory mutation. Values and evidence stay in `memory_records`;
owner/profile/session use a distinct hashed namespace so ordinary profile recall
cannot accidentally include these atoms. This is isolation against accidental API
mix-ups, not protection from privileged code with direct database access.

A read of a legacy ledger does not migrate or write it. Existing core writers retain
the additive tables when serializing the image. Use `PersonalMemory` controls for
these records; direct low-level mutations bypass its policy semantics.

Before deploying, use the host's approved backup procedure and test a synthetic
copy. To roll back, disable capture, stop the new host bridge, and install the prior
reviewed version. Leave the additive tables intact. **Do not restore a pre-forget
backup** or drop replay fences: either would resurrect previously forgotten data.
No production database migration is performed by this repository's tests.

Run `pytest -q`, `ruff check .`, the privacy gate, build and the installed-wheel
example. Tests compare memory-off versus consented capture, one-off versus explicit
assertions, conflicting versus conditional preferences, quoted versus authorized
continuation, and real failed receipts versus assistant claims. These are functional
regressions, not scores of conversational naturalness. **Model blinded A/B: NOT_RUN.**
No improvement in LLM answer quality, full persona parity or free-form extraction is
claimed. The public example makes no model or provider calls.

## Русский

### Возможности и включение

Начиная с 0.2.0, `PersonalMemory` сохраняет явно указанные предпочтения, цели и
интересы в существующем `SQLiteMemoryLedger`. `ConversationContext` отдельно
возвращает ограниченные фрагменты истории, которую разрешил и передал хост.
Обязательных зависимостей, облачного сервиса памяти и сетевых вызовов нет. Запись
остаётся POSIX-only; чтение переданного контекста работает и без ledger.

По умолчанию новый захват выключен. Штатный Hermes-плагин не начинает запоминать
разговоры после обновления. `memory_enabled` создаёт прежнее хранилище, но не
заменяет согласие владельца. Для нового цикла нужен программный host API:
`PersonalMemory` с проверкой прав `authorize` и разрешением событий `resolve`,
затем явный `enable()`. Поля сообщения, `role=user` и слова «я владелец» не являются
доказательством прав. Callback должен брать происхождение события из проверенного
транспорта; цитаты, вымысел, пересылки и служебные события исключаются.

Рабочий синтетический пример после обычной установки:

```bash
python examples/consented_memory.py
```

Он использует настоящий runtime и адаптер, открывает временный ledger повторно,
исправляет и удаляет предпочтение, проверяет no-save и повтор события, восстанавливает
черновик вместе с реальным для этого примера результатом инструмента — `failed`.
Никакие личные данные или базы хоста не нужны.

### Что считается памятью

Поддерживается полный явный запрос вида `Remember my preference: tone = concise`;
также доступны `goal` и `interest`. Для изменения — `Change my ...`, исправления
ошибочной записи — `Correct my ...`, подтверждения — `Confirm my ...`.
Последние три операции требуют `target_id` активной записи той же области.
Командные слова пока английские; значения могут быть на русском. Интерфейс хоста
может перевести выбор владельца в такую команду после подтверждения, но не превращать
обычный разговор в согласие автоматически.

Разовая просьба, настроение и догадка о характере не извлекаются. Модельный callback
не обязателен: работает детерминированный парсер. Необязательный `extractor` получает
только ограниченную явную команду и возвращает `Candidate`; код проверяет точное
соответствие, а не доверяет модели права записи. Выбор провайдера, таймауты, цена и
согласие на передачу данных остаются у хоста. Свободное извлечение из обычной речи
этот релиз не заявляет.

`domain` и `condition` — явные метки хоста. Предпочтения для писем и обучения не
создают ложный конфликт. `confirms` подтверждает запись новым источником;
`supersedes` отмечает изменение; `corrects` — исправление; `contradicts` сохраняет
неразрешённое расхождение. При конфликте `recall` не выбирает значение сам.
Повтор одного события не увеличивает число подтверждений. Старые и будущие события
не могут незаметно заменить актуальную запись.

### Управление и гарантии

- `inspect(after=..., limit=...)` — просмотр версий, условий и источников, до 50 за страницу.
- В native 0.3.1 обычные команды дают страницы по пять версий; SDK для управления
  не нужен. `inspect_page` возвращает также активные ID, наличие следующей страницы
  и политику снимка; `management_targets` выбирает полную ограниченную область.
- `capture(..., expected_policy=...)` проверяет согласие, эпоху и watermark перед
  резервированием записи; старый `expected_epoch` сохранён.
- `correct(event_id)` — исправление по новому разрешённому событию.
- `forget(record_id)` — удаление всей истории данного ключа и условия, включая подтверждения.
- `disable()` — остановка записи и recall, отмена ожидающих результатов; это не удаление.
- `enable()` — новое подтверждение согласия; также отменяет старую незавершённую работу.

Сессия изолирована по умолчанию конструктора: параметр `session_id` нужно передать.
Только явное `None` выбирает общую память профиля для данного владельца. Идентификаторы
и порядок событий должны назначаться хостом, а не моделью. No-save проверяется до
extractor и перед записью. Удаление и отключение меняют сохранённую эпоху политики;
поздний результат и повтор после перезапуска отклоняются. Фоновой очереди нет.

Остаются минимальные хеши и служебные отметки против повторного сохранения. Это не
шифрование. Удаление из ledger не удаляет разговоры хоста, архивы провайдера, резервные
копии, снимки файловой системы и физические остатки на носителе. Изменение внешних
прав хост должен согласовать со своими блокировками и durable-контролями библиотеки.
Ошибка записи — исключение, не успешное сохранение; при неоднозначном сбое сначала
проверьте состояние, не подменяйте событие новым ID ради повтора.

### Контекст продолжения

Хост передаёт `HistoryItem` от новых к старым. Запрос `Продолжи outline` или
`Continue outline` должен точно назвать разрешённую опорную метку. Просто
«продолжи», цитата, слабое совпадение и новая несвязанная задача не закрепляют старое
задание. Возвращаются ссылки на материал и реальные результаты инструментов;
заявление ассистента об успехе не заменяет receipt. Старый результат не доказывает
успех текущей операции. При ошибке истории частичный результат отбрасывается.

По умолчанию просматриваются 32 записи и возвращаются до 8 полных фрагментов в
пределах 2 400 символов. История не меняется, системный prompt не переписывается,
база хоста автоматически не открывается. No-save не запрещает это чтение.

Для интеграции создайте `AuthorizedHost` и вызывайте
`HermesAdapter.prepare_authorized(event_id, host=host, memory_keys=("tone",))` вместо
обычного `pre_llm_call` этого хода. Актуальные ключи выбирает хост. Проверяйте отдельно
статус плана, захвата памяти и восстановления разговора. Переданный контекст — данные,
не новые инструкции и не разрешение выполнить инструмент. Схема JSON не является
полной защитой модели от prompt injection.

### Совместимость, откат и ограничения

Прежние API и таблицы ledger v1 сохранены. Дополнительные таблицы создаются только
при явном изменении персональной памяти; чтение старой базы ничего не мигрирует.
Перед внедрением проверьте синтетическую копию и выполните принятую у хоста процедуру
резервирования. Для отката отключите новый захват и host API, установите прежнюю
проверенную версию, оставив дополнительные таблицы. Не восстанавливайте копию до
команды «забудь» и не удаляйте защиту от повторов: это вернёт забытые данные.

Лимиты и обработка ошибок подробно указаны в английском разделе выше. Проверки
покрывают функциональное поведение, включая гонку с отключением/удалением из другого
экземпляра. **Слепое модельное A/B: NOT_RUN.** Улучшение естественности ответов,
полное соответствие персональному агенту и качество свободного LLM-извлечения не
измерялись и не заявляются.
