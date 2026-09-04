import hashlib
import logging
import operator
import os
import re
import sys
from collections.abc import Sequence
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

load_dotenv()

logger = logging.getLogger("cfo.agent")

GROQ_MODEL = "llama-3.1-8b-instant"

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]

_mcp_client = None
_all_tools = None
_llm_with_tools = None

raw_key = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEY = raw_key.strip().strip('"').strip("'")

os.environ["GROQ_API_KEY"] = GROQ_API_KEY

mcp_config = {
    "cfo_core": {
        "command": sys.executable,
        "args": ["-m", "app.agents.mcp_server"],
        "transport": "stdio",
        "env": os.environ.copy()
    }
}

# Default LLM (fallback when a user has not configured their own provider/API key).
llm = ChatGroq(model=GROQ_MODEL, temperature=0, groq_api_key=GROQ_API_KEY)

if GROQ_API_KEY:
    logger.info("Default Groq API key is configured (first 4 chars: %s...).", GROQ_API_KEY[:4])
else:
    logger.warning("Default Groq API key NOT found in environment!")


def extract_user_id(messages) -> int:
    """Parse the 'USER_ID: <n>' prefix from the user message(s). Defaults to 1."""
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            match = re.search(r"USER_ID[:=]\s*(\d+)", content)
            if match:
                return int(match.group(1))
        elif isinstance(content, list):
            for part in content:
                text = part.get("text") if isinstance(part, dict) else None
                if isinstance(text, str):
                    match = re.search(r"USER_ID[:=]\s*(\d+)", text)
                    if match:
                        return int(match.group(1))
    return 1


def build_llm_for_user(user_id: int):
    """Build a LangChain chat model from the user's stored LLM settings.

    Returns ``(llm_instance, signature)`` where ``signature`` uniquely identifies
    the current provider/model/api key so the bound instance can be cached. When the
    user has no custom provider/API key configured, returns ``(None, None)`` so the
    module-level default (env GROQ key) is used instead.
    """
    try:
        from app.db.database import get_user_settings
        settings = get_user_settings(user_id)
    except Exception as e:
        sys.stderr.write(f"[AGENT] Could not load user settings for user {user_id}: {e}\n")
        return None, None

    provider = (settings.get("llm_primary_provider") or "").strip().lower()
    model = (settings.get("llm_primary_model") or "").strip() or GROQ_MODEL
    api_key = (settings.get("api_key") or "").strip().strip('"').strip("'")

    # No custom provider or no key upload -> use default GROQ env key / module LLM.
    if not provider or provider in ("mock", "local", "none", "test"):
        return None, None

    try:
        from app.services.llm_factory import create_llm
        user_llm = create_llm(provider=provider, model=model, api_key=api_key)
    except Exception as e:
        sys.stderr.write(f"[AGENT] Could not build LLM for provider '{provider}': {e}\n")
        return None, None

    signature = hashlib.sha256(
        f"{provider.lower()}|{model}|{api_key}".encode()
    ).hexdigest()[:20]
    return user_llm, signature


# Cache of tool-bound LLM instances keyed by the LLM config signature.
_user_llm_cache: dict = {}


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


async def get_llm_with_tools(user_id=None):
    """Return a cached LLM instance (with tools bound) for the given user.

    Falls back to the module-level default (env GROQ) when the user has not set a
    custom provider + API key.
    """
    global _llm_with_tools
    tools = await get_all_tools()

    if user_id is not None:
        user_llm, signature = build_llm_for_user(user_id)
        if user_llm is not None and signature:
            if signature in _user_llm_cache:
                return _user_llm_cache[signature]
            bound = user_llm.bind_tools(tools)
            _user_llm_cache[signature] = bound
            sys.stderr.write(f"[AGENT] Using per-user provider LLM for user {user_id}.\n")
            return bound

    if _llm_with_tools is not None:
        return _llm_with_tools
    _llm_with_tools = llm.bind_tools(tools)
    return _llm_with_tools


# --- 4. AGENT NODES ---

async def call_model(state: AgentState):
    """The Agent node that decides which tool to call."""
    messages = state.get("messages", [])
    user_id = extract_user_id(messages)
    llm_bound = await get_llm_with_tools(user_id=user_id)  # FIX 1: cached binding

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
        "- NEVER call the same tool twice in a row. If a tool returns an error, DO NOT retry it. Stop and tell the user about the error.\n"
        "- Only after ALL requested actions (including email and meeting if applicable) succeed, write a final one-line confirmation.\n"
        "- USER_ID: Parse the user_id from the 'USER_ID: <number>' prefix in the user message, and ALWAYS pass this user_id as an integer parameter to ALL tool calls. If not found, default to 1.\n\n"
        "FRONTEND INPUT FORMAT:\n"
        "- BUDGET_LIMITS: parse into a dict {Category: Amount}\n"
        "- EXPENSE_FILE_PATH: pass to ingest_financial_data\n"
        "- REVENUE_FILE_PATH: pass to ingest_financial_data\n"
        "- EXPENSE_SHEET_URL / REVENUE_SHEET_URL: Google Sheet URLs\n"
        "- Target email/attendees are mentioned in natural language (e.g. 'send to mfkapish@gmail.com' or 'invite team@example.com')\n"
        "- Meeting times: If the user says 'tomorrow at 10am', calculate the ISO string based on current time.\n"
    ))

    sys.stderr.write(f"\n[AGENT] Calling LLM ({GROQ_MODEL}) for user {user_id}...\n")
    try:
        response = await llm_bound.ainvoke([system_prompt] + list(messages))
        return {"messages": [response]}
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        sys.stderr.write(f"[AGENT ERROR] LLM call failed: {e}\n{tb}\n")

        # Provide a helpful message back to the agent flow instead of raising.
        err_text = str(e)
        if err_text and "rate limit" in err_text.lower():
            err_msg = (
                "LLM rate limit reached: the model quota has been exhausted or throttled. "
                "Try again later, reduce prompt size, or configure a smaller/fallback model."
            )
        else:
            err_msg = f"LLM error: {err_text}"

        # Optionally attempt a one-off fallback model if configured.
        allow_fallback = os.environ.get("ALLOW_MODEL_FALLBACK", "").lower() in ("1", "true", "yes")
        fallback_model = os.environ.get("FALLBACK_MODEL", "llama-2-13b")
        if allow_fallback and err_text and "rate limit" in err_text.lower():
            try:
                fallback_bound = None
                try:
                    from app.db.database import get_user_settings
                    fb_settings = get_user_settings(user_id)
                    fb_provider = (fb_settings.get("llm_fallback_provider") or "").strip().lower()
                    if fb_provider and fb_provider not in ("mock", "local", "none", "test"):
                        from app.services.llm_factory import create_llm
                        fb_model = (fb_settings.get("llm_fallback_model") or "").strip() or fallback_model
                        fb_key = (fb_settings.get("fallback_api_key") or fb_settings.get("api_key") or "").strip().strip('"').strip("'")
                        fb_llm = create_llm(provider=fb_provider, model=fb_model, api_key=fb_key)
                        fallback_bound = fb_llm.bind_tools(await get_all_tools())
                except Exception as fb_err:
                    sys.stderr.write(f"[AGENT] User fallback setup failed: {fb_err}\n")

                if fallback_bound is None:
                    fallback_llm = ChatGroq(model=fallback_model, temperature=0, groq_api_key=GROQ_API_KEY)
                    fallback_bound = fallback_llm.bind_tools(await get_all_tools())

                sys.stderr.write(f"[AGENT] Attempting fallback model: {fallback_model}\n")
                response = await fallback_bound.ainvoke([system_prompt] + list(messages))
                return {"messages": [response]}
            except Exception as e2:
                sys.stderr.write(f"[AGENT] Fallback model failed: {e2}\n")
                err_msg += " Fallback attempt failed."

        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content=err_msg)]}


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


# --- 4.5 ERROR DETECTION / HALT NODE ---

_ERROR_MARKERS = ("error", "timeout", "failed", "not found", "must be")


def _tool_msgs(state: AgentState):
    """Last ToolMessage(s) produced by the most recent tools run."""
    messages = state.get("messages", [])
    tool_msgs = []
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            tool_msgs.append(msg)
        elif isinstance(msg, AIMessage):
            break
    return list(reversed(tool_msgs))


def _has_error(state: AgentState) -> bool:
    """True if any tool result of the last run is an error/failure message.

    Used to route the graph to a halt node instead of looping back into the LLM,
    so a failed tool never triggers a blind retry or lets the pipeline continue
    on top of invalid state.
    """
    for tm in _tool_msgs(state):
        content = str(getattr(tm, "content", ""))
        if content.lower().startswith("error"):
            return True
        for marker in _ERROR_MARKERS:
            if marker in content.lower():
                return True
    return False


# --- 5. GRAPH CONSTRUCTION ---
builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", tool_node)
builder.add_node("halt", lambda state: {"messages": [AIMessage(content=(
    "Stopped: a required step failed. No further actions were taken and the "
    "financial workflow was not completed. Please check the error above and "
    "retry the workflow when the issue is resolved."
))]})


def route_after_tools(state: AgentState) -> str:
    return "halt" if _has_error(state) else "agent"


builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_conditional_edges("tools", route_after_tools, {"halt": "halt", "agent": "agent"})
builder.add_edge("halt", END)

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