"""Командная строка цикла: разбор аргументов, умолчания, коды возврата и ветви цикла."""

import json

import pytest
from forge_model.cli import CYCLE_OPEN, DEFAULT_RUNS, main
from forge_model.intent.engine import DEFAULT_MAX_ITERATIONS


@pytest.fixture
def scenario_file(tmp_path):
    """Сценарий прогона во временном каталоге."""

    def write(body):
        path = tmp_path / "scenario.yaml"
        path.write_text(f"intent: INT-001\npositions: [поле FR.code]\n{body}", encoding="utf-8")
        return path

    return write


def run(scenario, runs, *extra):
    return main(["intent", "run", "--scenario", str(scenario), "--runs", str(runs), *extra])


def test_clean_cycle_returns_zero(scenario_file, tmp_path):
    """Замкнутый цикл — нулевой код возврата."""
    assert run(scenario_file(""), tmp_path / "runs") == 0


def test_halt_returns_open_cycle_code(scenario_file, tmp_path):
    """Останов — код незамкнутого цикла, а не нулевой."""
    code = run(scenario_file("stages:\n  implement: halted\n"), tmp_path / "runs")
    assert code == CYCLE_OPEN


def test_limit_exhausted_returns_open_cycle_code(scenario_file, tmp_path):
    """Прерывание по лимиту — тот же код незамкнутого цикла."""
    scenario = scenario_file("stages:\n  reconcile: rejected\n")
    assert run(scenario, tmp_path / "runs", "--max-iterations", "2") == CYCLE_OPEN
    assert len(list((tmp_path / "runs" / "INT-001").glob("*.json"))) == 2


def test_process_error_returns_one(tmp_path):
    """Ошибка процесса отличается кодом от незамкнутого цикла."""
    assert main(["intent", "run", "--scenario", str(tmp_path / "нет.yaml")]) == 1


def test_broken_scenario_returns_one(scenario_file, tmp_path):
    """Нечитаемый сценарий — тоже ошибка процесса."""
    scenario = scenario_file("stages:\n  apply: готово\n")
    assert run(scenario, tmp_path / "runs") == 1


def test_reverse_edge_is_walked(scenario_file, tmp_path):
    """Расхождение и последующее совпадение замыкают цикл на второй итерации."""
    scenario = scenario_file("stages:\n  reconcile: [rejected, passed]\n")
    runs = tmp_path / "runs"
    assert run(scenario, runs) == 0
    states = [
        json.loads(path.read_text(encoding="utf-8"))["state"]
        for path in sorted((runs / "INT-001").glob("*.json"))
    ]
    assert states == ["rework", "confirmed"]


def test_defaults_are_declared():
    """Умолчания команды: каталог отчётов и лимит итераций."""
    assert DEFAULT_RUNS.as_posix() == "model/intents/runs"
    assert DEFAULT_MAX_ITERATIONS == 3


def test_scenario_argument_is_required():
    """Без сценария команда не запускается."""
    with pytest.raises(SystemExit):
        main(["intent", "run"])


def test_action_is_required():
    """Подкоманда `intent` без действия не запускается."""
    with pytest.raises(SystemExit):
        main(["intent"])
