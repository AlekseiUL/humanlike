# Humanlike Agent Kit v0.1 — План реализации

> Для исполнения используется subagent-driven development с TDD и двухэтапным review.

**Цель:** создать проверенный provider-neutral behavioral runtime, эталонный Hermes adapter и закрытый GitHub-репозиторий.  
**Архитектура:** чистый Python core принимает typed turn, возвращает bounded plan и никогда сам не вызывает LLM. State и creative packs подключаются через узкие интерфейсы.  
**Стек:** Python 3.11+, stdlib runtime, pytest/ruff/build как dev tooling, SQLite, GitHub Actions.

---

## Батч 1 — Контракты и роутинг

### Задача 1: Package scaffold и immutable contracts

**Файлы:**

- Создать: `pyproject.toml`
- Создать: `src/humanlike_agent/__init__.py`
- Создать: `src/humanlike_agent/models.py`
- Тест: `tests/test_models.py`

**RED:** тест импортирует `TurnInput`, `TurnPlan`, `ContextFragment`, проверяет immutable dataclasses и JSON-safe `to_dict()`.

```python
def test_turn_plan_is_immutable_and_json_safe():
    plan = TurnPlan.safe_default("t1", "s1")
    assert plan.to_dict()["turn_id"] == "t1"
    with pytest.raises(FrozenInstanceError):
        plan.mode = "creative"
```

**Команда RED:** `uv run pytest tests/test_models.py -x` → import failure.  
**GREEN:** реализовать enums `Mode`, `SocialMove`, `MemoryScope` и frozen dataclasses с явными defaults.  
**Команда GREEN:** `uv run pytest tests/test_models.py -x` → PASS.

### Задача 2: Двухосевой deterministic router

**Файлы:**

- Создать: `src/humanlike_agent/router.py`
- Тест: `tests/test_router.py`
- Fixture: `tests/fixtures/router_cases.json`

**RED:** параметризованные RU/EN cases проверяют mode, social move, constraints, candidate count и budget.

```python
@pytest.mark.parametrize("text,mode,move", [
    ("Привет, бро", Mode.SOCIAL, SocialMove.CONNECT),
    ("Ты опять не понял — исправь только второй абзац", Mode.REPAIR, SocialMove.REPAIR),
    ("Сочини пять небанальных заходов", Mode.CREATIVE, SocialMove.CREATE),
    ("I am exhausted, just listen", Mode.SUPPORT, SocialMove.LISTEN),
])
def test_route_cases(text, mode, move):
    decision = route_turn(TurnInput(text=text))
    assert (decision.mode, decision.social_move) == (mode, move)
```

**GREEN:** priority-aware lexical rules, quoted-control removal, explicit no-save/save, elapsed-time re-entry и mode budgets. Router не читает state и не вызывает модель.

### Задача 3: Persona spine и truth contract

**Файлы:**

- Создать: `src/humanlike_agent/persona.py`
- Создать: `examples/hermes-humanlike/SOUL.md`
- Тест: `tests/test_persona.py`

**RED:** parser сохраняет identity/voice/values, anchor bounded, disclosure hard rule всегда присутствует, path traversal блокируется.

```python
def test_anchor_is_bounded_and_truthful(tmp_path):
    persona = Persona.load(tmp_path / "SOUL.md")
    anchor = persona.anchor(max_chars=600)
    assert len(anchor) <= 600
    assert "не выдавай себя за человека" in anchor.lower()
```

**GREEN:** безопасный Markdown parser без исполнения frontmatter, stable SHA-256 fingerprint, bounded anchor и hard/soft section separation.

## Батч 2 — Память, творчество, поведенческая устойчивость

### Задача 4: Typed evidence-aware SQLite memory ledger

**Файлы:**

- Создать: `src/humanlike_agent/memory.py`
- Тест: `tests/test_memory.py`

**RED:** zero writes on no-save, typed record validation, scope isolation, expiry, supersession, conflict query и `why_recalled`.

```python
def test_no_save_turn_creates_no_database(tmp_path):
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(record(), no_save=True)
    assert not (tmp_path / "memory.db").exists()
```

**GREEN:** lazy schema creation, parameterized SQL, 0600 DB permissions, rebuildable records, no raw transcript columns.

### Задача 5: Creative studio и foundation pack

**Файлы:**

- Создать: `src/humanlike_agent/creative.py`
- Создать: `packs/foundation/manifest.json`
- Создать: `packs/foundation/rubric.json`
- Создать: `packs/foundation/anti-patterns.json`
- Тест: `tests/test_creative.py`

**RED:** ordinary chat retrieves nothing; creative request selects five distinct mechanisms; rights-ineligible records rejected; selector uses task-fit before preference.

```python
def test_creative_plan_changes_mechanism_not_wording(pack):
    plan = pack.plan("Придумай концепцию короткого фильма")
    assert len(plan.strategies) == 5
    assert len(set(plan.strategies)) == 5
```

**GREEN:** strategies `inversion`, `distant_analogy`, `constraint_shift`, `tension_first`, `concrete_counterexample`; bounded retrieval and deterministic candidate scoring contract.

### Задача 6: Discourse repetition, stance и drift

**Файлы:**

- Создать: `src/humanlike_agent/discourse.py`
- Создать: `src/humanlike_agent/stance.py`
- Создать: `src/humanlike_agent/drift.py`
- Тест: `tests/test_behavior_controls.py`

**RED:** repeated tactic chain triggers alternative; wrong-pressure and legitimate-correction instructions differ; drift threshold requests short re-anchor while normal session does not.

```python
def test_repeated_empathy_tactic_is_rotated():
    guard = DiscourseGuard(history_limit=8)
    for _ in range(3):
        guard.observe(("validate", "paraphrase", "offer_help"))
    assert guard.recommend("support")[0] != "validate"
```

**GREEN:** metadata-only bounded deques, correction-selectivity guidance, deterministic probe scoring and anchor cooldown.

## Батч 3 — Runtime, Hermes и conformance

### Задача 7: Runtime orchestration и privacy receipts

**Файлы:**

- Создать: `src/humanlike_agent/runtime.py`
- Тест: `tests/test_runtime.py`
- Тест: `tests/test_privacy.py`

**RED:** end-to-end plan is bounded, hard truth/privacy tail survives truncation, component failures fail open, receipt contains no raw text, no-save blocks every durable write.

```python
def test_packet_hard_limit_and_hard_tail(runtime):
    plan = runtime.prepare(TurnInput(text="Напиши рассказ " + "x" * 5000))
    packet = plan.render_context()
    assert len(packet) <= runtime.config.deep_context_chars
    assert "IDENTITY_TRUTH" in packet
```

**GREEN:** priority composer, component error isolation, hashed turn fingerprint, metadata counters and finalize cleanup.

### Задача 8: Hermes adapter и CLI

**Файлы:**

- Создать: `src/humanlike_agent/adapters/hermes.py`
- Создать: `src/humanlike_agent/cli.py`
- Создать: `src/humanlike_agent/__main__.py`
- Создать: `plugin.yaml`
- Создать: `__init__.py` — корневой Hermes registration shim, который безопасно добавляет локальный `src/` в import path
- Тест: `tests/test_hermes_adapter.py`
- Тест: `tests/test_cli.py`

**RED:** fake Hermes `pre_llm_call` returns context; unsupported payload fails neutral; transform gate can block identity deception; `humanlike route`, `doctor`, `eval` return stable JSON/non-zero errors.

**GREEN:** thin adapter with no host state leakage and argparse CLI. Plugin manifest и shim находятся в корне: `hermes plugins install owner/repo` копирует выбранный каталог, поэтому вложенный adapter не должен терять core package.

### Задача 9: Offline conformance runner

**Файлы:**

- Создать: `src/humanlike_agent/evals.py`
- Создать: `evals/cases/ru.jsonl`
- Создать: `evals/cases/en.jsonl`
- Тест: `tests/test_evals.py`

**RED:** runner catches wrong route, privacy regression and over-budget packet; official fixture set is fully green and reports dimension-level scores rather than one human score.

**GREEN:** deterministic checks for route, social move, constraints, budget, required/forbidden policy IDs and report JSON.

## Батч 4 — Выпуск и закрытый remote

### Задача 10: Документация, security и packaging gates

**Файлы:**

- Создать: `README.md`, `SECURITY.md`, `LICENSE`, `CHANGELOG.md`
- Создать: `docs/ARCHITECTURE.md`, `docs/PRIVACY.md`, `docs/COMPATIBILITY.md`, `docs/THREAT_MODEL.md`
- Создать: `scripts/privacy_gate.py`, `.github/workflows/ci.yml`, `.gitignore`
- Тест: `tests/test_privacy_gate.py`, `tests/test_docs.py`

**RED/GREEN:** tests требуют отсутствие абсолютных/private paths и секретов, рабочие README-команды, all-rights-reserved license и reproducible build.

### Задача 11: Полная верификация

Выполнить:

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
uv build
python scripts/privacy_gate.py .
python -m venv /tmp/humanlike-wheel-smoke
/tmp/humanlike-wheel-smoke/bin/pip install dist/*.whl
/tmp/humanlike-wheel-smoke/bin/humanlike doctor --config examples/hermes-humanlike/humanlike.toml
```

Дополнительно: benchmark 1,000 `prepare()` calls, SQLite `PRAGMA quick_check`, `git diff --check`, secret/path scan и independent final review.

### Задача 12: Git history и private GitHub repository

1. Работать в `feat/initial-product`, не в `main`.
2. Создать атомарные commits по батчам.
3. Проверить `gh auth status`; при валидной авторизации создать:

```bash
gh repo create humanlike-agent-kit --private --source=. --remote=origin --push
```

4. Проверить через API: `visibility == PRIVATE`, default branch и pushed HEAD.
5. Если GitHub auth недействителен, локальный продукт и история остаются готовыми; запросить только re-authentication, не ослаблять приватность и не создавать public fallback.

## Зависимости

- Задачи 1–3 блокируют 4–9.
- Задачи 4–6 независимы после contracts.
- Задача 7 объединяет 1–6.
- Задачи 8–9 зависят от runtime.
- Задачи 10–12 выполняются после полного API freeze.

## Definition of Done

- Все задачи и review закрыты.
- Все автоматические проверки зелёные.
- Приватные/персональные материалы отсутствуют в Git history.
- Private remote создан и подтверждён; при внешнем auth blocker локальный репозиторий полностью готов и blocker сформулирован одним действием.
