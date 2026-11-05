# Stability contracts — 0.4.0

## Neutral routing and advisory guidance

`Mode.UNKNOWN` / `SocialMove.NEUTRAL` mean insufficient lexical evidence, not a
request to ask a clarification question. For example, `Build a CSV parser with
validation` follows the current request with no assumed social intent.
`RouteDecision.response_budget` is `None` for unknown, serialized as JSON `null`.
Known modes still have advisory budgets: these are not provider token limits.
Positive full greetings/acknowledgments remain social; a greeting plus an unknown
task does not become social merely because it contains `hello`.

The rendered route block is `ADVISORY_ROUTE_GUIDANCE_JSON`, schema
`humanlike-route-guidance/v2`; discourse and tone anchors are also advisory.
Current explicit instructions outrank communication defaults and remembered
preferences. A detailed request does not permanently replace a stored short
preference. No hidden reasoning transcript is requested.

Consent, authorization, owner/chat isolation, replay checks, no-save and context
size bounds are enforced in code. Mandatory AI-truth/privacy fragments remain;
their presence does not prove model obedience or control host/provider archives.
The native bridge returns at most 9,999 context characters. Unknown classification
cannot grant write authority. An admitted mixed request such as `Build a CSV
parser. Do not save this session.` applies the session no-save fence and leaves
the ordinary task to the host. Quoted control text is not a command.

## Preference changes

1. With consent, store `Usually keep replies short` using native confirmation.
2. `Usually give detailed replies` now returns `[conflict_choice]`, not `[stored]`.
   Existing recall remains short. Nothing chooses last-write-wins.
3. Choose `/humanlike correct that: usually give detailed replies` to replace all
   active values in the exact general scope. Alternatively choose
   `/humanlike explain learning topics in detail` for learning only.
4. Read the new challenge and send its exact one-use confirmation within five
   minutes. The result identifies the stored domain/value and retained history.
5. Inspect with `/humanlike what do you remember`; paginate with
   `/humanlike next memory page`. Old values remain visible but inactive.

The short learning form is `Keep learning replies short` /
`Объясняй учебные темы кратко`. Explicit correction also resolves contradictions
written by earlier versions or the lower-level API. It does not erase provenance,
select one arbitrary conflict, or cross domain/condition/owner/chat boundaries.
The SDK accepts `HumanEvent.target_ids` only for correction of the entire exact
active group; existing single `target_id` APIs remain available. The selection and
policy are rechecked transactionally. Pending proposals/challenges do not survive
restart. Cancellation, revocation, session changes, timeout or concurrent writes
invalidate old approvals. Replaying an approval cannot save again.

The existing 256-version group bound is unchanged: a group with 255 versions can
add one correction; a full group returns `[group_full]`. Inspect and explicitly
forget the selected lineage only if you intend to erase it. No automatic pruning.

## Observable states, not model claims

- `[pending]` and `[confirmation_required]`: proposal, not a durable write.
- `[conflict_choice]`: no write; choose correction or a separate scope.
- `[stored]`: the durable commit returned successfully. Errors never claim this.
- Recall returns verified stored facts, abstaining on unresolved contradictions.
- `prepared:not_provider_receipt`: reference data prepared for a hook, not proof
  that the provider received it or the model used it. The legacy `[used]` why-use
  code now explicitly describes preparation, not delivery.
- `not_prepared`: missing/stale/mismatched ticket, disabled recall, unavailable
  memory, invalid payload, duplicate turn, bounds or prepare failure.
- `not_added`: the bridge could not return native context because the adapter was
  unavailable or the combined context exceeded the bound.

`/humanlike status` exposes scoped memory-context state and adapter-wide safe
status. `automatic_context=True` describes surface capability, not a receipt.
The legacy directory adapter exposes `/humanlike-status` if command registration
is supported; invalid configuration reports `config_profile_not_loaded` rather
than silently pretending a profile loaded. Unsupported native hosts report
`[unavailable]` when a command interface exists; the Python adapter's `status()`
also works without commands. These are bounded in-memory latest states, not a
per-turn log or proactive messages. No text, identifiers, paths or exception
messages are included in diagnostics. Ordinary memory-off conversation remains
available; storage failure does not confirm a save.

There is no `submitted`, provider-received or model-used receipt: the supported
hooks do not establish those facts. Tests exercise synthetic failures and real
Hermes command/hook dispatch, not a live bot transport.

## Compatibility and rollback

Existing `humanlike-hermes/v1` configs, consent records and SQLite `user_version=1`
remain readable; no schema migration or user-database operation is performed.
The bounded `MemoryRecord.supersedes` capacity grows from 32 to 256 so one group
correction remains one atomic version. Older readers can reject records with more
than 32 targets: **do not downgrade a populated ledger to an older reader**.
Disable the plugin for rollback, retain the current ledger/deletion/replay fences,
and use a reviewed code revert retaining the compatible reader if necessary.
Never restore pre-forget snapshots. The new route enum/null budget also requires
consumers to handle unknown explicitly; this is a minor beta API increment.

Model-quality experiment: **NOT_RUN** for 0.4.0; improvement **NOT_PROVEN**.
Live Telegram: **NOT_RUN**. Any new model comparison or live pilot requires a
separate approved budget/isolated transport setup. No live profile activation,
new provider, dependency, tag or PyPI publication is part of this increment.

## Русский

Неизвестный запрос получает `unknown/neutral`, без навязанного короткого бюджета
и без требования уточнять уже понятную задачу. Маршрут и стиль — рекомендации;
текущая просьба важнее старого предпочтения. Права записи, согласие, изоляция,
no-save и размер контекста проверяются кодом независимо от уверенности роутера.

После «обычно отвечай кратко» просьба «обычно отвечай подробно» даёт
`[conflict_choice]`: новая запись не сделана. Выберите замену через
`/humanlike исправь это: обычно отвечай подробно` либо отдельную учебную область:
`/humanlike объясняй учебные темы подробно`. Затем отправьте новое одноразовое
подтверждение. Исправление заменяет все активные значения только выбранной области;
старые версии и источники остаются в просмотре. «Сейчас объясни подробно» не меняет
постоянную память. При 256 версиях новая запись запрещена, автоматического удаления нет.

`/humanlike статус` показывает, был ли контекст подготовлен и почему он отсутствует.
Подготовка не означает отправку провайдеру или учёт моделью. Ошибка диска не становится
успешным сохранением. Диагностика не содержит переписки, путей и текста исключений.
При откате отключайте плагин, сохраняя актуальную базу и защиту от повторов/восстановления
удалённого. Старый reader может не прочитать групповое исправление более 32 значений;
не открывайте такую базу старой версией. Улучшение качества модели не доказано,
живой Telegram не проверялся; для обоих нужны отдельные разрешённые испытания.
