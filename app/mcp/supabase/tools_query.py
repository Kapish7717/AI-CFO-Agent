# ==========================================================
# supabase-mcp: query tools (org-scoped, LLM-generated SQL)
# ==========================================================
# These two tools are the retrieval path for the chat. They exist so the
# Text-to-SQL pipeline never holds a database connection of its own: schema
# discovery and execution both go through the org-scoped tools below, and the
# tenant boundary is enforced here rather than requested in the LLM prompt.

from __future__ import annotations

import asyncio

import psycopg2

from app.db.database import get_connection
from app.mcp.supabase.org import jsonable, resolve_org_scope
from app.mcp.supabase.sql_guard import (
    QUERYABLE_TABLES,
    ScopeError,
    assert_queryable,
    read_only,
    scope_sql,
    strip_sql_fences,
)

#: Row cap per query. The chat only needs enough rows to ground an answer, and
#: an unbounded result set from a model-written query is a memory risk.
MAX_ROWS = 2000

#: Statement timeout in ms, so a runaway cross join cannot pin a pool worker.
STATEMENT_TIMEOUT_MS = 15_000


def _describe_table(user_id: int, table_name: str) -> list[str]:
    resolve_org_scope(user_id)
    if table_name not in QUERYABLE_TABLES:
        raise ValueError(
            f"Unknown table {table_name!r}; chat may only read "
            f"{', '.join(QUERYABLE_TABLES)}"
        )
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position",
                (table_name,),
            )
            columns = cur.fetchall()
    finally:
        conn.close()
    if not columns:
        return []
    decl = (
        f"CREATE TABLE {table_name} (\n"
        + ",\n".join(f"  {c['column_name']} {c['data_type']}" for c in columns)
        + "\n);"
    )
    return [decl]


async def describe_table(user_id: int, table_name: str = QUERYABLE_TABLES[0]) -> list[str]:
    """Return ``CREATE TABLE``-style schema text for a chat-queryable table.

    Only the tables the chat is allowed to read can be described, so this cannot
    be used to fingerprint the rest of the schema.
    """
    return await asyncio.to_thread(_describe_table, user_id, table_name)


def _run_scoped_sql(user_id: int, sql: str, max_rows: int) -> dict:
    user_ids = resolve_org_scope(user_id)
    cleaned = strip_sql_fences(sql)
    if not read_only(cleaned):
        raise ValueError("only read-only (SELECT) queries are allowed")
    assert_queryable(cleaned)
    scoped = scope_sql(cleaned, user_ids)

    conn = get_connection()
    try:
        try:
            conn.rollback()
        except Exception:
            pass
        # Defense in depth: even a statement that slipped the keyword guard
        # cannot write, because PostgreSQL enforces this.
        conn.set_session(readonly=True)
        try:
            with conn.cursor() as cur:
                # Literal, not a placeholder: SET does not accept bind params.
                cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                cur.execute(scoped, (*user_ids, max_rows + 1))
                rows = cur.fetchmany(max_rows + 1)
        except psycopg2.errors.UndefinedColumn as e:
            raise ScopeError(
                "query must include user_id in its SELECT list so the org scope "
                "can be enforced"
            ) from e
    finally:
        try:
            conn.rollback()
            conn.set_session(readonly=False)
        finally:
            conn.close()

    truncated = len(rows) > max_rows
    return {
        "rows": [jsonable(r) for r in rows[:max_rows]],
        "row_count": min(len(rows), max_rows),
        "truncated": truncated,
    }


async def run_read_only_sql(user_id: int, sql: str, max_rows: int = MAX_ROWS) -> dict:
    """Run model-written SQL, returning only rows the caller's org can see.

    Returns ``{"rows": [...], "row_count": int, "truncated": bool}``. The query
    must be a single read-only SELECT over ``unified_transactions``; anything
    else raises ``ValueError``. Row scoping is applied by this tool, so the
    caller cannot widen it by editing the SQL.
    """
    return await asyncio.to_thread(_run_scoped_sql, user_id, sql, max_rows)
