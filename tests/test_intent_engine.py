"""Движок цикла: порядок стадий, итерации, лимит, отчёты, подмена шага."""

import json

import pytest
from forge_model.errors import ModelError
from forge_model.intent.engine import DEFAULT_MAX_ITERATIONS, run_cycle
from forge_model.intent.mock import steps_for
from forge_model.intent.scenario import Scenario
from forge_model.intent.state import State
from forge_model.intent.step import STAGES, Outcome, Stage, StepResult, Steps


def scenario(**stages):
    """Сценарий с позициями и заданными исходами стадий."""
    outcomes = {
        Stage(name): tuple(Outcome(value) for value in values) for name, values in stages.items()
    }
    return Scenario(code="INT-001", positions=("поле FR.code",), outcomes=outcomes)


def run(tmp_path, spec, steps=None, **options):
    return run_cycle(spec, steps or steps_for(spec), runs_dir=tmp_path, **options)


def reports_of(tmp_path, code="INT-001"):
    return sorted((tmp_path / code).glob("*.json"))


def payload(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_clean_pass_confirms_intent(tmp_path):
    """Все стадии пройдены — намерение подтверждено, цикл замкнут."""
    outcome = run(tmp_path, scenario())
    assert outcome.state is State.CONFIRMED
    assert outcome.closed
    assert outcome.iterations == 0


def test_stage_order_is_fixed(tmp_path):
    """Стадии выполняются в порядке схемы цикла."""
    run(tmp_path, scenario())
    stages = [entry["stage"] for entry in payload(reports_of(tmp_path)[0])["stages"]]
    assert stages == [stage.value for stage in STAGES]


def test_rejection_stops_remaining_stages(tmp_path):
    """После отклонения последующие стадии итерации не выполняются."""
    run(tmp_path, scenario(validate=["rejected"]), max_iterations=1)
    stages = [entry["stage"] for entry in payload(reports_of(tmp_path)[0])["stages"]]
    assert stages == ["intent", "validate"]


def test_halt_stops_remaining_stages(tmp_path):
    """Останов тоже прерывает последовательность стадий."""
    outcome = run(tmp_path, scenario(implement=["halted"]))
    stages = [entry["stage"] for entry in payload(reports_of(tmp_path)[0])["stages"]]
    assert stages == ["intent", "validate", "implement"]
    assert outcome.state is State.VALIDATED
    assert not outcome.closed


def test_rework_opens_next_iteration(tmp_path):
    """Расхождение на первой итерации и совпадение на второй замыкают цикл."""
    outcome = run(tmp_path, scenario(reconcile=["rejected", "passed"]))
    assert outcome.state is State.CONFIRMED
    assert outcome.iterations == 1
    assert len(reports_of(tmp_path)) == 2


def test_limit_aborts_cycle(tmp_path):
    """Исчерпание лимита прерывает цикл и не помечает намерение подтверждённым."""
    outcome = run(tmp_path, scenario(reconcile=["rejected"]), max_iterations=3)
    assert outcome.state is State.ABORTED
    assert outcome.iterations == 3
    assert not outcome.closed
    assert [path.name for path in reports_of(tmp_path)] == ["1.json", "2.json", "3.json"]


def test_halt_does_not_count_iteration(tmp_path):
    """Останов итерацию не засчитывает: повторный прогон продолжает ту же."""
    first = run(tmp_path, scenario(implement=["halted"]))
    second = run(tmp_path, scenario(implement=["halted"]))
    assert first.iterations == second.iterations == 0
    assert [path.name for path in reports_of(tmp_path)] == ["1.json"]


def test_confirmed_rerun_does_not_count_iteration(tmp_path):
    """Повторный прогон подтверждённого намерения номер итерации не двигает."""
    run(tmp_path, scenario())
    outcome = run(tmp_path, scenario())
    assert outcome.state is State.CONFIRMED
    assert [path.name for path in reports_of(tmp_path)] == ["1.json"]


def test_default_limit_is_three(tmp_path):
    """Лимит по умолчанию — три итерации."""
    assert DEFAULT_MAX_ITERATIONS == 3
    outcome = run(tmp_path, scenario(reconcile=["rejected"]))
    assert outcome.iterations == 3


def test_limit_below_one_is_process_error(tmp_path):
    """Лимит меньше одной итерации — ошибка процесса."""
    with pytest.raises(ModelError, match="меньше одной"):
        run(tmp_path, scenario(), max_iterations=0)


def test_incomplete_set_runs_no_stage(tmp_path):
    """Неполный набор шагов отвергается до первой стадии, отчётов не появляется."""
    spec = scenario()
    partial: Steps = {
        stage: step for stage, step in steps_for(spec).items() if stage is not Stage.RECONCILE
    }
    with pytest.raises(ModelError, match="reconcile"):
        run_cycle(spec, partial, runs_dir=tmp_path)
    assert not tmp_path.exists() or not reports_of(tmp_path)


def test_report_carries_every_field(tmp_path):
    """Отчёт содержит намерение, итерацию, состояние, исходы, вердикты и причину."""
    run(tmp_path, scenario(reconcile=["rejected"]), max_iterations=1)
    stored = payload(reports_of(tmp_path)[0])
    assert stored["intent"] == "INT-001"
    assert stored["iteration"] == 1
    assert stored["state"] == "aborted"
    assert stored["state_title"] == "Прервано"
    assert stored["verdicts"] == [{"position": "поле FR.code", "verdict": "Не исполнено"}]
    assert "лимит итераций исчерпан" in stored["reason"]


def test_earlier_reports_survive(tmp_path):
    """Отчёты предыдущих итераций новыми не затираются."""
    run(tmp_path, scenario(reconcile=["rejected", "rejected", "passed"]))
    assert [payload(path)["iteration"] for path in reports_of(tmp_path)] == [1, 2, 3]


def test_report_written_on_process_error(tmp_path):
    """Отчёт пишется и при ошибке процесса, называя стадию."""
    spec = scenario()
    steps = dict(steps_for(spec))
    steps[Stage.GENERATE] = lambda context: StepResult(outcome=Outcome.FAILED, message="нет места")
    with pytest.raises(ModelError, match="нет места"):
        run_cycle(spec, steps, runs_dir=tmp_path)
    stored = payload(reports_of(tmp_path)[0])
    assert "преобразование в миграцию" in stored["reason"]


def test_numbering_continues_from_stored_reports(tmp_path):
    """Прогон на непустом каталоге продолжает нумерацию итераций."""
    run(tmp_path, scenario(reconcile=["rejected"]), max_iterations=2)
    run(tmp_path, scenario(reconcile=["passed"]), max_iterations=5)
    assert [path.name for path in reports_of(tmp_path)] == ["1.json", "2.json", "3.json"]


def test_step_replacement_leaves_engine_intact(tmp_path):
    """Предметный шаг встаёт на место подставного, движок не меняется."""
    spec = scenario()
    calls: list[int] = []

    def real_apply(context):
        """Шаг, ведущий себя как предметный: накат ему недоступен, он просит его снаружи."""
        calls.append(context.iteration)
        return StepResult(outcome=Outcome.HALTED, message="накат выполняется целью make")

    steps = dict(steps_for(spec))
    steps[Stage.APPLY] = real_apply
    outcome = run_cycle(spec, steps, runs_dir=tmp_path)

    assert calls == [1]
    assert outcome.state is State.RELEASED
    stages = [entry["stage"] for entry in payload(reports_of(tmp_path)[0])["stages"]]
    assert stages == ["intent", "validate", "implement", "generate", "apply"]


def test_run_is_reproducible(tmp_path):
    """Два прогона одного сценария на пустом каталоге дают одинаковый результат."""
    spec = scenario(reconcile=["rejected", "passed"])
    first = run(tmp_path / "первый", spec)
    second = run(tmp_path / "второй", spec)
    assert (first.state, first.iterations) == (second.state, second.iterations)
    assert (
        payload(reports_of(tmp_path / "первый")[0])["stages"]
        == (payload(reports_of(tmp_path / "второй")[0])["stages"])
    )
