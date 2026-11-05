# Changelog

All notable changes to Humanlike are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The `0.1.x` beta line does not yet promise API stability.

## [Unreleased]

## [0.4.0] - 2026-11-05

### Changed / Изменено

- Explicit unknown/neutral fallback with nullable advisory response budget; positive
  social cues retained. Route guidance is versioned `humanlike-route-guidance/v2`,
  subordinate to current requests, separate from enforced privacy/authority/bounds.
- Native conflict choice instead of silently accumulating contradictory preferences;
  group correction uses exact scoped supersession history and fresh confirmation.
  Existing 256-version cap remains; supersession capacity expands to 256. No SQLite
  schema migration; older readers may reject large corrections, so rollback must
  retain a compatible reader and current deletion/replay fences.
- Bounded safe adapter/native status for unavailable configuration, memory and
  missing context; prepared is not submitted, provider receipt or model-used proof.
- Неизвестные задачи больше не считаются социальными по умолчанию. Стиль и длина —
  рекомендации, текущая просьба важнее; права записи и приватность проверяются кодом.
- Конфликт предлагает замену области или отдельное предпочтение. Исправление
  сохраняет историю; нужен новый одноразовый ответ. No-save не зависит от маршрута.
- Диагностика не раскрывает текст, пути и исключения. Ошибка не объявляется записью.

### Verification limits / Границы проверки

Offline regressions, synthetic native dispatch and non-editable package checks;
no new model experiment or live transport. Model-quality improvement **NOT_PROVEN**;
live Telegram and new A/B **NOT_RUN**. No live activation, tag or PyPI publication.
[Details / Подробности](docs/STABILITY.md).


## [0.3.1] - 2026-11-05

### Fixed — English

- Second-alternative lookup preserves multiline bodies and trailing conditions;
  unsupported/duplicate headings and over-budget blocks clarify without stale fallback.
- Native memory inspection pages five versions at a time. Full-lineage management
  no longer stops at 50 records; page state expires on mutation, timeout or restart.
  Active markers include later replacements; scoped forget includes contradictions.
- Capture checks the full expected policy at reservation, including concurrent writes.
- Small optional-politeness and explicit-preference RU/EN forms; unsupported explicit
  memory requests clarify without saving. No model extraction or new dependencies.

### Исправлено — Русский

- Второй вариант извлекается целиком, с многострочным текстом и условиями. Неясные,
  повторные заголовки и превышение бюджета требуют уточнения, без подстановки старого текста.
- Память просматривается по пять версий; лимит 50 записей больше не блокирует
  управление. Изменение памяти, тайм-аут или перезапуск сбрасывают просмотр.
  Активность учитывает поздние исправления; забывание области удаляет и противоречия.
- Перед записью проверяется вся ожидаемая политика, включая параллельные записи.
- Добавлены несколько RU/EN-перефразировок и необязательное «пожалуйста».
  Неподдерживаемый явный запрос памяти требует уточнения, а не сохраняется.

### Limits / Ограничения

- Existing 256-version limit per key/domain/condition remains; inspect and explicitly
  forget that scope before starting a fresh lineage. No schema migration.
- Лимит 256 версий на ключ/область/условие сохранён; после просмотра можно явно забыть
  эту область и начать новую цепочку. Схема хранилища не меняется.
- Real Hermes synthetic dispatch is not live Telegram delivery: **NOT_RUN** for the
  live pilot. No new model A/B; the previous tie is unchanged. No tag or PyPI release.

## [0.3.0] - 2026-11-05

### Added — English

- Callback-free native Hermes bridge: `/humanlike`, transport-scoped identity,
  admitted-message proposals, explicit consent and fresh single-use confirmations.
- Closed RU/EN reply-length vocabulary; inspect/source/why-use/correct/forget/pause
  controls, durable session no-save/no-recall and replay/out-of-order fences.
- Bounded recent-history continuation, numbered alternatives, last correction and
  topic references; current requests outrank memory, no archive crawling.
- `humanlike export-plugin --output` exports only runtime files into a new directory,
  avoiding modifications to Hermes' managed Python environment.
- Real native-interface synthetic smoke, normal-install/export checks and a 12-case
  blinded model comparison. Both conditions scored 120/120: no quality gain claimed.

### Boundaries — English

- Automatic context path: Telegram human DM without a thread; native CLI has
  session-local controls only. New sessions need `/humanlike status` binding.
- Memory remains off until consent, POSIX-only and unencrypted. Only documented
  reply-length phrases are extracted; no extra model/provider or cloud service.
- Static slash text cannot authorize a write: forwarded provenance is unavailable,
  so changes require a five-minute, single-use challenge. Forget does not erase
  transcripts/backups/provider copies. No live gateway activation was performed.

### Добавлено — Русский

- Подключение к Hermes без Python-callbacks: `/humanlike`, привязка к владельцу/чату,
  предложения из обычных сообщений, согласие и одноразовое подтверждение изменений.
- Ограниченный RU/EN-словарь предпочтений длины ответа; просмотр источников,
  объяснение использования, исправление, забывание, пауза и no-save/no-recall.
- Продолжение по недавней истории, второй вариант, последняя поправка и тема без
  технических привязок. Новый запрос важнее памяти; архивы не сканируются.
- Экспорт только рабочих файлов через `humanlike export-plugin --output` в новый
  каталог, без изменения Python-среды Hermes.
- Native smoke, проверка обычной установки и слепое сравнение на 12 диалогах:
  по 120/120 у обоих вариантов, улучшение качества не доказано.

### Ограничения — Русский

- Автоматический контекст — в личном Telegram-чате без темы; CLI даёт только
  команды. Новая сессия привязывается через `/humanlike статус`.
- Память выключена до согласия, POSIX-only и без шифрования. Извлекаются только
  описанные предпочтения длины ответа; скрытой модели или облачного сервиса нет.
- Статическая slash-команда не разрешает запись: нужно одноразовое подтверждение.
  Забывание не стирает переписку, копии провайдера или бэкапы. Живой gateway не включался.

## [0.2.0] - 2026-11-05

### Added — English

- Opt-in `PersonalMemory` over the existing SQLite ledger: explicitly stated
  preferences, goals and interests, source evidence, later recall and owner consent
  checked through host authorization.
- Separate confirms/supersedes/corrects/contradicts relations with domain and
  condition scopes; stale-event and replay guards preserve newer knowledge.
- Inspect/correct/forget/disable controls. Forgetting erases the selected fact's
  version history; no-save is checked before extraction and persistence. Durable
  policy epochs reject late saves after forgetting or disabling, including after
  reopening the ledger.
- Bounded read-only `ConversationContext` for exact-anchor continuation requests,
  with artifact references and host-observed past tool outcomes. Unrelated requests,
  quoted cues and weak matches do not reactivate old tasks or rewrite history.
- Explicit `AuthorizedHost` and `HermesAdapter.prepare_authorized(...)` integration,
  a runnable synthetic lifecycle example and an EN/RU integration guide.
- Regression coverage for authorization, no-save, replay, concurrent revocation,
  scope isolation, old/new ledger compatibility and installed-package behavior.

### Boundaries — English

- Existing APIs, stock plugin defaults and zero mandatory runtime dependencies remain.
  Personal capture is off by default; legacy TOML settings or untrusted hook payload
  flags do not enable it. Trusted host integration and owner consent are required.
- Durable memory remains POSIX-only and unencrypted. Explicit capture uses English
  command words with Unicode values, not free-form extraction from ordinary speech.
  Forgetting does not delete host/provider transcripts or backups.
- Model A/B: **NOT_RUN**. Offline functional tests do not establish more natural or
  higher-quality LLM answers. No mandatory cloud service or model is added.

### Добавлено — Русский

- Опциональная `PersonalMemory` поверх существующего SQLite-хранилища: явно указанные
  предпочтения, цели и интересы, источники, последующее использование записей и
  согласие владельца с проверкой прав на стороне основной системы.
- Раздельные отношения confirms/supersedes/corrects/contradicts с предметной областью
  и условием применения; защита от устаревших и повторных событий сохраняет более
  свежие сведения.
- Просмотр, исправление, забывание и отключение. Забывание удаляет историю версий
  выбранного факта; запрет сохранения проверяется до извлечения и перед записью.
  Сохранённая версия политики отклоняет поздние результаты после забывания или
  отключения, в том числе после повторного открытия хранилища.
- Ограниченная `ConversationContext` для запросов на продолжение с точной привязкой
  к прежнему материалу и реальным результатам инструментов. Несвязанные запросы,
  цитаты и слабые совпадения не возобновляют старую задачу и не переписывают историю.
- Явная интеграция через `AuthorizedHost` и `HermesAdapter.prepare_authorized(...)`,
  исполняемый пример на вымышленных данных и инструкция EN/RU.
- Проверки регрессий: права доступа, запрет записи, повторы, отзыв разрешения во время
  обработки, изоляция областей, совместимость старого и нового хранилища и работа
  установленного пакета.

### Ограничения — Русский

- Прежние API, настройки обычного плагина и отсутствие обязательных runtime-зависимостей
  сохранены. Персональная запись по умолчанию выключена: прежних TOML-настроек или
  флагов в недоверенном сообщении недостаточно. Нужны доверенная интеграция и согласие владельца.
- Постоянная память остаётся POSIX-only и не шифруется. Запись использует английские
  командные слова со значениями Unicode, а не свободное извлечение из обычной речи.
  Забывание не удаляет переписку и резервные копии основной системы или провайдера.
- Модельное A/B: **NOT_RUN**. Офлайн-тесты функций не доказывают, что ответы LLM стали
  естественнее или качественнее. Обязательный облачный сервис или модель не добавлены.

## [0.1.2] - 2026-09-04

### Added

- Added native Windows support for the core runtime, CLI, read-only profile and foundation-pack loaders, and the memory-off Hermes plugin.
- Added a real `windows-latest` wheel-install, CLI, eval, and doctor gate to CI.
- Added bilingual PowerShell installation instructions and the supplied Humanlike project cover.
- Added a bilingual Hermes wheel-entry-point installation path with runtime validation, commit pinning, rollback, and removal.
- Added a memory-off starter runtime that Hermes discovers from the installed Python package.

### Changed

- Prepared the repository documentation for public beta availability under the MIT License.
- Shortened the public product and repository name to **Humanlike** while keeping the `humanlike-agent-kit` package and plugin identifiers stable for compatibility.

### Security

- Windows path loaders fail closed on traversal, symlinks, junctions, and other reparse points. The optional SQLite memory ledger remains POSIX-only rather than weakening its locking and ownership contract.

### Fixed

- Made tests and documented `humanlike doctor` quickstarts reliable under `umask 0002` without weakening the hardened profile-permission checks.

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
