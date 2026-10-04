# ==========================================================
# supabase-mcp: FastMCP server (stdio transport)
#
# Read-only by design. Writes reach unified_transactions through the 60s Stripe
# loop, the Stripe webhook and the upload ingest (app/db/unified_store.py
# callers), so nothing here can mutate a transaction.
# ==========================================================

# Each stdio server is its own process, so nothing else loads .env for it: the
# FastAPI app happens to export the environment to the subprocess it spawns, but
# running this module directly (mcp dev, the Inspector) has no such parent.
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from app.mcp.supabase.tools_query import describe_table, run_read_only_sql
from app.mcp.supabase.tools_read import list_transactions

load_dotenv()

mcp = FastMCP("supabase-mcp")

# list_transactions feeds the anomaly pass; describe_table/run_read_only_sql back
# the Text-to-SQL analyst.
mcp.tool()(list_transactions)
mcp.tool()(describe_table)
mcp.tool()(run_read_only_sql)


if __name__ == "__main__":
    mcp.run()
