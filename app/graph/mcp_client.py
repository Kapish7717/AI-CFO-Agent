"""MCP clients for the pipeline graph — binds supabase-mcp + reporting-mcp tools
via langchain-mcp-adapters (stdio transport, in-process subprocesses).

There is no Stripe fetch server here: Stripe data reaches unified_transactions
through the 60s sync loop and the webhook (app/main.py, app/services/stripe_sync.py),
so a run reads what is already stored and never re-fetches.
"""

import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

MCP_SERVERS = {
    "supabase": {
        "command": sys.executable,
        "args": ["-m", "app.mcp.supabase.server"],
        "transport": "stdio",
        "env": os.environ.copy(),
    },
    "reporting": {
        "command": sys.executable,
        "args": ["-m", "app.mcp.reporting.server"],
        "transport": "stdio",
        "env": os.environ.copy(),
    },
}

_client = None
_tools = None


async def get_pipeline_tools():
    """Return the combined supabase-mcp + reporting-mcp tools, cached after the
    first call. Returns [] if the MCP connection fails so nodes degrade to
    explicit error results."""
    global _client, _tools
    if _tools is not None:
        return _tools
    try:
        _client = MultiServerMCPClient(MCP_SERVERS)
        _tools = await _client.get_tools()
        names = [t.name for t in _tools]
        sys.stderr.write(f"[GRAPH][MCP] Bound {len(_tools)} tools: {names}\n")
    except Exception as e:
        sys.stderr.write(f"[GRAPH][MCP] Connection failed: {e}\n")
        _tools = []
    return _tools