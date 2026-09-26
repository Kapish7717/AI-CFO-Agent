# ==========================================================
# supabase-mcp: FastMCP server (stdio transport)
# ==========================================================

from mcp.server.fastmcp import FastMCP

from app.mcp.supabase.tools_query import describe_table, run_read_only_sql
from app.mcp.supabase.tools_read import (
    get_sync_status,
    list_stripe_transactions,
    list_transactions,
)
from app.mcp.supabase.tools_transactions import (
    mark_sync_status,
    write_stripe_transactions,
    write_transactions,
)

mcp = FastMCP("supabase-mcp")

# Register the org-scoped read + write tools:
#   reads  - list_transactions, list_stripe_transactions, get_sync_status,
#            describe_table, run_read_only_sql
#   writes - write_transactions, write_stripe_transactions, mark_sync_status
mcp.tool()(list_transactions)
mcp.tool()(list_stripe_transactions)
mcp.tool()(get_sync_status)
mcp.tool()(describe_table)
mcp.tool()(run_read_only_sql)
mcp.tool()(write_transactions)
mcp.tool()(write_stripe_transactions)
mcp.tool()(mark_sync_status)


if __name__ == "__main__":
    mcp.run()