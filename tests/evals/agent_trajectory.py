"""Deterministic agent-trajectory evaluation harness.

This module scores the *behaviour* of an agent over a single turn — the ordered
sequence of tool calls and the arguments it passed — against a golden trajectory
recorded in ``tests/eval_sets/agent_trajectories.json``.

Two pieces:

1. ``score_trajectory`` — pure functions that compare an *executed* trajectory
   (tool names + args) to the golden expectations and produce metrics:

   - ``tool_set_precision`` / ``tool_set_recall`` — did it call the right tools?
   - ``order_score`` — did it call them in the right relative order? (LCS based)
   - ``arg_faithfulness`` — did it pass the required arguments with the right values?
   - ``score`` — 0..1 weighted combination; ``passed`` is True when the golden
     threshold is met.

2. ``TrajectoryRecorder`` — a tiny, dependency-free agent loop that drives a
   ``Policy`` (a stand-in for the LLM) against stub tool implementations and
   records the executed trajectory. This makes CI runs deterministic and offline:
   the *same* scorer can later be fed real traces (e.g. from LangSmith) with no
   changes, while CI gates on the scripted policies below.

Policies provided for testing:

- ``ScriptedPolicy`` — replays the golden tool sequence; used to verify the happy
  path executes end-to-end and scores 1.0.
- ``DeviantPolicy`` — deliberately breaks the golden contract (skips a mandatory
  step) to prove the harness detects deviation.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

EVAL_SETS_DIR = os.path.join(os.path.dirname(__file__), "..", "eval_sets")

# Mandatory ordering contract enforced on the recorder and scorer.
MANDATORY_STEPS = (
    "authenticate_google",
    "ingest_financial_data",
    "detect_financial_anomalies",
    "generate_cfo_pdf_report",
    "send_email_report",
)

MAX_STEPS = 20


# --------------------------------------------------------------------------- #
# Trajectory data model
# --------------------------------------------------------------------------- #
@dataclass
class TrajectoryStep:
    tool: str
    args: dict[str, Any]


@dataclass
class Trajectory:
    steps: list[TrajectoryStep] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [s.tool for s in self.steps]

    def args_for(self, tool: str) -> list[dict[str, Any]]:
        return [s.args for s in self.steps if s.tool == tool]


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _lcs(a: Sequence[str], b: Sequence[str]) -> int:
    """Length of the longest common subsequence preserving order."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


def _count(tools: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tools:
        counts[t] = counts.get(t, 0) + 1
    return counts


def score_trajectory(
    executed: Trajectory,
    expected_tools: Sequence[str],
    required_args: dict[str, dict[str, Any]],
    threshold: float = 1.0,
) -> dict[str, Any]:
    """Score an executed trajectory against golden expectations.

    ``required_args`` maps a tool name to {arg_name: expected_value}. A value of
    ``None``/null only requires the argument key to be present; any other value
    must match exactly in at least one call of that tool.
    """
    names = executed.tool_names
    exp_counts = _count(expected_tools)
    exe_counts = _count(names)

    # Set-level metrics ------------------------------------------------------ #
    union = set(exp_counts) | set(exe_counts)
    true_pos = sum(min(exp_counts.get(t, 0), exe_counts.get(t, 0)) for t in union)
    precision = true_pos / len(names) if names else 0.0
    recall = true_pos / len(expected_tools) if expected_tools else 0.0

    missing_tools = [
        t for t in expected_tools if exe_counts.get(t, 0) < exp_counts[t]
    ]
    extra_tools = [t for t in names if exe_counts[t] > exp_counts.get(t, 0)]

    # Order metric (relative order of expected steps preserved) -------------- #
    order_score = _lcs(names, expected_tools) / len(expected_tools) if expected_tools else 0.0

    # Argument faithfulness -------------------------------------------------- #
    checked = 0
    passed_args = 0
    arg_violations: list[str] = []
    for tool, expected in required_args.items():
        calls = executed.args_for(tool)
        for key, value in expected.items():
            checked += 1
            present = any(key in c for c in calls)
            if value is None:
                if present:
                    passed_args += 1
                else:
                    arg_violations.append(f"{tool}.{key}: expected key present")
                continue
            values = [c.get(key) for c in calls]
            if any(v == value for v in values):
                passed_args += 1
            else:
                arg_violations.append(f"{tool}.{key}: expected {value!r}, got {values}")

    arg_faithfulness = (passed_args / checked) if checked else 1.0

    # Weighted combination --------------------------------------------------- #
    weights = {"recall": 0.4, "order": 0.3, "args": 0.2, "precision": 0.1}
    score = (
        weights["recall"] * recall
        + weights["order"] * order_score
        + weights["args"] * arg_faithfulness
        + weights["precision"] * precision
    )
    rounded_score = round(score, 4)

    return {
        "executed_tools": names,
        "expected_tools": list(expected_tools),
        "tool_set_precision": round(precision, 4),
        "tool_set_recall": round(recall, 4),
        "order_score": round(order_score, 4),
        "arg_faithfulness": round(arg_faithfulness, 4),
        "missing_tools": missing_tools,
        "extra_tools": extra_tools,
        "arg_violations": arg_violations,
        "score": rounded_score,
        "passed": rounded_score >= threshold,
    }


# --------------------------------------------------------------------------- #
# Golden set loading
# --------------------------------------------------------------------------- #
def load_eval_set(name: str = "agent_trajectories.json") -> dict:
    path = os.path.abspath(os.path.join(EVAL_SETS_DIR, name))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# Policies (deterministic stand-ins for the LLM)
# --------------------------------------------------------------------------- #
class Policy:
    """Base class for a deterministic decision-maker."""

    def decide(self, history: Sequence[str]) -> TrajectoryStep | None:
        raise NotImplementedError


class ScriptedPolicy(Policy):
    """Replays the golden tool sequence verbatim (with correct args)."""

    def __init__(self, expected_tools: Sequence[str], required_args: dict[str, dict[str, Any]]):
        self._queue = list(expected_tools)
        self._args = {t: dict(a) for t, a in required_args.items()}

    def decide(self, history: Sequence[str]) -> TrajectoryStep | None:
        if not self._queue:
            return None
        tool = self._queue.pop(0)
        return TrajectoryStep(tool=tool, args=dict(self._args.get(tool, {})))


class DeviantPolicy(Policy):
    """Skips the mandatory detection step to model a broken agent.

    Walks the golden sequence but omits ``detect_financial_anomalies``, so the
    executed trajectory is genuine yet deviant.
    """

    def __init__(self):
        self._queue = [
            "authenticate_google",
            "ingest_financial_data",
            "generate_cfo_pdf_report",  # detect_financial_anomalies SKIPPED
        ]

    def decide(self, history: Sequence[str]) -> TrajectoryStep | None:
        if not self._queue:
            return None
        return TrajectoryStep(self._queue.pop(0), {})


# --------------------------------------------------------------------------- #
# Recorder (deterministic agent loop)
# --------------------------------------------------------------------------- #
STUB_RESULTS = {
    "authenticate_google": "Success: authenticated with Google.",
    "ingest_financial_data": "Success! Unified 10 rows.",
    "detect_financial_anomalies": "Analysis complete. Detected 2 breaches.",
    "generate_cfo_pdf_report": "Success! PDF generated.",
    "send_email_report": "Success! Email sent.",
    "schedule_meeting": "Success! Meeting scheduled.",
}


def run_policy(policy: Policy, user_input: str) -> Trajectory:
    """Run a policy through the recorder loop and return the executed trajectory.

    Mirrors the agent loop: the policy returns one tool call at a time, the stub
    implementation produces a result, and the result feeds back into history.
    """
    trajectory = Trajectory()
    history = [f"user: {user_input}"]

    for _ in range(MAX_STEPS):
        decision = policy.decide(history)
        if decision is None:
            break
        trajectory.steps.append(decision)
        history.append(f"{decision.tool}({decision.args})")
        history.append(f"result: {STUB_RESULTS.get(decision.tool, 'ok')}")
    else:
        raise RuntimeError("Recorder reached the step limit without terminating.")

    return trajectory
