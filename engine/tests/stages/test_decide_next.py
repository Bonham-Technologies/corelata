import pytest

from corelata.schema import Finding, FindingOut, Verdict
from corelata.stages.audit import decide_next


def f(rule, verdict=Verdict.FAIL, severity="blocking", route_to="writer", iteration=0):
    return Finding(
        **FindingOut(rule_id=rule, verdict=verdict, evidence="e").model_dump(),
        severity=severity,
        route_to=route_to,
        iteration=iteration,
    )


def test_clean_renders():
    assert decide_next([f("a.b.1", Verdict.PASS)], 0, 2) == "rendering"


def test_minor_failures_never_loop():
    assert decide_next([f("a.b.1", severity="minor")], 0, 2) == "rendering"


def test_blocking_routes_to_writer_and_conveyor_only_to_conveyor():
    assert decide_next([f("a.b.1", route_to="conveyor")], 0, 2) == "conveying"
    mixed = [f("a.b.1", route_to="conveyor"), f("a.b.2", route_to="writer")]
    assert decide_next(mixed, 0, 2) == "drafting"


def test_budget_exhausted_renders():
    assert decide_next([f("a.b.1")], 2, 2) == "rendering"
    assert decide_next([f("a.b.1")], 0, 0) == "rendering"


@pytest.mark.parametrize("severity", ["blocking", "major"])
def test_major_and_blocking_loop_while_budget(severity):
    assert decide_next([f("a.b.1", severity=severity)], 1, 2) == "drafting"
