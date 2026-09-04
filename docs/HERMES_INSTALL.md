# Installing Humanlike in Hermes

[English](#english) · [Русский](#русский)

## English

Humanlike is distributed as a Python package with an official Hermes plugin entry point. Hermes discovers it from its own runtime environment. GitHub authentication is not required for the public repository.

The full source repository contains adversarial test strings used by its safety suite. Because Hermes correctly scans every file in a directory-plugin clone, installing the full repository with `hermes plugins install AlekseiUL/humanlike` is not the supported route. Install the reviewed Python package into the Hermes runtime instead.

### Requirements

- Hermes Agent with `hermes plugins` (verified against Hermes v0.21).
- `uv` and Git access to `AlekseiUL/humanlike`.
- macOS, Linux, WSL2, or native Windows with Python 3.11 or newer. Native Windows uses the memory-off plugin mode in `0.1.x`.

### Install

Use a reviewed full commit SHA rather than a moving branch:

```bash
HERMES_PYTHON="$(dirname "$(command -v hermes)")/python"
uv pip install --python "$HERMES_PYTHON" \
  "git+https://github.com/AlekseiUL/humanlike.git@<40-character-commit-sha>"
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
hermes plugins show humanlike-agent-kit
```

Start a new Hermes session after enabling it. Restart a gateway only when it is safe to interrupt its active work.

Native Windows (PowerShell):

```powershell
$HermesPython = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\.venv\Scripts\python.exe"
uv pip install --python $HermesPython `
  "git+https://github.com/AlekseiUL/humanlike.git@<40-character-commit-sha>"
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
hermes plugins show humanlike-agent-kit
```

The optional Humanlike SQLite memory ledger remains disabled on native Windows in `0.1.x`. WSL2 is the supported Windows route when that ledger is required.

The starter runtime registers four hooks and no tools:

- `pre_llm_call`
- `transform_llm_output`
- `post_llm_call`
- `on_session_finalize`

Memory is off by default. The plugin does not need model credentials, and its core runtime makes no network calls.

### Verify

```bash
hermes plugins show humanlike-agent-kit
humanlike eval
```

`hermes plugins show` confirms that Hermes discovered the installed entry point and reports whether it is enabled. `humanlike eval` loads the installed package and runs its bundled offline behavior suite. For a source checkout, `hermes plugins doctor . --ci` separately validates the directory-plugin adapter.

### Roll back or remove

Disable first. This is the fastest rollback:

```bash
hermes plugins disable humanlike-agent-kit
```

Start a new Hermes session. To remove the installed package as well:

```bash
HERMES_PYTHON="$(dirname "$(command -v hermes)")/python"
uv pip uninstall --python "$HERMES_PYTHON" humanlike-agent-kit
```

The plugin does not change model credentials or delete Hermes transcripts. Uninstalling it does not remove data retained by Hermes, a model provider, logs, or backups.

## Русский

Humanlike устанавливается как Python-пакет с официальной точкой подключения Hermes. Hermes находит плагин в своей рабочей Python-среде. Для публичного репозитория авторизация GitHub не требуется.

В полном репозитории есть провокационные тестовые строки для проверки безопасности. Hermes правильно сканирует все файлы directory-плагина и блокирует такие строки. Поэтому команда `hermes plugins install AlekseiUL/humanlike` для этого репозитория не подходит. Надёжный путь — установить проверенный Python-пакет прямо в среду Hermes.

### Требования

- Hermes Agent с командой `hermes plugins` (проверено на Hermes v0.21).
- `uv` и доступ к `AlekseiUL/humanlike` через Git.
- macOS, Linux, WSL2 или нативный Windows и Python 3.11 или новее. В нативном Windows ветка `0.1.x` использует плагин с выключенной памятью.

### Установка

Используйте полный SHA проверенного коммита, а не меняющуюся ветку:

```bash
HERMES_PYTHON="$(dirname "$(command -v hermes)")/python"
uv pip install --python "$HERMES_PYTHON" \
  "git+https://github.com/AlekseiUL/humanlike.git@<40-character-commit-sha>"
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
hermes plugins show humanlike-agent-kit
```

После включения начните новую сессию Hermes. Gateway перезапускайте только тогда, когда можно безопасно прервать его текущую работу.

Нативный Windows (PowerShell):

```powershell
$HermesPython = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\.venv\Scripts\python.exe"
uv pip install --python $HermesPython `
  "git+https://github.com/AlekseiUL/humanlike.git@<40-character-commit-sha>"
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
hermes plugins show humanlike-agent-kit
```

Опциональная SQLite-память Humanlike в нативном Windows для ветки `0.1.x` остаётся выключенной. Если она нужна, используйте WSL2.

Стартовый режим регистрирует четыре hook и не добавляет инструменты:

- `pre_llm_call`
- `transform_llm_output`
- `post_llm_call`
- `on_session_finalize`

Память по умолчанию выключена. Плагину не нужны ключи моделей, а его основная логика не обращается к сети.

### Проверка

```bash
hermes plugins show humanlike-agent-kit
humanlike eval
```

`hermes plugins show` подтверждает, что Hermes обнаружил установленную точку подключения, и показывает её состояние. `humanlike eval` загружает установленный пакет и запускает встроенный офлайн-набор поведенческих проверок. В клоне исходников команда `hermes plugins doctor . --ci` отдельно проверяет directory-адаптер.

### Откат и удаление

Сначала отключите плагин — это самый быстрый откат:

```bash
hermes plugins disable humanlike-agent-kit
```

После этого начните новую сессию Hermes. Для полного удаления пакета:

```bash
HERMES_PYTHON="$(dirname "$(command -v hermes)")/python"
uv pip uninstall --python "$HERMES_PYTHON" humanlike-agent-kit
```

Плагин не меняет ключи моделей и не удаляет историю Hermes. Удаление пакета не стирает данные, уже сохранённые Hermes, провайдером модели, логами или резервными копиями.
