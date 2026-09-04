"""Text-to-SQL RAG for the AI Chat using Jina reranking.

This module answers natural-language questions about the user's financial data:

    1. Loads the live database schema (PostgreSQL/Supabase via DATABASE_URL).
    2. Uses the Jina reranker API to pick the most relevant table schemas for
       the user's question.
    3. Asks the user's configured LLM to generate a read-only SQL query.
    4. Executes the query against the database.
    5. Asks the LLM to convert the result rows into a natural-language answer.

It is fully separate from the CFO reporting agent. If JINA_API_KEY is missing or
the reranker fails, the schemas are returned unranked so the chat still works.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

from app.db.database import get_connection, get_user_settings

logger = logging.getLogger("cfo.chat")

RERANK_URL = "https://api.jina.ai/v1/rerank"
JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip().strip('"').strip("'")

# Prefer the app's financial tables when ranking/querying.
PREFERRED_TABLES = (
    "transactions",
    "unified_transactions",
    "stripe_transactions",
)


def _llm_for(settings):
    """Build an LLM from the user's configured provider/model settings,
    defaulting to the env Groq key when none is configured."""
    from app.services.llm_factory import create_llm

    provider = (settings.get("llm_primary_provider") or "groq").lower()
    # "mock"/local/test settings mean "no real model configured" — fall back to
    # the env Groq key so the chat actually answers.
    if provider in ("mock", "local", "none", "test"):
        provider = "groq"
    model = settings.get("llm_primary_model")
    api_key = (settings.get("api_key") or "").strip() or GROQ_API_KEY
    return create_llm(provider=provider, model=model, api_key=api_key)


async def _llm_answer(llm, prompt: str) -> str:
    from app.services.llm_factory import generate_text
    return await generate_text(llm, prompt)


def extract_schema(conn) -> list:
    """Return ``CREATE TABLE``-style schema strings for the app tables."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position;
        """
    )
    columns = {}
    for row in cur.fetchall():
        table = row.get("table_name")
        columns.setdefault(table, []).append((row.get("column_name"), row.get("data_type")))

    specs = []
    for name in PREFERRED_TABLES:
        if name not in columns:
            continue
        decl = f"CREATE TABLE {name} (\n" + ",\n".join(
            f"  {col} {dtype}" for col, dtype in columns[name]
        ) + "\n);"
        specs.append(decl)
    return specs


async def rank_tables(query: str, table_specs: list, top_n: int = 0) -> list:
    """Rank table schemas against the question using the Jina reranker.

    Returns ``[(relevance_score, schema), ...]``. If the key is missing or the
    request fails, the schemas are returned unranked so callers can proceed.
    """
    if not table_specs:
        return []

    if not JINA_API_KEY:
        logger.warning("JINA_API_KEY not set; returning unranked schemas.")
        return [(0.0, spec) for spec in table_specs]

    data = {
        "model": "jina-reranker-v2-base-multilingual",
        "query": query,
        "documents": table_specs,
        "top_n": top_n if top_n > 0 else len(table_specs),
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {JINA_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(RERANK_URL, headers=headers, json=data)
            resp.raise_for_status()
            result = resp.json()
            scored = []
            for item in result.get("results", []):
                score = item.get("relevance_score", 0.0)
                doc = item.get("document") or ""
                table_spec = doc.get("text") if isinstance(doc, dict) else doc
                if not table_spec:
                    table_spec = table_specs[item.get("index", 0)]
                scored.append((score, table_spec))
            return scored
    except Exception as e:
        logger.warning(f"Jina rerank failed: {e}")
        return [(0.0, spec) for spec in table_specs]


def make_sql_prompt(query: str, table_specs: list) -> str:
    """Build the prompt asking the LLM to write a read-only SQL query."""
    t1 = table_specs[0][1] if len(table_specs) > 0 else "None"
    t2 = table_specs[1][1] if len(table_specs) > 1 else "None"
    t3 = table_specs[2][1] if len(table_specs) > 2 else "None"
    return (
        "Generate a SQL query to answer the following question from the user:\n"
        f'"{query}"\n\n'
        "The SQL query should use only tables with the following SQL definitions:\n\n"
        f"Table 1:\n{t1}\n\n"
        f"Table 2:\n{t2}\n\n"
        f"Table 3:\n{t3}\n\n"
        "Make sure you ONLY output a read-only SELECT (or WITH) SQL query and no explanation."
    )


async def generate_sql_query(sql_prompt: str, settings: dict) -> str:
    """Ask the user's LLM to generate the SQL query as plain text."""
    llm = _llm_for(settings)
    response = await _llm_answer(llm, sql_prompt)
    return response.strip()


_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"replace|call|copy|vacuum|analyze|reindex|comment|load|import|attach|"
    r"detach|begin|commit|rollback|savepoint|reset|set)\b",
    re.IGNORECASE,
)


def _strip_sql_literals(sql: str) -> str:
    """Remove comments and string literals so keyword checks see code only."""
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    # Replace single-quoted strings and double-quoted identifiers with spaces.
    s = re.sub(r"'(\\.|[^'\\])*'", " ", s)
    s = re.sub(r'"(\\.|[^"\\])*"', " ", s)
    # Dollar-quoted bodies ($$ ... $$ or $tag$ ... $tag$).
    s = re.sub(r"\$[A-Za-z_0-9]*\$.+?\$[A-Za-z_0-9]*\$", " ", s, flags=re.DOTALL)
    return s


def _read_only(sql: str) -> bool:
    """Guard so the chat can only run read-only queries.

    Requires the statement to start with SELECT/WITH AND contain no mutating
    keyword (including inside data-modifying CTEs). A trailing statement
    separator is tolerated, but chained multi-statement payloads are rejected.
    """
    cleaned = _strip_sql_literals(sql or "").strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if not lower.startswith(("select", "with")):
        return False
    # Split on ';' — a single trailing terminator is tolerated, but any
    # additional statement (chained multi-statement payloads) is rejected.
    parts = [p.strip() for p in cleaned.split(";")]
    while parts and parts[-1] == "":
        parts.pop()
    if len(parts) > 1:
        return False
    if _FORBIDDEN_KEYWORDS.search(cleaned):
        return False
    return True


def sql_response(sql_query: str, conn) -> list:
    """Execute a cleaned read-only SQL query and return the rows as dicts.

    The connection is forced into a read-only transaction as defense-in-depth:
    even if a mutating statement slipped through the keyword guard, PostgreSQL
    will reject it.
    """
    sql_clean = sql_query.replace("```sql", "").replace("```", "").strip().rstrip(";")
    # End any transaction opened by earlier queries (e.g. schema extraction) so
    # set_session can take effect.
    try:
        conn.rollback()
    except Exception:
        pass
    conn.set_session(readonly=True)
    try:
        cur = conn.cursor()
        cur.execute(sql_clean)
        rows = cur.fetchall()
        return [dict(r) for r in rows] if rows else []
    finally:
        conn.rollback()
        conn.set_session(readonly=False)


async def rag_response(query: str, sql_query: str, sql_result: list, settings: dict) -> str:
    """Turn the SQL result rows into a concise natural-language answer."""
    prompt = (
        "You are a financial analyst. Use the information in the JSON table to answer "
        "the following user query. Do not explain anything, just answer concisely in "
        "natural language, not computer formatting.\n\n"
        f"USER QUERY: {query}\n\n"
        f"JSON table:\n{json.dumps(sql_result, default=str)}\n\n"
        "This table was generated by the following SQL query:\n"
        f"{sql_query}\n\n"
        "Answer ONLY using the information in the table and the SQL query. If the table "
        "does not provide the information to answer the question, answer \"No Information\"."
    )
    llm = _llm_for(settings)
    return await _llm_answer(llm, prompt)


async def answer_with_rag(user_id: int, question: str) -> str:
    """Full Text-to-SQL RAG pipeline for a chat question."""
    import asyncio
    settings = await asyncio.to_thread(get_user_settings, user_id)
    conn = await asyncio.to_thread(get_connection)
    try:
        table_specs = await asyncio.to_thread(extract_schema, conn)
        if not table_specs:
            return "No database tables available to query."
        ranked = await rank_tables(question, table_specs, top_n=3)
        sql_prompt = make_sql_prompt(question, ranked)
        sql = await generate_sql_query(sql_prompt, settings)
        sql_clean = sql.replace("```sql", "").replace("```", "").strip()
        if sql_clean.startswith("[llm error]") or sql_clean.startswith("[mock]"):
            logger.error("RAG SQL generation failed for user %s: %s", user_id, sql_clean[:300])
            return (
                "I couldn't generate a database query with the configured model. "
                "Check the model in Settings, then try again."
            )
        if not _read_only(sql_clean):
            return "Sorry, I can only run read-only (SELECT) queries."
        result = await asyncio.to_thread(sql_response, sql_clean, conn)
        return await rag_response(question, sql_clean, result, settings)
    except Exception as e:
        logger.error(f"RAG query failed for user {user_id}: {e}")
        return f"Data query failed: {e}"
    finally:
        conn.close()