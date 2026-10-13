# Tasks

## 1. Эталон и каркас тестов архитектуры

- [x] 1.1 Зафиксировать эталон `tests/golden/` прогоном нынешнего кода с фиксированными часами на фикстурах `forge.reqs.v1` и `trade.v1`: дескриптор, миграции выпуска двух версий и свёртки, `master.yaml`, `registry.yaml`, вывод `build`, `diff`, `checks`; проверка: `tests/test_golden.py` зелёный на текущем коде
- [x] 1.2 Написать `tests/test_architecture.py` на `ast` по design D11 с перечнем переложенных модулей, пока пустым; проверка: тест зелёный, а на подставном модуле с запрещённым импортом, изменяемым `Input` или второй публичной операцией сценария даёт отказ

## 2. Модуль `delivery`

- [x] 2.1 Перенести `delivery.py` в `delivery/infrastructure.py` (`PackageDeliveryFiles`), добавить контракт `DeliveryFiles` и сценарии `ShowNorms`, `ShowSample` по design D9; подключить их в `cli.py` через временную фабрику; удалить `delivery.py`; проверка: `tests/test_plugin_norms.py` и `test_plugin_entry.py` зелёные, `delivery` внесён в перечень теста архитектуры и проходит его

## 3. Модуль `contract`

- [x] 3.1 Вынести объекты модели в `contract/domain.py` с `Place(file, line)` и именами по design D10 (`RelationSignature`, `Enum`, `TakenNumbers`); проверка: mypy зелёный, классы `frozen`
- [x] 3.2 Написать `YamlModelSource` в `contract/infrastructure.py`: разбор через `yaml.compose` с метками строк, накопление ошибок формата в `ModelReading` по design D4; проверка: тесты синтаксической ошибки с номером строки и двух ошибок формата в одном файле
- [x] 3.3 Свести `validate.py` и проверки формы значений из `model.py` в единственное доменное правило `structure_findings` с перечнем всех нарушений; проверка: сценарии дельты `model-contract` «Два нарушения в одном файле» и «Нарушения в разных файлах» как тесты; правило вызывается только из `compile_descriptor`
- [x] 3.4 Ввести `Descriptor` как неизменяемый объект домена, каноническую форму и хеш в домене по design D5, дельту `diff(old, new) -> Delta` с `Operation` и `OperationClass`; удалить `model.py`, `validate.py`, `descriptor.py`, `diff.py`; проверка: `tests/test_golden.py` — дескриптор и хеш побайтно, `test_descriptor.py`, `test_model_format.py` переведены на новые пути и зелёные
- [x] 3.5 Написать сценарии `BuildModel` и `DiffModel` с контрактами `ModelSource`, `ReleasedDescriptors` и `Discrepancy`; подключить в `cli.py`; удалить `ModelError` из пути отказа модели; проверка: `test_cli.py` зелёный, ожидание отказа модели обновлено на перечень с номерами строк, `contract` проходит тест архитектуры

## 4. Модуль `release`

- [x] 4.1 Перенести гейт совместимости в домен `release` (`CompatibilityGate`, `GateDecision`) с исходами-значениями вместо `GateError` по design D6; проверка: `test_release.py` переведён на исходы и зелёный, исключений гейт не поднимает
- [x] 4.2 Перенести `gen/ops.py` в домен как `MigrationStep`, правила раскладки `MDL-030..032` — в домен, `gen/postgres.py` — в `PostgresDialect` за контрактом `MigrationDialect`; проверка: `test_generation.py` зелёный, `tests/test_golden.py` — миграции побайтно
- [x] 4.3 Ввести агрегат `Release` с текстами миграций, порядком применения, записью реестра с контрольными суммами и добавленными занятыми номерами; контракт записи `ReleaseRepository.add` в домене; проверка: тест агрегата — пересобранный дескриптор содержит занятые номера, хеш не изменился
- [x] 4.4 Написать `FileReleaseRepository`, `FileReleasedDescriptors`, `FileRegistryEntries` с общим `ChangelogPaths`; удалить `release.py`, `registry.py`, `gen/`; проверка: `tests/test_golden.py` — `master.yaml`, `registry.yaml`, дескриптор выпуска побайтно; тест «реализации чтения и записи — разные классы»
- [x] 4.5 Написать сценарии `ReleaseModel` и `ReleaseBaseline` и подключить их в `cli.py` вместо `_gen`; проверка: `test_cli.py` и `test_end_to_end.py` зелёные, повторный `gen` неизменной модели — код `0` без исключения, `release` проходит тест архитектуры

## 5. Модуль `store`

- [x] 5.1 Вынести правила целостности и сверку схемы в домен `store` (`IntegrityRule`, `SchemaDrift`, `IntegrityViolation`), SQL — в `PostgresIntegrityQueries`, `PostgresSchemaInspector`, `PostgresIntegrityProbe` по design D7; удалить `checks.py`, `verify.py`; проверка: `test_integrity.py` переведён и зелёный, `tests/test_golden.py` — вывод `checks` побайтно
- [x] 5.2 Написать сценарии `ListChecks` и `VerifyStore` с контрактами чтения и подключить в `cli.py`; проверка: `test_postgres_apply.py` зелёный, тест `verify` с недоступным DSN даёт `2`, конструктор `VerifyStore` не принимает `ReleaseRepository`, `store` проходит тест архитектуры

## 6. Модуль `intent`

- [x] 6.1 Разложить `intent/` по design D8: домен (`Stage`, `StageOutcome`, `Verdict`, `IntentState`, неизменяемый `IterationReport`), слой приложения (`Step`, `StepResult`, `RunIntent`, контракты `ScenarioSource`, `StepsFactory`, `RunHistory`, `RunReports`), инфраструктура (`YamlScenarioSource`, `ScenarioSteps`, `FileRunHistory`, `FileRunReports`); проверка: `test_intent_*.py` переведены и зелёные, коды цикла по спеке `intent-pipeline` не изменились, `intent` проходит тест архитектуры

## 7. Вход, сборка и глоссарий

- [x] 7.1 Вынести создание адаптеров и сборку сценариев в `assembly.py`; `cli.py` зависит только от контрактов сценариев и `EnvironmentFault`; проверка: тест входа с подменённой фабрикой, тест архитектуры по всему пакету без перечня модулей
- [x] 7.2 Дописать в `plugin/forge/share/docs/glossary.md` понятия из design D10 и строку версий; проверка: тест имён по глоссарию зелёный для всех `domain.py`, каждое новое понятие — в формате TERM-004
- [x] 7.3 Поднять версию плагина до `0.2.0` в `plugin/forge/.claude-plugin/plugin.json` и `pyproject.toml`; проверка: тест сверки версий зелёный

## 8. Приёмка

- [x] 8.1 Пересчитать в `docs/reports/apb-conformance.md` проверки 15–27, 29, 30, 55 и отклонения D01–D05 с местом в коде и тестом; удалить раздел долга `layer-forge-core`; проверка: у каждой из 16 проверок исход «Соответствует» либо названная причина, у D01–D05 — тест, который их исключает
- [x] 8.2 Прогнать полный набор: `uv run --extra dev pytest -q`, `ruff check`, `ruff format --check`, `mypy`, `sh tools/make-lint/check.sh`, `openspec validate --all --strict`; проверка: все команды завершаются кодом `0`

## Workflow follow-up

- Архивировать change после ревью и синхронизировать дельты `core-architecture` и `model-contract` в основные спеки.
- Вынести владельцу решения по расхождениям норм с ядром Р1–Р6 из приёмочного отчёта.

## Версионирование

| Версия | Дата | Задача | Агент | Модель | Описание изменений |
|--------|------|--------|-------|--------|--------------------|
| 1.0.0 | 2026-10-13 | FRG-010: перевести forge на архитектуру плагина | Claude Code | Claude Opus 5.5 | Начальное создание: восемь групп задач — эталон, пять модулей ядра, вход и глоссарий, приёмка |
