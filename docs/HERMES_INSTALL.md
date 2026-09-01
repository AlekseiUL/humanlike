# Installing Humanlike Agent Kit in Hermes

[English](#english) · [Русский](#русский)

## English

Humanlike Agent Kit is a native Hermes directory plugin. Use Hermes' own plugin manager rather than copying files or running a separate installer. The repository is private, so the current GitHub account must already have access.

### Requirements

- Hermes Agent with the `hermes plugins` command (verified against Hermes v0.21).
- Git access to `AlekseiUL/humanlike-agent-kit`.
- macOS, Linux, or WSL with Python 3.11 or newer.

### Safe installation

Install the plugin disabled, validate it with the real Hermes runtime contracts, and only then enable it:

```bash
hermes plugins install AlekseiUL/humanlike-agent-kit --no-enable
hermes plugins doctor humanlike-agent-kit --ci
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
```

Start a new Hermes session after enabling the plugin. If a gateway process should use it, restart that gateway only when it is safe to interrupt active work.

The plugin registers four hooks and no tools:

- `pre_llm_call`
- `transform_llm_output`
- `post_llm_call`
- `on_session_finalize`

Memory is disabled in the bundled starter profile. No model credential is required by the plugin, and its core runtime makes no network calls.

### Reproducible pinned installation

For a reviewed deployment, pin the exact 40-character Git commit SHA:

```bash
hermes plugins install AlekseiUL/humanlike-agent-kit \
  --ref <40-character-commit-sha> \
  --no-enable
hermes plugins doctor humanlike-agent-kit --ci
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
```

A pinned plugin does not move during `hermes plugins update`. Review a newer commit, then reinstall it explicitly with `--force --ref <new-40-character-commit-sha>`.

### Health checks

Validate the installed plugin with Hermes:

```bash
hermes plugins doctor humanlike-agent-kit --ci
```

If you also installed the Python package or are working from a source checkout, validate the starter profile and offline behavior suite separately:

```bash
humanlike doctor --config examples/hermes-humanlike/humanlike.toml
humanlike eval
```

`hermes plugins doctor` checks Hermes discovery, manifest parsing, import, and registration. It does not install the optional `humanlike` console command. `humanlike doctor` checks one Humanlike profile, and `humanlike eval` runs the bundled offline behavior suite when the Python package is installed.

### Disable, rollback, and remove

Disable first. This is the fastest rollback and preserves the installed files for inspection:

```bash
hermes plugins disable humanlike-agent-kit
```

Start a new Hermes session after disabling it. Remove the plugin only when it is no longer needed:

```bash
hermes plugins remove humanlike-agent-kit
```

The plugin does not alter model credentials or Hermes transcripts. Removing it does not delete data already retained by Hermes, a model provider, logs, or backups.

## Русский

Humanlike Agent Kit — нативный directory plugin для Hermes. Используйте штатный менеджер плагинов Hermes: отдельный установщик и ручное копирование файлов не нужны. Репозиторий приватный, поэтому у текущего аккаунта GitHub уже должен быть доступ.

### Требования

- Hermes Agent с командой `hermes plugins` (проверено на Hermes v0.21).
- Доступ к `AlekseiUL/humanlike-agent-kit` через Git.
- macOS, Linux или WSL и Python 3.11 или новее.

### Безопасная установка

Сначала установите плагин выключенным, проверьте его реальным Hermes Doctor и только потом включите:

```bash
hermes plugins install AlekseiUL/humanlike-agent-kit --no-enable
hermes plugins doctor humanlike-agent-kit --ci
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
```

После включения начните новую сессию Hermes. Если плагин нужен работающему gateway, перезапускайте только этот gateway и только когда можно безопасно прервать текущую работу.

Плагин регистрирует четыре hook и не добавляет инструменты:

- `pre_llm_call`
- `transform_llm_output`
- `post_llm_call`
- `on_session_finalize`

Во встроенном стартовом профиле память выключена. Плагину не нужны ключи моделей, а его основная логика не обращается к сети.

### Воспроизводимая установка

Для контролируемой установки закрепите полный 40-символьный SHA проверенного коммита:

```bash
hermes plugins install AlekseiUL/humanlike-agent-kit \
  --ref <40-character-commit-sha> \
  --no-enable
hermes plugins doctor humanlike-agent-kit --ci
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
```

Закреплённый плагин не обновляется командой `hermes plugins update`. Сначала проверьте новый коммит, затем явно переустановите его с `--force --ref <new-40-character-commit-sha>`.

### Проверка плагина

```bash
hermes plugins doctor humanlike-agent-kit --ci
```

Если вы также установили Python-пакет или работаете из клона репозитория, отдельно проверьте стартовый профиль и офлайн-набор тестов:

```bash
humanlike doctor --config examples/hermes-humanlike/humanlike.toml
humanlike eval
```

`hermes plugins doctor` проверяет обнаружение, manifest, импорт и регистрацию в Hermes. Он не устанавливает дополнительную консольную команду `humanlike`. `humanlike doctor` проверяет профиль Humanlike, а `humanlike eval` запускает встроенные тесты, когда Python-пакет установлен.

### Отключение и удаление

Сначала отключите плагин. Это быстрый rollback без удаления файлов:

```bash
hermes plugins disable humanlike-agent-kit
```

После отключения начните новую сессию Hermes. Если плагин больше не нужен, удалите его штатной командой:

```bash
hermes plugins remove humanlike-agent-kit
```

Плагин не меняет ключи моделей и историю Hermes. Его удаление не стирает данные, которые уже сохранили Hermes, провайдер модели, логи или резервные копии.
