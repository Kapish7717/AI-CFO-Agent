from typing import TypedDict, Annotated, Sequence
import operator
import os
import sys
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import tools_condition
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

GROQ_MODEL = "llama-3.3-70b-versatile"

# --- 1. AGENT STATE DEFINITION ---
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]

# --- 2. GLOBAL CACHE ---
_mcp_client = None
_all_tools = None
_llm_with_tools = None

# Robust API Key loading (strips potential quotes/spaces from Docker --env-file)
raw_key = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEY = raw_key.strip().strip('"').strip("'")

# Crucial: Export the cleaned key back to os.environ so subprocesses (tools) can see it
os.environ["GROQ_API_KEY"] = GROQ_API_KEY

# --- 3. MCP CONFIGURATION ---
# We define this AFTER cleaning the environment so the subprocess inherits the clean keys
mcp_config = {
    "cfo_core": {
        "command": sys.executable,
        "args": ["mcp_client.py"],
        "transport": "stdio",
        "env": os.environ.copy() # Explicitly pass the cleaned environment
    }
}

llm = ChatGroq(model=GROQ_MODEL, temperature=0, groq_api_key=GROQ_API_KEY)

if GROQ_API_KEY:
    print(f"[AGENT] Groq API Key found: {GROQ_API_KEY[:10]}...", flush=True)
else:
    print("[AGENT ERROR] Groq API Key NOT found in environment!", flush=True)


async def get_all_tools():
    """
    Fetches tools from the MCP server once and caches them.
    Note: As of langchain-mcp-adapters 0.1.0, MultiServerMCPClient 
    does not support async context manager interface.
    """
    global _all_tools, _mcp_client
    if _all_tools is not None:
        return _all_tools

    try:
        sys.stderr.write("[MCP] Connecting to CFO Central Server...\n")
        _mcp_client = MultiServerMCPClient(mcp_config)
        mcp_tools = await _mcp_client.get_tools()
        
        found_names = [t.name for t in mcp_tools]
        sys.stderr.write(f"[MCP] Discovered {len(mcp_tools)} tools: {found_names}\n")
        _all_tools = mcp_tools
        return _all_tools
    except Exception as e:
        sys.stderr.write(f"[MCP ERROR] Connection failed: {e}\n")
        return []
async def get_llm_with_tools():
    """
    Returns a cached LLM instance with tools already bound.

    FIX 1: Previously llm.bind_tools() was called inside call_model() on every
    single agent invocation, creating a new object each time. Now it is built
    once on first call and reused for the lifetime of the process.
    """
    global _llm_with_tools
    if _llm_with_tools is not None:
        return _llm_with_tools
    tools = await get_all_tools()
    _llm_with_tools = llm.bind_tools(tools)
    return _llm_with_tools


# --- 4. AGENT NODES ---

async def call_model(state: AgentState):
    """The Agent node that decides which tool to call."""
    llm_bound = await get_llm_with_tools()  # FIX 1: cached binding
    messages = state.get("messages", [])
    
    # Safety: if more than 20 messages, something is looping
    if len(messages) > 20:
        sys.stderr.write("[AGENT] Message limit reached — possible loop. Stopping.\n")
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="Agent stopped: exceeded step limit.")]}
    system_prompt = SystemMessage(content=(
        "You are an expert autonomous CFO AI agent. "
        "You MUST call tools in this exact sequence for the core financial workflow. Never skip a step. Never summarize instead of calling a tool.\n\n"
        "MANDATORY SEQUENCE — call each tool one at a time, wait for result, then call the next:\n"
        "STEP 1: authenticate_google — ALWAYS call this with NO arguments first. NEVER invent, guess, or hallucinate an auth_code. If the tool returns a link, YOU MUST STOP and wait for the user. Only pass 'auth_code' if the user literally just provided it in their last message.\n"
        "STEP 2: ingest_financial_data — only after Step 1 is successful.\n"
        "STEP 3: detect_financial_anomalies — always third.\n"
        "STEP 4: generate_cfo_pdf_report — always fourth.\n"
        "STEP 5: send_email_report — always fifth.\n"
        "STEP 6: schedule_meeting — optional, call this sixth if requested.\n\n"
        "RULES:\n"
        "- You MUST call generate_cfo_pdf_report after detect_financial_anomalies. No exceptions.\n"
        "- If the user makes a specific request about the report format or content (e.g. 'show monthly revenue at the end'), pass that request as 'custom_instructions' to generate_cfo_pdf_report.\n"
        "- You MUST call send_email_report after generate_cfo_pdf_report. No exceptions.\n"
        "- Do NOT write a summary or explanation between steps. Only make tool calls.\n"
        "- When passing Windows file paths (starting with C:\\), ensure you escape backslashes correctly in the JSON argument.\n"
        "- Only after ALL requested actions (including email and meeting if applicable) succeed, write a final one-line confirmation.\n\n"
        "FRONTEND INPUT FORMAT:\n"
        "- BUDGET_LIMITS: parse into a dict {Category: Amount}\n"
        "- EXPENSE_FILE_PATH: pass to ingest_financial_data\n"
        "- REVENUE_FILE_PATH: pass to ingest_financial_data\n"
        "- EXPENSE_SHEET_URL / REVENUE_SHEET_URL: Google Sheet URLs\n"
        "- Target email/attendees are mentioned in natural language (e.g. 'send to mfkapish@gmail.com' or 'invite team@example.com')\n"
        "- Meeting times: If the user says 'tomorrow at 10am', calculate the ISO string based on current time (Current local time is: 2026-05-15T11:21:39+05:30).\n"
    ))

    messages = state.get("messages", [])

    sys.stderr.write(f"\n[AGENT] Calling Groq LLM ({GROQ_MODEL})...\n")
    response = await llm_bound.ainvoke([system_prompt] + list(messages))

    # Keep one tool call at a time for graph stability
    if hasattr(response, "tool_calls") and len(response.tool_calls) > 1:
        response.tool_calls = [response.tool_calls[0]]

    return {"messages": [response]}


async def tool_node(state: AgentState):
    """The Tool node that executes the requested tool."""
    messages = state.get("messages", [])
    last_message = messages[-1]

    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {"messages": []}

    all_tools_list = await get_all_tools()
    tool_map = {t.name: t for t in all_tools_list}

    tool_outputs = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        # FIX 3: Use .get() consistently in ALL branches (success, error, not-found).
        # Groq is reliable with IDs but defensive access prevents any edge-case KeyError.
        tool_call_id = tool_call.get("id") or tool_call.get("name", "unknown_id")

        sys.stderr.write(f"[TOOLS] Executing: {tool_name} (id={tool_call_id})\n")

        if tool_name in tool_map:
            tool = tool_map[tool_name]
            try:
                # Increased timeout to 300 seconds (5 minutes)
                import asyncio
                sys.stderr.write(f"[TOOLS] Awaiting tool result for: {tool_name}...\n")
                result = await asyncio.wait_for(tool.ainvoke(tool_args), timeout=300.0)
                sys.stderr.write(f"[TOOLS] Completed: {tool_name}\n")
                # FIX 2: Use ToolMessage (a proper BaseMessage subclass).
                # Previously raw dicts were appended — LangGraph's state reducer
                # silently drops them, so the agent never saw tool results and stalled.
                tool_outputs.append(
                    ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call_id,
                    )
                )
            except asyncio.TimeoutError:
                err_msg = f"Timeout error: Tool '{tool_name}' exceeded the 300s limit. It may be processing large data or the MCP server is unresponsive."
                sys.stderr.write(f"[TOOLS] {err_msg}\n")
                tool_outputs.append(
                    ToolMessage(
                        content=err_msg,
                        tool_call_id=tool_call_id,
                    )
                )
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                sys.stderr.write(f"[TOOLS] Error in {tool_name}: {e}\n{error_details}\n")
                tool_outputs.append(
                    ToolMessage(
                        content=f"Error executing {tool_name}: {str(e) or type(e).__name__}",
                        tool_call_id=tool_call_id,
                    )
                )
        else:
            available = list(tool_map.keys())
            tool_outputs.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' not found. Available tools: {available}",
                    tool_call_id=tool_call_id,
                )
            )

    return {"messages": tool_outputs}


# --- 5. GRAPH CONSTRUCTION ---
builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", tool_node)

builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")

graph = builder.compile()


# async def main():
#     print("\n--- TOOL VERIFICATION ---")
#     available_tools = await get_all_tools()
#     if available_tools:
#         print(f"PASS: Agent found {len(available_tools)} tools.")
#         for i, t in enumerate(available_tools):
#             print(f"  {i+1}. {t.name}")
#     else:
#         print("FAIL: Agent could not find any tools.")
#     print("------------------------\n")

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(main())