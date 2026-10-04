"""Step 6 supervisor: trigger routing and subgraph delegation.

Every test that builds a graph stubs the subgraphs first. A test that lets the
real pipeline run spawns three MCP subprocesses, queries the live database and
tries to generate a PDF; that is what made the suite hang in Step 5.
"""

import pytest

from app.graph import analyst_node, supervisor
from app.graph.state import PipelineState
from app.services import rag


def _stub_subgraphs(monkeypatch, calls: list) -> None:
    """Replace both subgraphs with recorders that cannot touch the outside world."""

    async def stub_pipeline(state):
        calls.append(("pipeline", state.get("trigger")))
        return {"anomaly_result": {"success": True, "anomaly_count": 0}}

    async def stub_analyst(state):
        calls.append(("analyst", state.get("question")))
        return {"analyst": {"success": True, "implemented": True}}

    monkeypatch.setattr(supervisor, "build_pipeline_graph", lambda: stub_pipeline)
    monkeypatch.setattr(supervisor, "build_analyst_graph", lambda: stub_analyst)


@pytest.mark.anyio
async def test_supervisor_routes_data_triggers_to_pipeline():
    out = await supervisor.supervisor_node({"trigger": "new_data"})
    assert out["route"] == "pipeline"
    assert out["route_error"] is None
    assert (await supervisor.supervisor_node({"trigger": "scheduled"}))["route"] == "pipeline"


@pytest.mark.anyio
async def test_supervisor_resolves_the_report_window(monkeypatch):
    # The window is resolved here so the anomaly pass and the report agree; the
    # nodes must not each decide their own period.
    import app.db.database as database

    monkeypatch.setattr(
        database, "get_user_settings", lambda user_id: {"report_months": 3}
    )
    monkeypatch.setattr(
        database, "get_max_transaction_date", lambda user_id: "2026-09-15"
    )

    out = await supervisor.supervisor_node({"trigger": "new_data", "user_id": 4})

    assert out["report_months"] == 3
    assert out["start_date"] == "2026-07-01"
    assert out["end_date"] == "2026-09-15"


@pytest.mark.anyio
async def test_supervisor_falls_back_to_twelve_months(monkeypatch):
    import app.db.database as database
    from app.graph.period import DEFAULT_MONTHS

    monkeypatch.setattr(database, "get_user_settings", lambda user_id: {})
    monkeypatch.setattr(
        database, "get_max_transaction_date", lambda user_id: "2026-09-15"
    )

    out = await supervisor.supervisor_node({"trigger": "scheduled", "user_id": 4})

    assert out["report_months"] == DEFAULT_MONTHS
    assert out["start_date"] == "2025-10-01"


@pytest.mark.anyio
async def test_supervisor_window_survives_a_settings_failure(monkeypatch):
    # A database hiccup must degrade to the default period, not fail the run.
    import app.db.database as database
    from app.graph.period import DEFAULT_MONTHS

    def boom(user_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(database, "get_user_settings", boom)
    monkeypatch.setattr(database, "get_max_transaction_date", boom)

    out = await supervisor.supervisor_node({"trigger": "new_data", "user_id": 4})

    assert out["route"] == "pipeline"
    assert out["route_error"] is None
    assert out["report_months"] == DEFAULT_MONTHS


@pytest.mark.anyio
async def test_supervisor_leaves_chat_without_a_window(monkeypatch):
    # Chat goes to the analyst, which does not report, so no period is needed.
    import app.db.database as database

    def boom(user_id):
        raise AssertionError("chat must not resolve a report window")

    monkeypatch.setattr(database, "get_user_settings", boom)
    monkeypatch.setattr(database, "get_max_transaction_date", boom)

    out = await supervisor.supervisor_node({"trigger": "chat", "user_id": 4})

    assert out == {"route": "analyst", "route_error": None}


@pytest.mark.anyio
async def test_supervisor_routes_chat_to_analyst():
    assert await supervisor.supervisor_node({"trigger": "chat"}) == {
        "route": "analyst",
        "route_error": None,
    }


@pytest.mark.anyio
async def test_supervisor_rejects_unknown_trigger():
    result = await supervisor.supervisor_node({"trigger": "nonsense"})

    assert result["route"] is None
    assert "nonsense" in result["route_error"]


@pytest.mark.anyio
async def test_supervisor_rejects_missing_trigger():
    result = await supervisor.supervisor_node({})

    assert result["route"] is None
    assert result["route_error"]


@pytest.mark.anyio
async def test_route_after_trigger_defaults_to_end():
    assert supervisor.route_after_trigger({"route": "pipeline"}) == "pipeline"
    assert supervisor.route_after_trigger({"route": "analyst"}) == "analyst"
    assert supervisor.route_after_trigger({}) == "end"
    assert supervisor.route_after_trigger({"route": None}) == "end"


def test_routes_map_covers_every_documented_trigger():
    assert supervisor.ROUTES == {
        "new_data": "pipeline",
        "scheduled": "pipeline",
        "chat": "analyst",
    }


@pytest.mark.anyio
async def test_graph_delegates_to_pipeline_subgraph(monkeypatch):
    calls: list = []
    _stub_subgraphs(monkeypatch, calls)

    graph = supervisor.build_graph()
    result = await graph.ainvoke({"user_id": 1, "trigger": "new_data"})

    assert calls == [("pipeline", "new_data")]
    assert result["route"] == "pipeline"
    assert result["anomaly_result"] == {"success": True, "anomaly_count": 0}
    assert "analyst" not in result, "chat subgraph must not run for a data trigger"


@pytest.mark.anyio
async def test_graph_delegates_chat_to_analyst_subgraph(monkeypatch):
    calls: list = []
    _stub_subgraphs(monkeypatch, calls)

    graph = supervisor.build_graph()
    result = await graph.ainvoke(
        {"user_id": 1, "trigger": "chat", "question": "why did spend spike?"}
    )

    assert calls == [("analyst", "why did spend spike?")]
    assert result["analyst"] == {"success": True, "implemented": True}
    assert "anomaly_result" not in result, "chat must not run the reporting pipeline"


@pytest.mark.anyio
async def test_graph_stops_on_unknown_trigger(monkeypatch):
    calls: list = []
    _stub_subgraphs(monkeypatch, calls)

    graph = supervisor.build_graph()
    result = await graph.ainvoke({"user_id": 1, "trigger": "bogus"})

    assert calls == [], "an unknown trigger must not enter a subgraph"
    assert result["route"] is None
    assert result["route_error"]


@pytest.mark.anyio
async def test_graph_does_not_dispatch_on_trigger_alone(monkeypatch):
    """A data trigger must not itself imply an email or a calendar event.

    Dispatch is driven by state, so routing a trigger with no report_email and no
    meeting leaves the dispatch fields untouched.
    """
    calls: list = []
    _stub_subgraphs(monkeypatch, calls)

    graph = supervisor.build_graph()
    result = await graph.ainvoke({"user_id": 1, "trigger": "scheduled"})

    assert calls == [("pipeline", "scheduled")]
    assert "report_email" not in result
    assert "meeting" not in result


@pytest.mark.anyio
async def test_analyst_node_answers_through_the_rag_service(monkeypatch):
    captured = {}

    async def fake_answer(user_id, question):
        captured["user_id"] = user_id
        captured["question"] = question
        return "Marketing spend was $1200."

    monkeypatch.setattr(rag, "answer_with_rag", fake_answer)

    result = await analyst_node.analyst_node(
        {"user_id": 4, "trigger": "chat", "question": "why did marketing spend spike?"}
    )

    assert result["analyst"]["success"] is True
    assert result["analyst"]["answer"] == "Marketing spend was $1200."
    assert captured == {"user_id": 4, "question": "why did marketing spend spike?"}


@pytest.mark.anyio
async def test_analyst_node_validates_input():
    assert (await analyst_node.analyst_node({"question": "why?"}))["analyst"]["error"]
    assert (await analyst_node.analyst_node({"user_id": 1}))["analyst"]["error"]
    assert (
        await analyst_node.analyst_node({"user_id": 1, "question": "   "})
    )["analyst"]["error"]


def test_analyst_subgraph_contains_only_the_analyst_node():
    """The analyst answers a question; it must not re-sync a source."""
    assert set(analyst_node.graph.get_graph().nodes) == {"__start__", "analyst", "__end__"}


def test_supervisor_graph_compiles():
    assert supervisor.graph is not None


def test_package_exposes_both_graphs():
    from app import graph as graph_pkg

    assert graph_pkg.graph is supervisor.graph
    assert graph_pkg.pipeline_graph is not supervisor.graph


def test_state_schema_carries_supervisor_fields():
    keys = set(PipelineState.__annotations__)
    assert {"route", "route_error", "question", "analyst"} <= keys
