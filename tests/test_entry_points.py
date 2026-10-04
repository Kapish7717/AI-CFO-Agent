"""The graph-backed entry points.

``/api/agent/run`` used to drive the autonomous ReAct agent and both chat
endpoints used to call the RAG service directly, so the scheduler and the UI ran
two different pipelines. Every entry point now invokes the supervisor graph, and
these tests pin that: the state each route hands the supervisor, the shape the
UI reads back, and the custom-stream path that lets a graph node feed SSE.
"""

import json
import pathlib
import re

import pytest

from app.api import agent as agent_api
from app.api import chat as chat_api
from app.graph import analyst_node, pipeline


class _FakeGraph:
    """Records the state a route handed the supervisor, then replays a result."""

    def __init__(self, result=None, chunks=("Spend ", "spiked.")):
        self.result = result if result is not None else {}
        self.chunks = chunks
        self.states: list[dict] = []
        self.stream_modes: list = []

    async def ainvoke(self, state):
        self.states.append(state)
        return self.result

    async def astream(self, state, stream_mode=None):
        self.states.append(state)
        self.stream_modes.append(stream_mode)
        for chunk in self.chunks:
            yield "custom", chunk
        answer = "".join(self.chunks)
        yield "values", {"analyst": {"success": True, "answer": answer}}


@pytest.fixture
def stub_graph(monkeypatch):
    """Install a recording graph as the supervisor's compiled entry point."""
    import app.graph.supervisor as supervisor

    def _install(result=None, **kwargs):
        graph = _FakeGraph(result, **kwargs)
        monkeypatch.setattr(supervisor, "graph", graph)
        return graph

    return _install


@pytest.fixture
def settings(monkeypatch):
    """Replace the per-user settings row every one of these routes reads."""
    import app.db.database as database

    def _set(row):
        monkeypatch.setattr(database, "get_user_settings", lambda user_id: row)
        return row

    return _set


@pytest.fixture(autouse=True)
def no_chat_writes(monkeypatch):
    """Chat persists the exchange; the tests do not need a database for that."""
    monkeypatch.setattr(chat_api, "save_user_chat_message", lambda *a, **k: None)


# --------------------------------------------------------------------------- #
# /api/agent/run
# --------------------------------------------------------------------------- #

_REPORT = {
    "success": True,
    "generated": True,
    "delivered": True,
    "recipient": "cfo@company.com",
    "anomaly_count": 2,
    "steps": [
        {"step": "generate_cfo_pdf_report", "success": True},
        {"step": "send_email_report", "success": True},
    ],
}


@pytest.mark.anyio
async def test_agent_run_drives_the_supervisor_graph(stub_graph, settings):
    settings({"expense_file_path": "uploads/expense.csv"})
    graph = stub_graph({"route": "pipeline", "report": _REPORT})

    result = await agent_api.agent_run(agent_api.AgentRunRequest(), user_id=7)

    assert graph.states[0]["user_id"] == 7
    assert graph.states[0]["trigger"] == "new_data"
    assert result["success"] is True
    assert "cfo@company.com" in result["message"]


@pytest.mark.anyio
async def test_agent_run_forces_a_report_on_a_manual_request(stub_graph, settings):
    # Nobody pressed a button for a scheduled run, so a clean period stays quiet.
    settings({"expense_file_path": "uploads/expense.csv"})
    graph = stub_graph({"route": "pipeline", "report": _REPORT})

    await agent_api.agent_run(agent_api.AgentRunRequest(), user_id=7)

    assert graph.states[0]["force_report"] is True


@pytest.mark.anyio
async def test_agent_run_prefers_the_requested_recipient(stub_graph, settings):
    settings({"expense_file_path": "uploads/expense.csv", "report_email": "saved@company.com"})
    graph = stub_graph({"route": "pipeline", "report": _REPORT})

    await agent_api.agent_run(agent_api.AgentRunRequest(to_email="override@company.com"), user_id=7)

    assert graph.states[0]["report_email"] == "override@company.com"


@pytest.mark.anyio
async def test_agent_run_falls_back_to_the_saved_recipient(stub_graph, settings):
    settings({"expense_file_path": "uploads/expense.csv", "report_email": "saved@company.com"})
    graph = stub_graph({"route": "pipeline", "report": _REPORT})

    await agent_api.agent_run(agent_api.AgentRunRequest(to_email="   "), user_id=7)

    assert graph.states[0]["report_email"] == "saved@company.com"


@pytest.mark.anyio
async def test_agent_run_accepts_a_stripe_only_user(stub_graph, settings):
    settings({"stripe_secret_key": "sk_live_x"})
    graph = stub_graph({"route": "pipeline", "report": _REPORT})

    result = await agent_api.agent_run(agent_api.AgentRunRequest(), user_id=7)

    assert graph.states, "a Stripe-connected user must still be able to run"
    assert result["success"] is True


@pytest.mark.anyio
async def test_agent_run_short_circuits_without_any_data(stub_graph, settings):
    settings({})
    graph = stub_graph({"route": "pipeline", "report": _REPORT})

    result = await agent_api.agent_run(agent_api.AgentRunRequest(), user_id=7)

    assert result["success"] is False
    assert graph.states == [], "no data means no reason to run the graph"


@pytest.mark.anyio
async def test_agent_run_reports_a_failed_pdf(stub_graph, settings):
    settings({"expense_file_path": "uploads/expense.csv"})
    stub_graph(
        {
            "route": "pipeline",
            "anomaly_result": {"success": True, "anomaly_count": 1, "rows_analyzed": 10},
            "report": {"success": False, "error": "rendering blew up", "steps": []},
        }
    )

    result = await agent_api.agent_run(agent_api.AgentRunRequest(), user_id=7)

    assert result["success"] is False
    assert "rendering blew up" in result["message"]


@pytest.mark.anyio
async def test_agent_run_reports_a_failed_analysis(stub_graph, settings):
    settings({"expense_file_path": "uploads/expense.csv"})
    stub_graph(
        {
            "route": "pipeline",
            "anomaly_result": {"success": False, "error": "analysis blew up"},
        }
    )

    result = await agent_api.agent_run(agent_api.AgentRunRequest(), user_id=7)

    assert result["success"] is False
    assert "analysis blew up" in result["message"]


@pytest.mark.anyio
async def test_agent_run_survives_a_graph_crash(stub_graph, settings):
    settings({"expense_file_path": "uploads/expense.csv"})

    import app.graph.supervisor as supervisor

    class _Boom:
        async def ainvoke(self, state):
            raise RuntimeError("mcp wedged")

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(supervisor, "graph", _Boom())
        result = await agent_api.agent_run(agent_api.AgentRunRequest(), user_id=7)

    assert result["success"] is False
    assert "mcp wedged" in result["message"]


def test_agent_run_steps_describe_every_stage():
    steps = agent_api._steps(
        {
            "anomaly_result": {"success": True, "anomaly_count": 3, "rows_analyzed": 40},
            "report": {
                "steps": [
                    {"step": "generate_cfo_pdf_report", "success": True},
                    {"step": "send_email_report", "error": "gmail rejected it"},
                    {"step": "schedule_budget_review", "skipped": "no attendee"},
                ]
            },
        }
    )

    assert [s["step"] for s in steps] == [
        "anomaly_detect",
        "generate_cfo_pdf_report",
        "send_email_report",
        "schedule_budget_review",
    ]
    assert "3 anomalies" in steps[0]["message"]
    assert steps[1]["message"] == "ok"
    assert "gmail rejected it" in steps[2]["message"]
    assert "no attendee" in steps[3]["message"]


def test_a_clean_run_is_a_success():
    ok, message = agent_api._summarise(
        {"report": {"success": True, "generated": True, "delivered": False, "anomaly_count": 0, "steps": []}}
    )
    assert ok is True
    assert "no report email is configured" in message


# --------------------------------------------------------------------------- #
# force_report routing
# --------------------------------------------------------------------------- #


def test_a_manual_run_reports_even_with_nothing_flagged():
    state = {"anomaly_result": {"success": True, "anomaly_count": 0}, "force_report": True}
    assert pipeline.route_after_anomaly(state) == "reporting"


def test_a_scheduled_run_stays_quiet_when_nothing_is_flagged():
    state = {"anomaly_result": {"success": True, "anomaly_count": 0}}
    assert pipeline.route_after_anomaly(state) == "end"


def test_a_forced_run_still_reports_when_analysis_failed():
    # A forced run is an explicit request for a report; the failure is recorded
    # in state either way, and hiding it would look like the run did nothing.
    state = {"anomaly_result": {"success": False, "error": "boom"}, "force_report": True}
    assert pipeline.route_after_anomaly(state) == "reporting"


def test_a_flagged_run_reports_without_being_forced():
    state = {"anomaly_result": {"success": True, "anomaly_count": 4}}
    assert pipeline.route_after_anomaly(state) == "reporting"


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_chat_routes_through_the_supervisor(stub_graph):
    graph = stub_graph({"analyst": {"success": True, "answer": "Marketing was $1200."}})

    result = await chat_api.chat_data_query(chat_api.DataQueryRequest(question="why?"), user_id=7)

    assert graph.states[0] == {"user_id": 7, "trigger": "chat", "question": "why?"}
    assert result == {"answer": "Marketing was $1200.", "success": True}


@pytest.mark.anyio
async def test_chat_rejects_a_blank_question_without_touching_the_graph(stub_graph):
    graph = stub_graph({"analyst": {"success": True, "answer": "should not be used"}})

    result = await chat_api.chat_data_query(chat_api.DataQueryRequest(question="   "), user_id=7)

    assert result["success"] is True
    assert graph.states == []


@pytest.mark.anyio
async def test_chat_streams_chunks_then_a_done_frame(stub_graph):
    graph = stub_graph(chunks=("Spend ", "spiked."))

    response = await chat_api.chat_data_query_stream(
        chat_api.DataQueryRequest(question="why did spend spike?"), user_id=7
    )
    frames = [json.loads(line.removeprefix("data: ")) async for line in response.body_iterator]

    assert graph.states[0]["trigger"] == "chat"
    assert graph.stream_modes[0] == ["custom", "values"]
    assert "".join(f["chunk"] for f in frames if "chunk" in f) == "Spend spiked."
    assert frames[-1] == {"done": True, "answer": "Spend spiked."}


@pytest.mark.anyio
async def test_chat_stream_turns_a_crash_into_an_answer(stub_graph):
    import app.graph.supervisor as supervisor

    class _Boom:
        async def astream(self, state, stream_mode=None):
            yield "custom", "partial"
            raise RuntimeError("supabase-mcp died")

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(supervisor, "graph", _Boom())
        response = await chat_api.chat_data_query_stream(
            chat_api.DataQueryRequest(question="why?"), user_id=7
        )
        frames = [json.loads(line.removeprefix("data: ")) async for line in response.body_iterator]

    assert any("supabase-mcp died" in f.get("chunk", "") for f in frames)
    assert frames[-1]["done"] is True


# --------------------------------------------------------------------------- #
# the analyst node as a streaming graph node
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_analyst_node_writes_each_chunk_to_the_custom_stream(monkeypatch):
    from app.services import rag

    async def fake_stream(user_id, question):
        for chunk in ("Spend ", "spiked."):
            yield chunk

    monkeypatch.setattr(rag, "answer_with_rag_stream", fake_stream)
    written: list[str] = []
    monkeypatch.setattr(analyst_node, "_stream_writer", lambda: written.append)

    out = await analyst_node.analyst_node({"user_id": 7, "trigger": "chat", "question": "why?"})

    assert written == ["Spend ", "spiked."]
    assert out["analyst"]["answer"] == "Spend spiked."

@pytest.mark.anyio
async def test_analyst_subgraph_streams_over_a_real_graph(monkeypatch):
    """The custom stream has to work through a compiled graph, not just the node."""
    from app.services import rag

    async def fake_stream(user_id, question):
        yield "Spend spiked."

    monkeypatch.setattr(rag, "answer_with_rag_stream", fake_stream)
    graph = analyst_node.build_analyst_graph()

    chunks: list[str] = []
    async for mode, chunk in graph.astream(
        {"user_id": 7, "trigger": "chat", "question": "why?"}, stream_mode=["custom", "values"]
    ):
        if mode == "custom":
            chunks.append(chunk)

    assert chunks == ["Spend spiked."]


@pytest.mark.anyio
async def test_analyst_node_falls_back_to_the_non_streaming_service(monkeypatch):
    from app.services import rag

    async def fake_answer(user_id, question):
        return "no stream available"

    monkeypatch.setattr(rag, "answer_with_rag", fake_answer)
    monkeypatch.setattr(analyst_node, "_stream_writer", lambda: None)

    out = await analyst_node.analyst_node({"user_id": 7, "trigger": "chat", "question": "why?"})

    assert out["analyst"]["answer"] == "no stream available"


# --------------------------------------------------------------------------- #
# the old ReAct agent is gone
# --------------------------------------------------------------------------- #

_REACT_AGENT_REF = re.compile(r"app\.agents\.cfo_agent|from\s+app\.agents\s+import\s+cfo_agent")


def test_nothing_references_the_removed_react_agent():
    offenders = [
        str(path)
        for path in pathlib.Path("app").rglob("*.py")
        if _REACT_AGENT_REF.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_removed_agent_file_is_gone():
    assert not pathlib.Path("app/agents/cfo_agent.py").exists()
