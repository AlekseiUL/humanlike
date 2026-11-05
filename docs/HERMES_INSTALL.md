# Installing Humanlike in Hermes (0.3.0)

[English](#english) · [Русский](#русский)

## English

### Install without changing Hermes' Python environment

Requirements: Python 3.11+, Git, `uv`, and Hermes with native plugin commands and
`post_gateway_admission`. Native command/hook interfaces were exercised on Hermes
0.22.6, revision `f0d94882`. This is an isolated compatibility checkpoint, not a
live Telegram delivery test or a guarantee for every Hermes distribution.

On Linux/macOS/WSL2, install the reviewed package into its **own** environment:

```bash
uv venv .humanlike-cli
uv pip install --python .humanlike-cli/bin/python \
  "git+https://github.com/AlekseiUL/humanlike.git@<40-character-commit-sha>"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
mkdir -p "$HERMES_HOME/plugins"
.humanlike-cli/bin/humanlike export-plugin \
  --output "$HERMES_HOME/plugins/humanlike-agent-kit"
hermes plugins doctor "$HERMES_HOME/plugins/humanlike-agent-kit" --ci
hermes plugins enable humanlike-agent-kit --no-allow-tool-override
hermes plugins show humanlike-agent-kit
```

Replace the SHA with the reviewed release commit. For a named Hermes profile, set
`HERMES_HOME` to **that profile's home before running these commands**. Do not mix
one profile's plugin directory with another profile's enable command. The exporter
creates a new runtime-only directory; it does not enable the plugin, overwrite an
existing installation, copy user state, or install dependencies into Hermes.
Do not clone the whole repository into `plugins`: its adversarial tests are not
runtime files. No scanner bypass is required or recommended.

Start a new Hermes process after enabling. Restart a gateway only when its owner
has approved a safe interruption. Memory stays OFF: plugin enable is not consent.
The normal memory-off behavior layer works immediately. No Python callbacks or
additional model credentials are needed.

Native Windows: the behavioral core and memory-off plugin work; SQLite controls
remain POSIX-only. Use WSL2 for this memory workflow. The exporter can also be run
from a normal Windows package environment, but this guide's shell commands are for
POSIX hosts.

### First conversation (Telegram human DM)

1. Send one ordinary message to start the Hermes conversation.
2. Send `/humanlike enable memory`, then `/humanlike I agree to local memory`.
3. Read the proposed action and send the **exact fresh confirmation command** shown
   by the plugin. Only `[enabled]` confirms consent was saved.
4. Say `Usually keep replies short`. `[pending]` means **not saved**. Send
   `/humanlike confirm`, then the displayed `/humanlike confirm …` command.
5. Ask `What do you remember?`, converse normally, then ask `Why did you use that?`.

Every consent/save/correct/forget/resume command needs a fresh, single-use
confirmation valid for five minutes. A static slash command alone is insufficient:
Hermes' command source does not expose forwarded-message provenance. The challenge
binds the exact request, owner/chat, session and policy. Do not confirm a request
you did not make. No record IDs or developer-written callbacks are needed.

After `/new`, restart, or a long-idle binding eviction, send `/humanlike status`
once in the current conversation. Without this binding the plugin does not infer
identity from a model hook. Unsupported platforms/groups/threads return
`[unavailable]`; errors do not claim completion. Native CLI has session-local slash
controls, but **not automatic admitted-message memory/continuity injection**.

### Supported wording, not arbitrary extraction

| Need | English | Russian |
|---|---|---|
| General short replies | `Usually keep replies short` | `Обычно отвечай кратко` |
| Detailed learning | `Explain learning topics in detail` | `Объясняй учебные темы подробно` |
| Inspect | `What do you remember?` | `Что ты помнишь?` |
| Why used | `Why did you use that?` | `Почему ты это использовал?` |
| Correct general length | `Correct that: usually give detailed replies` | `Исправь это: обычно отвечай подробно` |
| Forget one unambiguous preference | `Forget that` | `Забудь это` |
| Disambiguate forget | `Forget general reply length` | `Забудь длину общих ответов` |
| Stop capture and recall | `Pause memory` | `Отключи память` |
| Session no-save | `Do not save this session` | `Не сохраняй эту сессию` |
| Session no-recall | `Do not recall this session` | `Не вспоминай в этой сессии` |
| Resume session modes | `Resume this session` | `Возобнови эту сессию` |

Use `/humanlike <request>` for explicit controls; the same supported phrases in a
bound Telegram conversation can inspect, pause or propose changes. Bare `confirm`
in ordinary chat never writes. `/humanlike cancel` cancels a proposal/challenge.
`/humanlike help` and `/humanlike status` show scope and state.

The closed parser extracts only reply-length preferences, with `general` or
`learning` domains and `always` condition. Unknown wording is not guessed. A
one-off `This reply shorter` remains a normal request, not a saved preference.
There is no model extractor, mood/personality inference, or hidden provider call.
Learning preferences are selected on explicit explain/teach requests; otherwise
general defaults apply. Current instructions and corrections outrank stored defaults.

### Continuity and controls

After consent and binding, `continue`, `the second version`, `use my last correction`
and `we discussed <topic>` resolve against a bounded recent host history. Russian
forms include `продолжи`, `второй вариант`, `используй мою последнюю поправку` and
`мы обсуждали <тема>`. Missing references remain missing; ambiguity asks a question.
The resolver includes actual host tool rows, never treats an assistant's claim as
a completed tool action, and does not rewrite history or crawl archives.

Inspection shows stored versions, domain, condition, source reference and relation.
Why-use reports what was offered as context, not proof that the model followed it.
The native view is bounded to fewer than 50 versions; a larger history returns
`[inspection_limit]` and requires the paged SDK rather than silently hiding targets.
No-save blocks new captures; no-recall blocks injection but still permits owner
inspection. These session flags survive restart; resume clears them explicitly.

State lives at `plugin-data/humanlike/memory.sqlite` under the selected Hermes home.
It is local, unencrypted, POSIX-only SQLite. Owner/chat scopes are separate within
the profile; no cross-chat promotion. Fresh installations have no seeded memories.
Forget removes the selected preference's whole version lineage and source text
from Humanlike; opaque replay fences remain. It **does not** delete Hermes
transcripts, model-provider copies, filesystem snapshots or backups. Pause retains
records so you can inspect/forget them. See [privacy](PRIVACY.md).

### Verify and roll back

`hermes plugins doctor <exported-directory> --ci` checks the directory package;
`hermes plugins show humanlike-agent-kit` checks discovery/enabled state. Neither
proves live transport delivery. The developer smoke `scripts/native_smoke.py`
exercises the real native interfaces using a new synthetic home and no network.
The [quality report](NATIVE_EVALUATION.md) separates functional proof from LLM A/B.

Disable with `hermes plugins disable humanlike-agent-kit`, then start a new process
when safe. To upgrade, preserve the old plugin directory and local ledger using your
normal private backup procedure, export into a **new** directory, inspect it, then
replace only the disabled plugin. Existing targets and symlink parents are rejected;
a failed export may leave an incomplete new directory, never a claimed installation.
Do not delete state or downgrade its schema as part of an automatic rollback.

## Русский

### Установка

Нужны Python 3.11+, Git, `uv` и Hermes с native-командами плагинов и
`post_gateway_admission`. Проверка выполнена на интерфейсах Hermes 0.22.6,
`f0d94882`, в отдельной синтетической среде — не в живом Telegram.

Выполните команды из английского блока выше: они устанавливают пакет в отдельную
`.humanlike-cli`, экспортируют только рабочие файлы и включают плагин штатной
командой Hermes. Замените SHA проверенным коммитом. Если используете именованный
профиль, сначала задайте `HERMES_HOME` именно для него. Python-среда Hermes не
меняется. Существующий каталог экспорт не перезапишет; весь репозиторий с
провокационными тестами в папку плагинов переносить не нужно.

После включения запустите новый процесс Hermes. Работающий gateway не
перезапускайте без согласования. Обычный режим доступен сразу, память выключена.
Постоянная память поддерживается на Linux/macOS/WSL2; в нативном Windows доступен
режим без неё. Новые ключи моделей и Python-callbacks не нужны.

### Первый диалог

1. Отправьте обычное сообщение Hermes в личном Telegram-чате.
2. Напишите `/humanlike включи память`, затем
   `/humanlike согласен на локальную память`.
3. Проверьте показанный запрос и отправьте свежую команду подтверждения из ответа.
   Только `[enabled]` означает, что согласие сохранено.
4. Напишите `Обычно отвечай кратко`. `[pending]` означает «ещё не сохранено».
   Отправьте `/humanlike подтверждаю`, затем команду с одноразовым кодом из ответа.
5. Спросите `Что ты помнишь?`; после обычного вопроса — `Почему ты это использовал?`.

Согласие, запись, исправление, забывание и возобновление требуют одноразового
подтверждения в течение пяти минут. Это не ID записи: команда уже готова в ответе.
Так пересланная статическая команда не получает право менять память. Не
подтверждайте чужой запрос. `/humanlike отмена` отменяет ожидающее действие.

После `/new`, перезапуска или потери временной привязки отправьте
`/humanlike статус`. Автоматическая память и продолжение доступны в личном
Telegram-чате без темы. В native CLI есть команды в пределах сессии, но нет
автоматической подстановки памяти и контекста. Другие платформы, группы и темы
получают `[unavailable]`; ошибка не выдаётся за успешную запись.

Точные поддерживаемые фразы — в таблице выше. Словарь намеренно небольшой:
длина общих ответов и подробность учебных объяснений. «Этот ответ покороче» не
сохраняется как постоянное правило. Свободного извлечения любых фактов, выводов о
характере или скрытого обращения к другой модели нет.

`Продолжи`, `второй вариант`, `используй мою последнюю поправку`, `мы обсуждали <тема>`
используют только ограниченную недавнюю историю текущего диалога. Неоднозначность
требует уточнения; отсутствующее воспоминание не выдумывается. Последняя просьба
важнее старого предпочтения. История не переписывается, архивы не сканируются.

Просмотр показывает версии, область, условие и источник. Объяснение использования
показывает переданный модели контекст, а не гарантирует её послушание. No-save
останавливает новые записи; no-recall — подстановку, но не просмотр владельцем.
Режимы сохраняются при перезапуске и явно снимаются возобновлением сессии.

SQLite находится в `plugin-data/humanlike/memory.sqlite` внутри выбранного home,
не шифруется и начинается пустой. Чаты и владельцы изолированы. «Забудь» удаляет
цепочку версий выбранного предпочтения из Humanlike; метки защиты от повторов
остаются. Переписка Hermes, копии провайдера и резервные копии не удаляются.
«Отключи память» сохраняет записи для просмотра и удаления. При большом числе
версий `[inspection_limit]` требует постраничного SDK вместо скрытого выбора цели.

Откат: `hermes plugins disable humanlike-agent-kit`, затем безопасный запуск нового
процесса. Перед обновлением сохраните прежний каталог и локальное хранилище своим
приватным способом резервирования. Не удаляйте память и не понижайте её схему
автоматически. [Результат A/B](NATIVE_EVALUATION.md): проверка проведена, но улучшение
качества относительно сильной базовой модели не доказано.
