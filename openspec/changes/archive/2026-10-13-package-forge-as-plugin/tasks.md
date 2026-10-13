# Tasks

## 1. Перенос ядра под корень плагина

- [x] 1.1 Перенести `tools/forge_model/` в `plugin/forge/src/forge_model/` через `git mv` без правки импортов; проверка: `git status` показывает переименования, а не удаление и добавление
- [x] 1.2 Перевести `pyproject.toml` на новый путь (`packages`, `pythonpath`, `mypy_path`, `files`) по design D7 и обновить `uv.lock`; проверка: `uv run --extra dev pytest -q`, `ruff check`, `ruff format --check`, `mypy` зелёные
- [x] 1.3 Перевести `.github/workflows/model.yml`, `quality.yml`, `tests.yml` на новые пути; проверка: в workflow нет упоминаний `tools/forge_model` и `PYTHONPATH=tools`
- [x] 1.4 Создать `plugin/forge/.claude-plugin/plugin.json` с `name`, `version: 0.1.0`, `description`; проверка: тест читает манифест и сверяет `version` с `pyproject.toml`

## 2. Вход и окружение

- [x] 2.1 Записать `plugin/forge/src/requirements.txt` с пинами `pyyaml==6.0.3`, `psycopg[binary]==3.3.5` из `uv.lock` и закрепить те же версии в `dependencies` `pyproject.toml`; проверка: тест «каждая строка — комментарий или пин `==`» и сверка с `pyproject.toml`
- [x] 2.2 Написать `plugin/forge/lib/python-env.sh` с `prepare_python_env`: каталог `${CLAUDE_PLUGIN_DATA}` или пользовательский кеш, метка `.env-mark` (версия интерпретатора, способ, sha256 `requirements.txt`), перебор `uv` → `venv`, код `2` при исчерпании; проверка: тесты сборки, повторного использования при совпадении метки, пересборки при смене пина, кода `2` без обоих способов
- [x] 2.3 Написать `plugin/forge/bin/forge` (POSIX sh): корень поставки через `command -v "$0"`, окружение, `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE=1`, `exec … -m forge_model`; проверка: `forge --help` и `forge <подкоманда> --help` для всех подкоманд дают `0`, вызов из каталога вне проекта находит ядро
- [x] 2.4 Добавить тест «вход не пишет в корень плагина»: снимок дерева `plugin/forge/` до и после прогона всех подкоманд совпадает

## 3. Корень проекта, каталоги и коды возврата

- [x] 3.1 Реализовать `_project_root()` (`CLAUDE_PROJECT_DIR`, иначе `.git` вверх) и разрешение умолчаний `DEFAULT_*` от корня проекта; проверка: тест прогона `build` из подкаталога даёт ту же модель, тест без корня даёт код `2`
- [x] 3.2 Добавить переменные `FORGE_MODEL_DIR`, `FORGE_RELEASES_DIR`, `FORGE_CHANGELOG_DIR`, `FORGE_RUNS_DIR` с приоритетом «ключ → переменная → умолчание»; проверка: тесты «переменная переносит каталог» и «ключ перекрывает переменную»
- [x] 3.3 Ввести `EXIT_OK`/`EXIT_REJECTED`/`EXIT_ENVIRONMENT` и `EnvironmentFault`; отобразить коды по таблице design D4: незамкнутый цикл → `1`, ошибка процесса цикла и недоступное хранилище → `2`; проверка: обновлённые `tests/test_intent_cli.py`, `tests/test_cli.py` и новые тесты на `verify` с недоступным DSN
- [x] 3.4 Печатать рекомендацию `.gitignore` при первом создании каталога отчётов цикла, не правя `.gitignore`; проверка: тест на рекомендацию и неизменность `.gitignore`
- [x] 3.5 Обновить `docs/model-intent-loop.md` под новые коды возврата и корень проекта; проверка: в документе коды `0`/`1`/`2` совпадают с таблицей design D4

## 4. Нормы модели, глоссарий и образец

- [x] 4.1 Перенести нормативные положения `docs/model-format.md`, `docs/model-evolution.md`, `docs/migrations.md` в `plugin/forge/share/rules/model-rules.md` с кодами `MDL-NNN` (заголовок, назначение, навигация, таблица правил, таблица версий); проверка: каждый абзац `**[MDL-NNN]**` уникален, расхождения положений с кодом записаны для приёмочного отчёта
- [x] 4.2 Свести понятия модели в `plugin/forge/share/docs/glossary.md` в формате TERM-004; проверка: каждое понятие, использованное в `model-rules.md`, раскрыто в глоссарии
- [x] 4.3 Сжать `docs/model-format.md`, `docs/model-evolution.md`, `docs/migrations.md` до пользовательского описания со ссылками на нормы по DOC-023 и обновить их таблицы версий; проверка: в `docs/` нет абзацев `**[MDL-…]**` и пересказа норм
- [x] 4.4 Реализовать `forge norms` и `forge norms --rule КОД`; проверка: тесты «все нормы и глоссарий, код `0`», «раздел существующего правила», «неизвестный код — `2`»
- [x] 4.5 Создать образец `plugin/forge/templates/sample-model/` из урезанной фикстуры и подкоманду `forge sample`; проверка: тест раскладывает вывод `sample` во временный проект и получает `0` от `forge build`

## 5. Навыки

- [x] 5.1 Написать `plugin/forge/skills/model-change/SKILL.md` по design D6: фронтматтер с `Bash(forge:*)`, границы, шаги, таблица исходов, таблица версий; нормы названы кодом и вызовом `forge norms --rule`; проверка: тест фронтматтера навыков и отсутствие пересказа норм
- [x] 5.2 Написать `plugin/forge/skills/model-release/SKILL.md`: состояние по дескриптору и реестру, стоп-знак перед `forge gen`, `forge verify`, таблица исходов, таблица версий; проверка: тест фронтматтера и наличие шага подтверждения перед `forge gen`
- [x] 5.3 Заменить раздел «Команды» `docs/migrations.md` ссылкой на навык `forge:model-release`; проверка: шаги выпуска в `docs/` и `README.md` не перечислены

## 6. Подключение плагина

- [x] 6.1 Создать `.claude-plugin/marketplace.json` с записью `forge` → `./plugin/forge`; проверка: тест читает запись и проверяет относительный путь
- [x] 6.2 Создать коммитимый `.claude/settings.json` с локальным маркетплейсом `directory` и `enabledPlugins`; проверка: в новом сеансе Claude Code в репозитории `forge --help` даёт `0`, а навыки `forge:model-change` и `forge:model-release` видны в списке
- [x] 6.3 Добавить `@`-импорты `plugin/forge/share/rules/model-rules.md` и `plugin/forge/share/docs/glossary.md` в `CLAUDE.md` (и `AGENTS.md`, если он подключает правила) со строкой версий, называющей локальное отличие от kit'а; проверка: нормы `MDL` видны в контексте нового сеанса
- [x] 6.4 Переписать «Быстрый старт» `README.md`: подключение плагина в проекте-потребителе через `.claude/settings.json` и вызовы `forge`; проверка: команды из README выполняются в репозитории-источнике с кодом `0`
- [x] 6.5 Проверить установку в чистый проект-потребитель: временный каталог с `.git` и `.claude/settings.json`, указывающим на маркетплейс репозитория; проверка: `forge sample`, `forge build` дают `0`, в дереве потребителя нет файлов поставки

## 7. Строгая проверка спецификаций

- [x] 7.1 Добавить шаг `openspec validate --all --strict` в `quality.yml`; проверка: локальный прогон той же команды зелёный, включая `intent-pipeline` после синхронизации дельты

## 8. Приёмка

- [x] 8.1 Пройти чек-лист `docs/spec/agent-plugin-blueprint/conformance.md` и записать `docs/reports/apb-conformance.md` в форме базового отчёта: исходы, утверждённые отклонения (оси применимости, зависимости, `venv-target`, pytest, локальное отличие `CLAUDE.md`), долг `layer-forge-core`; проверка: все 26 несоответствий, отнесённых к этому change, имеют исход «Соответствует» либо названную причину
- [x] 8.2 Прогнать полный набор: `uv run --extra dev pytest -q`, `ruff check`, `ruff format --check`, `mypy`, `sh tools/make-lint/check.sh`, `openspec validate --all --strict`; проверка: все команды завершаются кодом `0`

## Workflow follow-up

- Архивировать change после ревью и синхронизировать дельты `ci-checks` и `intent-pipeline` в основные спеки.
- До синхронизации дельт шаг `openspec validate --all --strict` в `quality.yml` на ветке красный: `intent-pipeline` проходит `--strict` только после синхронизации. Владелец оставил шаг в пайплайне.
- Открыть change `layer-forge-core` для APB-004..006 и отклонений D01–D05.

## Версионирование

| Версия | Дата | Задача | Агент | Модель | Описание изменений |
|--------|------|--------|-------|--------|--------------------|
| 1.0.0 | 2026-10-13 | FRG-010: перевести forge на архитектуру плагина | Claude Code | Claude Opus 5.5 | Начальное создание: восемь групп задач от переноса ядра до приёмочного отчёта |
| 1.0.1 | 2026-10-13 | FRG-010: решение владельца при внедрении | Claude Code | Claude Opus 5.5 | В «Workflow follow-up» записано: шаг строгой проверки спецификаций остаётся в `quality.yml` и до синхронизации дельт на ветке красный — решение владельца |
