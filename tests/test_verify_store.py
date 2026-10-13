"""Сценарий сверки хранилища на подставных контрактах: исходы и тексты расхождений.

Хранилище подменено: сценарий зависит только от контрактов чтения, поэтому его поведение
проверяется без запущенного PostgreSQL. Тексты расхождений — те же, что печатал вход
до раскладки по слоям.
"""

from dataclasses import dataclass

from forge_model.contract.infrastructure import YamlModelSource
from forge_model.store.application.contracts import DRIFTED, REJECTED, VERIFIED
from forge_model.store.application.verify_store import VerifyStoreInput, VerifyStoreUseCase
from forge_model.store.domain import expected_columns
from forge_model.store.infrastructure import PostgresIntegrityQueries

from tests.conftest import compiled


@dataclass(frozen=True)
class _File:
    address: str
    version: str
    recorded: str
    actual: str | None


class _Registry:
    def __init__(self, *files):
        self._files = files

    def files(self):
        return self._files


class _Inspector:
    def __init__(self, columns, stamp):
        self._columns, self._stamp = columns, stamp

    def columns(self):
        return self._columns

    def stamp(self):
        return self._stamp


class _Probe:
    def __init__(self, offenders=None):
        self._offenders = offenders or {}

    def offenders(self, sql):
        return next((found for marker, found in self._offenders.items() if marker in sql), ())


def _verify(model, registry, inspector, probe):
    return VerifyStoreUseCase(
        YamlModelSource(model), registry, inspector, PostgresIntegrityQueries(), probe
    ).execute(VerifyStoreInput())


def test_согласованное_хранилище_соответствует_модели(model_root):
    descriptor = compiled(model_root)
    inspector = _Inspector(expected_columns(descriptor), ("1.2.0", descriptor.hash))

    output = _verify(model_root, _Registry(), inspector, _Probe())

    assert (output.outcome, output.summary) == (VERIFIED, ("схема соответствует модели 1.2.0",))


def test_расхождения_названы_как_до_раскладки(model_root):
    descriptor = compiled(model_root)
    columns = dict(expected_columns(descriptor))
    columns["br_revision"] = columns["br_revision"] | {"sneaky"}
    registry = _Registry(
        _File("core/Version20260915142233.sql", "1.2.0", "sha256:a", "sha256:b"),
        _File("core/Version20260915142234.sql", "1.2.0", "sha256:c", None),
    )
    probe = _Probe({"HAVING count(l.id) < 1": ("7",)})

    output = _verify(model_root, registry, _Inspector(columns, None), probe)

    assert output.outcome == DRIFTED
    assert [(item.place, item.message) for item in output.discrepancies] == [
        ("changelog: core/Version20260915142233.sql", "файл выпуска 1.2.0 изменён после выпуска"),
        ("changelog: core/Version20260915142234.sql", "файл выпуска 1.2.0 удалён"),
        ("схема: br_revision.sneaky", "колонка есть в хранилище, но модель её не описывает"),
        ("схема: model_state", "отпечаток модели отсутствует: миграции не применялись"),
        (
            "целостность: realizes.from_cardinality.min",
            "узел без обязательной связи realizes (минимум 1); нарушители: 7",
        ),
    ]


def test_отвергнутая_модель_до_хранилища_не_доходит(model_copy):
    (model_copy / "types" / "br.yaml").write_text("type: br\n", encoding="utf-8")

    class _Unreachable:
        def columns(self):
            raise AssertionError("хранилище не опрашивается")

        stamp = columns

    output = _verify(model_copy, _Registry(), _Unreachable(), _Probe())

    assert output.outcome == REJECTED
    assert output.discrepancies
