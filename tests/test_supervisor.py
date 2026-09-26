"""Step 6 supervisor: trigger routing and subgraph delegation.

Every test that builds a graph stubs the subgraphs first. A test that lets the
real pipeline run spawns three MCP subprocesses, queries the live database and
tries to generate a PDF; that is what made the suite hang in Step 5.
"""

import pytest

from app.graph import analyst_node, supervisor
from app.graph.state import PipelineState


def _stub_subgraphs(monkeypatch, calls: list) -> None:
    """Replace both subgraphs with recorders that cannot touch the outside world."""

    async def stub_pipeline(state):
        calls.append(("pipeline", state.get("trigger")))
        return {"sync_result": {"success": True, "record_count": 0}}

    async def stub_analyst(state):
        calls.append(("analyst", state.get("question")))
        return {"analyst": {"success": True, "implemented": True}}

    monkeypatch.setattr(supervisor, "build_pipeline_graph", lambda: stub_pipeline)
    monkeypatch.setattr(supervisor, "build_analyst_graph", lambda: stub_analyst)


@pytest.mark.anyio
async def test_supervisor_routes_data_triggers_to_pipeline():
    assert await supervisor.supervisor_node({"trigger": "new_data"}) == {
        "route": "pipeline",
        "route_error": None,
    }
    assert (await supervisor.supervisor_node({"trigger": "scheduled"}))["route"] == "pipeline"


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
    assert result["sync_result"] == {"success": True, "record_count": 0}
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
    assert "sync_result" not in result, "chat must not trigger ingestion"


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
async def test_analyst_placeholder_reports_not_implemented():
    result = await analyst_node.analyst_node({"user_id": 1, "question": "why?"})

    assert result["analyst"]["success"] is True
    assert result["analyst"]["implemented"] is False
    assert result["analyst"]["question"] == "why?"
    assert "Step 7" in result["analyst"]["detail"]


@pytest.mark.anyio
async def test_analyst_placeholder_validates_input():
    assert (await analyst_node.analyst_node({"question": "why?"}))["analyst"]["error"]
    assert (await analyst_node.analyst_node({"user_id": 1}))["analyst"]["error"]
    assert (
        await analyst_node.analyst_node({"user_id": 1, "question": "   "})
    )["analyst"]["error"]


def test_supervisor_graph_compiles():
    assert supervisor.graph is not None


def test_package_exposes_both_graphs():
    from app import graph as graph_pkg

    assert graph_pkg.graph is supervisor.graph
    assert graph_pkg.pipeline_graph is not supervisor.graph


def test_state_schema_carries_supervisor_fields():
    keys = set(PipelineState.__annotations__)
    assert {"route", "route_error", "question", "analyst"} <= keys
