from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from app.agents import cfo_agent as agent


def _fake_tool(name: str, result: str):
    """Build a lightweight stand-in for an MCP tool that the graph can execute."""
    t = MagicMock(name=name)
    t.name = name
    t.ainvoke = AsyncMock(return_value=result)
    return t


@tool
def mock_authenticate_google() -> str:
    """Mock authentication tool"""
    return "Success: Already authenticated with Google."

@tool
def mock_ingest_financial_data(expense_path_or_url: str) -> str:
    """Mock ingestion tool"""
    return "Success! Unified 100 rows."

@pytest.mark.anyio
@patch("app.agents.cfo_agent.get_all_tools")
@patch("app.agents.cfo_agent.get_llm_with_tools")
async def test_agent_graph_execution(mock_get_llm, mock_get_tools):
    mock_tools = [mock_authenticate_google, mock_ingest_financial_data]
    mock_get_tools.return_value = mock_tools

    agent._all_tools = None
    agent._llm_with_tools = None

    first_llm_response = AIMessage(
        content="",
        tool_calls=[{
            "name": "mock_authenticate_google",
            "args": {},
            "id": "call_abc123"
        }]
    )
    second_llm_response = AIMessage(
        content="Authentication was successful. I am now ready to proceed."
    )

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=[first_llm_response, second_llm_response])
    mock_get_llm.return_value = mock_llm

    initial_state = {"messages": [HumanMessage(content="Start the financial workflow.")]}
    result = await agent.graph.ainvoke(initial_state)

    assert "messages" in result
    messages = result["messages"]

    assert len(messages) == 4
    assert messages[0].content == "Start the financial workflow."
    assert messages[1].tool_calls[0]["name"] == "mock_authenticate_google"
    assert isinstance(messages[2], ToolMessage)
    assert "Success" in messages[2].content
    assert messages[3].content == "Authentication was successful. I am now ready to proceed."

    assert mock_llm.ainvoke.call_count == 2


@pytest.mark.anyio
@patch("app.agents.cfo_agent.get_all_tools")
@patch("app.agents.cfo_agent.get_llm_with_tools")
async def test_agent_halts_on_tool_error(mock_get_llm, mock_get_tools):
    """A failed tool result must route the graph to the halt node."""
    mock_tools = [
        _fake_tool("mock_authenticate_google", "Success: Already authenticated."),
        _fake_tool("mock_ingest_financial_data", "Error: Expense file not found."),
    ]
    mock_get_tools.return_value = mock_tools

    agent._all_tools = None
    agent._llm_with_tools = None

    llm_response = AIMessage(
        content="",
        tool_calls=[{
            "name": "mock_ingest_financial_data",
            "args": {"expense_path_or_url": "uploads/missing.csv"},
            "id": "call_xyz789",
        }]
    )
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=llm_response)
    mock_get_llm.return_value = mock_llm

    initial_state = {"messages": [HumanMessage(content="Run the ingest step.")]}
    result = await agent.graph.ainvoke(initial_state)

    messages = result["messages"]
    assert isinstance(messages[-1], AIMessage)
    assert "Stopped: a required step failed" in messages[-1].content

    assert mock_llm.ainvoke.call_count == 1


@pytest.mark.anyio
@patch("app.agents.cfo_agent.get_all_tools")
@patch("app.agents.cfo_agent.get_llm_with_tools")
async def test_agent_routes_back_to_model_on_success(mock_get_llm, mock_get_tools):
    """A successful tool result must loop back to the LLM."""
    mock_tools = [
        _fake_tool("mock_authenticate_google", "Success: Already authenticated."),
        _fake_tool("mock_ingest_financial_data", "Success! Unified 100 rows."),
    ]
    mock_get_tools.return_value = mock_tools

    agent._all_tools = None
    agent._llm_with_tools = None

    first = AIMessage(
        content="",
        tool_calls=[{
            "name": "mock_ingest_financial_data",
            "args": {"expense_path_or_url": "uploads/data.csv"},
            "id": "call_ok456",
        }]
    )
    second = AIMessage(content="Data ingested successfully.")
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=[first, second])
    mock_get_llm.return_value = mock_llm

    initial_state = {"messages": [HumanMessage(content="Run the ingest step.")]}
    result = await agent.graph.ainvoke(initial_state)

    messages = result["messages"]
    assert isinstance(messages[-1], AIMessage)
    assert messages[-1].content == "Data ingested successfully."
    assert mock_llm.ainvoke.call_count == 2
