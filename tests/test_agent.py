import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from langchain_core.tools import tool

# Importing the compiled graph and agent functions
import agent

# Create a simple mock tool for testing
@tool
def mock_authenticate_google() -> str:
    """Mock authentication tool"""
    return "Success: Already authenticated with Google."

@tool
def mock_ingest_financial_data(expense_path_or_url: str) -> str:
    """Mock ingestion tool"""
    return "Success! Unified 100 rows."

@pytest.mark.anyio
@patch("agent.get_all_tools")
@patch("agent.llm")
async def test_agent_graph_execution(mock_llm, mock_get_tools):
    # 1. Setup mock tools
    mock_tools = [mock_authenticate_google, mock_ingest_financial_data]
    mock_get_tools.return_value = mock_tools

    # Clear cached LLM and tools to force re-binding with our mocks
    agent._all_tools = None
    agent._llm_with_tools = None

    # 2. Setup mock LLM response
    # First response: Decides to call the mock_authenticate_google tool
    first_llm_response = AIMessage(
        content="",
        tool_calls=[{
            "name": "mock_authenticate_google",
            "args": {},
            "id": "call_abc123"
        }]
    )
    
    # Second response: Summarizes after tool execution
    second_llm_response = AIMessage(
        content="Authentication was successful. I am now ready to proceed."
    )

    # Configure the mock LLM to return the first response, then the second
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(side_effect=[first_llm_response, second_llm_response])

    # 3. Initialize state and run the graph
    initial_state = {"messages": [HumanMessage(content="Start the financial workflow.")]}
    
    # Run the compiled graph asynchronously
    result = await agent.graph.ainvoke(initial_state)

    # 4. Assertions
    assert "messages" in result
    messages = result["messages"]
    
    # The conversation should have:
    # 1. HumanMessage (input)
    # 2. AIMessage (decides to call mock_authenticate_google)
    # 3. ToolMessage (contains the tool execution result)
    # 4. AIMessage (final summary response)
    assert len(messages) == 4
    
    # Check execution sequence
    assert messages[0].content == "Start the financial workflow."
    assert messages[1].tool_calls[0]["name"] == "mock_authenticate_google"
    assert isinstance(messages[2], ToolMessage)
    assert "Success" in messages[2].content
    assert messages[3].content == "Authentication was successful. I am now ready to proceed."

    # Verify our mock LLM ainvoke was called exactly twice
    assert mock_llm.ainvoke.call_count == 2
