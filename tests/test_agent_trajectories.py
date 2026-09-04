"""Tests for the deterministic agent-trajectory evaluation harness.

Verifies that (a) the ScriptedPolicy happy path reproduces every golden trajectory
and scores perfect, and (b) that the scorer genuinely *detects* deviation — a
skipped mandatory step, or a wrong argument value — so the harness is a real gate.
"""

import pytest

from tests.evals.agent_trajectory import (
    DeviantPolicy,
    ScriptedPolicy,
    Trajectory,
    TrajectoryStep,
    load_eval_set,
    run_policy,
    score_trajectory,
)

GOLDEN_THRESHOLD = 1.0


def _golden_cases():
    return load_eval_set()["cases"]


def test_eval_set_schema_is_valid():
    data = load_eval_set()
    assert data["version"] == 1
    assert len(data["cases"]) >= 2
    for case in data["cases"]:
        assert case["id"]
        assert case["user_input"]
        assert isinstance(case["expected_tools"], list) and case["expected_tools"]
        assert isinstance(case.get("required_args"), dict)


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c["id"])
def test_golden_trajectory_passes_unanimously(case):
    policy = ScriptedPolicy(case["expected_tools"], case["required_args"])
    executed = run_policy(policy, case["user_input"])

    assert executed.tool_names == case["expected_tools"]

    result = score_trajectory(
        executed,
        case["expected_tools"],
        case["required_args"],
        threshold=GOLDEN_THRESHOLD,
    )
    assert result["passed"], result
    assert result["score"] == 1.0
    assert result["missing_tools"] == []
    assert result["extra_tools"] == []
    assert result["arg_violations"] == []


def test_deviant_policy_is_caught():
    """A policy that skips the mandatory detection step must fail the gate."""
    policy = DeviantPolicy()
    executed = run_policy(policy, "USER_ID: 2 run the analysis")

    result = score_trajectory(
        executed,
        ["authenticate_google", "ingest_financial_data", "detect_financial_anomalies",
         "generate_cfo_pdf_report", "send_email_report"],
        {},
        threshold=GOLDEN_THRESHOLD,
    )
    assert result["passed"] is False
    assert "detect_financial_anomalies" in result["missing_tools"]
    assert result["order_score"] < 1.0


def test_wrong_argument_value_is_flagged():
    executed = Trajectory(
        steps=[
            TrajectoryStep("send_email_report", {"to_email": "wrong@mail.com"}),
        ]
    )
    result = score_trajectory(
        executed,
        ["send_email_report"],
        {"send_email_report": {"to_email": "cfo@acme.com"}},
        threshold=GOLDEN_THRESHOLD,
    )
    assert result["passed"] is False
    assert any("to_email" in v for v in result["arg_violations"])


def test_missing_required_key_is_flagged():
    """A required arg that is entirely absent must be caught."""
    executed = Trajectory(
        steps=[TrajectoryStep("send_email_report", {"user_id": 5})]
    )
    result = score_trajectory(
        executed,
        ["send_email_report"],
        {"send_email_report": {"to_email": "cfo@acme.com"}},
        threshold=GOLDEN_THRESHOLD,
    )
    assert result["passed"] is False
    assert any("to_email" in v for v in result["arg_violations"])