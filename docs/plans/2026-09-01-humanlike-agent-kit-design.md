# Humanlike — Design Document

**Дата:** 2026-09-01  
**Инициатор:** владелец продукта
**Статус:** Approved — пользователь явно попросил сформировать, протестировать и создать закрытый репозиторий

## Проблема

Современные агентские фреймворки хорошо вызывают инструменты и всё лучше хранят память, но их разговорное поведение остаётся нестабильным: они неверно выбирают социальный ход, отвечают непропорционально, повторяют шаблоны, теряют характер, соглашаются под давлением и смешивают предположение с фактом. Проверенный внутренний прототип уже детерминированно классифицирует ход, ограничивает контекст, подключает творческий отбор и уважает `no-save`; сейчас эта технология связана с приватным профилем и не является переносимым продуктом.

## Решение

Создать **Humanlike** — provider- и host-neutral Python runtime, который готовит компактный поведенческий план для каждого хода, но не заменяет LLM, agent host или memory database. Первая эталонная интеграция — Hermes Humanlike.

Продукт отвечает за семь вещей:

1. определить предметный режим и ожидаемый социальный ход;
2. задать соразмерный бюджет и форму ответа;
3. выбрать только разрешённый и релевантный контекст;
4. включить divergent/convergent creative plan только по необходимости;
5. обеспечить truth, privacy, no-save и calibrated disagreement;
6. отслеживать речевые повторы и persona drift;
7. выдавать приватный receipt без raw-транскрипта.

## Рассмотренные подходы

| Подход | Плюсы | Минусы | Решение |
|---|---|---|---|
| Скопировать весь runtime и данные внутреннего прототипа | Максимальная близость к текущему агенту | Приватные пути, персональный профиль, закрытые корпуса, права и сильная связь с исходной системой | Отклонён |
| Построить полный agent/companion OS | Можно контролировать UI, voice, tools и память | Конкурирует с Hermes/OpenClaw/Letta; огромный scope | Отклонён |
| Переносимый behavioral runtime + reference agent | Ясный wedge, простая интеграция, измеримость, отсутствие vendor lock-in | Требует строгих adapter contracts и conformance suite | Выбран |

## Архитектура

### Core API

```python
runtime = HumanlikeRuntime(config, memory=memory_port, packs=[taste_pack])
plan = runtime.prepare(TurnInput(...))
context = plan.render_context()
receipt = runtime.observe(TurnOutcome(...))
runtime.finalize(SessionRef(...))
```

Core не вызывает модель и сеть. Host получает `TurnPlan`, добавляет bounded context к системному prompt, сам вызывает модель и сообщает минимальный outcome обратно.

### Компоненты

- `models.py` — immutable contracts: turn, route, context fragment, receipt.
- `router.py` — двухосевой RU/EN router: cognitive mode + social move.
- `persona.py` — compact identity spine, SOUL/PERSONA-compatible import, anchor hash.
- `memory.py` — typed SQLite ledger с provenance, scope, validity и supersession.
- `creative.py` — пять mechanism-shifting strategies, rubric/anti-pattern retrieval, candidate scoring.
- `discourse.py` — metadata-only ledger речевых тактик и repetition guard.
- `drift.py` — probe scoring и conditional re-anchor.
- `runtime.py` — оркестрация, context budgets, fail-open и receipts.
- `adapters/hermes.py` — тонкий перевод Hermes hooks в core API.
- корневые `plugin.yaml` и `__init__.py` — installable Hermes shim; Hermes копирует выбранный plugin-каталог, поэтому shim находится в корне репозитория и сохраняет доступ к `src/`.
- `evals.py` — offline conformance runner; live judges остаются optional.

### Поток данных

```text
User turn
  -> privacy controls
  -> mode + social move
  -> persona/drift check
  -> scoped memory recall
  -> creative/discourse/stance policies
  -> bounded TurnPlan
  -> host LLM
  -> output gate
  -> metadata-only receipt
  -> optional validated memory update
```

Сквозные ограничения: `Truth · Consent · Drift Control`.

## Данные и приватность

- По умолчанию не сохраняются raw user/assistant messages.
- `no-save` запрещает все durable writes до завершения хода.
- Память хранится только как typed record с evidence reference, confidence и scope.
- Гипотезы о пользователе не становятся facts без явного подтверждения.
- Творческие private packs остаются локальными и gitignored; в репозиторий входит только обезличенный foundation pack.
- Закрытые корпуса, персональная USER/MEMORY, абсолютные пути и state DB не копируются.
- Receipt содержит routing metadata, размеры контекста и rule IDs, но не chain-of-thought.

## Обработка ошибок

- Ошибка pack/memory/drift компонента: fail-open без дополнительного контекста, с безопасным error code в receipt.
- Повреждённый config: `doctor` возвращает non-zero до запуска host-интеграции.
- SQLite locked/corrupt: read/write отклоняется, исходное сообщение не логируется.
- Превышение budget: фрагменты сортируются по hard priority и обрезаются; truth/privacy tail нельзя удалить.
- Неподдерживаемый Hermes payload: hook возвращает нейтральный результат и не ломает host.
- Output gate исправляет только точное полное утверждение о биологической человечности; остальные policy-классы остаются guidance для модели и ответственностью host.

## Тестирование

1. Unit: router, budget, no-save, memory validity/supersession, creative selection, discourse repetition, drift.
2. Contract: immutable models, adapter payloads, schemas.
3. Integration: end-to-end `prepare -> render -> observe -> finalize` на temp SQLite.
4. Conformance: RU/EN сценарии social, task, support, repair, creative, ontology, pressure, privacy.
5. Security/privacy: secret-shaped input, raw-transcript absence, path traversal, file permissions.
6. Packaging: build wheel/sdist, install in isolated venv, CLI smoke.
7. Performance: deterministic prepare p95 < 10 ms на локальном corpus.

## Критерии готовности v0.1

- Core работает без network/LLM/runtime dependencies.
- Hermes adapter проходит fake-host integration tests.
- Не менее 60 детерминированных тестов и 40 conformance fixtures.
- `no-save` создаёт ноль durable writes.
- Context packet не превышает configured hard limit.
- Privacy gate и secret scan проходят.
- Wheel/sdist собираются и устанавливаются.
- README позволяет получить первый route/context менее чем за 10 минут.
- GitHub repository подтверждён как private после push.

## Не входит в v0.1

- собственный vector DB;
- avatar, voice и real-time turn taking;
- background autonomous mind;
- скрытые affinity/soulmate scores;
- fine-tuning;
- утверждения о сознании или человеческой природе;
- автоматическая загрузка приватного корпуса исходного агента.

## Неблокирующие решения

- Историческое решение для первой закрытой версии: all rights reserved. Начиная с `0.1.1`, репозиторий и foundation pack распространяются по MIT.
- Основной формат config: TOML/JSON на стандартной библиотеке; PERSONA.md и Character Card adapters развивать совместимо, но без объявления нового стандарта.
- Python: 3.11+, без runtime dependencies; текущая локальная проверка также на Python 3.14.
