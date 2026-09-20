"""Сценарий прогона: чтение, умолчания, ошибки формата и поведение подставных шагов."""

import pytest
from forge_model.errors import ModelError
from forge_model.intent.mock import steps_for
from forge_model.intent.scenario import load_scenario
from forge_model.intent.step import STAGES, Outcome, Stage, StepContext


def write(tmp_path, body):
    path = tmp_path / "scenario.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_full_scenario_is_read(tmp_path):
    """Код намерения, позиции и исходы стадий читаются из файла."""
    scenario = load_scenario(
        write(
            tmp_path,
            "intent: INT-007\n"
            "positions:\n  - поле FR.source_ref\n"
            "stages:\n  reconcile: [rejected, passed]\n",
        )
    )
    assert scenario.code == "INT-007"
    assert scenario.positions == ("поле FR.source_ref",)
    assert scenario.outcome_for(Stage.RECONCILE, 1) is Outcome.REJECTED
    assert scenario.outcome_for(Stage.RECONCILE, 2) is Outcome.PASSED


def test_unnamed_stage_is_passed(tmp_path):
    """Стадия, сценарием не названная, считается пройденной."""
    scenario = load_scenario(write(tmp_path, "intent: INT-001\n"))
    assert all(scenario.outcome_for(stage, 1) is Outcome.PASSED for stage in STAGES)


def test_short_list_repeats_last_outcome(tmp_path):
    """Список короче числа итераций повторяет последнее значение."""
    scenario = load_scenario(write(tmp_path, "intent: INT-001\nstages:\n  reconcile: [rejected]\n"))
    assert scenario.outcome_for(Stage.RECONCILE, 9) is Outcome.REJECTED


def test_single_value_needs_no_list(tmp_path):
    """Одиночный исход допустим без перечня."""
    scenario = load_scenario(write(tmp_path, "intent: INT-001\nstages:\n  validate: rejected\n"))
    assert scenario.outcome_for(Stage.VALIDATE, 1) is Outcome.REJECTED


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("intent: INT-1\n", "не имеет вида"),
        ("intent: [INT-001]\n", "не имеет вида"),
        ("intent: INT-001\npositions: поле\n", "перечнем строк"),
        ("intent: INT-001\nstages:\n  накат: passed\n", "неизвестная стадия"),
        ("intent: INT-001\nstages:\n  apply: готово\n", "неизвестный исход"),
        ("intent: INT-001\nstages:\n  apply: []\n", "перечень исходов пуст"),
        ("intent: INT-001\nlimit: 3\n", "неизвестные ключи"),
        ("- INT-001\n", "отображением ключей"),
    ],
)
def test_broken_scenario_is_rejected(tmp_path, body, message):
    """Каждая ошибка формата отклоняет сценарий и называет причину."""
    with pytest.raises(ModelError, match=message):
        load_scenario(write(tmp_path, body))


def test_missing_file_is_reported(tmp_path):
    """Отсутствующий файл сценария — ошибка процесса, а не падение."""
    with pytest.raises(ModelError, match="файл не найден"):
        load_scenario(tmp_path / "нет.yaml")


def test_mock_steps_cover_every_stage(tmp_path):
    """Подставной набор покрывает все стадии цикла."""
    scenario = load_scenario(write(tmp_path, "intent: INT-001\n"))
    assert set(steps_for(scenario)) == set(STAGES)


def test_mock_step_touches_nothing(tmp_path, monkeypatch):
    """Подставной шаг не читает файлов и не открывает подключений."""
    scenario = load_scenario(write(tmp_path, "intent: INT-001\npositions: [поле FR.code]\n"))

    def forbidden(*args, **kwargs):
        raise AssertionError("подставной шаг обратился к внешнему ресурсу")

    monkeypatch.setattr("pathlib.Path.read_text", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)

    context = StepContext(scenario.code, scenario.positions, 1)
    results = [steps_for(scenario)[stage](context) for stage in STAGES]
    assert all(result.outcome is Outcome.PASSED for result in results)


def test_reconcile_step_carries_verdict_per_position(tmp_path):
    """Подставная сверка выдаёт вердикт на каждую позицию намерения."""
    scenario = load_scenario(
        write(
            tmp_path,
            "intent: INT-001\npositions: [первая, вторая]\nstages:\n  reconcile: rejected\n",
        )
    )
    context = StepContext(scenario.code, scenario.positions, 1)
    result = steps_for(scenario)[Stage.RECONCILE](context)
    assert [verdict.verdict for verdict in result.verdicts] == ["Не исполнено", "Не исполнено"]


def test_demo_scenario_describes_reverse_edge():
    """Пример сценария в репозитории описывает расхождение и последующее совпадение."""
    from pathlib import Path

    scenario = load_scenario(Path("model/intents/scenarios/demo.yaml"))
    assert scenario.outcome_for(Stage.RECONCILE, 1) is Outcome.REJECTED
    assert scenario.outcome_for(Stage.RECONCILE, 2) is Outcome.PASSED
