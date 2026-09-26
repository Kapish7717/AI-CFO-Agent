"""Text-to-SQL RAG for the AI Chat using Jina reranking.

This module answers natural-language questions about the user's financial data:

    1. Asks supabase-mcp for the schema of the tables the chat may read.
    2. Uses the Jina reranker API to pick the most relevant table schemas for
       the user's question.
    3. Asks the user's configured LLM to generate a read-only SQL query.
    4. Hands the SQL to supabase-mcp, which runs it inside a read-only
       transaction and returns only the caller's org rows.
    5. Asks the LLM to convert the result rows into a natural-language answer.

Retrieval goes through the supabase-mcp query tools (steps 1 and 4), so this
module holds no database connection and cannot read across tenants: the org
boundary is enforced by the tool, not by the instructions in the prompt.

It is fully separate from the CFO reporting agent. If JINA_API_KEY is missing or
the reranker fails, the schemas are returned unranked so the chat still works.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx

from app.db.database import get_domain_user_ids, get_user_chat_history, get_user_settings
from app.mcp.supabase.sql_guard import read_only as _read_only
from app.mcp.supabase.tools_query import ScopeError, describe_table, run_read_only_sql

logger = logging.getLogger("cfo.chat")

RERANK_URL = "https://api.jina.ai/v1/rerank"
JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip().strip('"').strip("'")

# Only query the unified_transactions table — it already contains all data
# from both Stripe and Excel uploads. The source column distinguishes them.
PREFERRED_TABLES = (
    "unified_transactions",
)


class RagAbort(Exception):
    """Stop the pipeline with a user-facing message instead of an error page."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


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


async def _describe_chat_tables(user_id: int) -> list:
    """Ask supabase-mcp for the schema of the tables the chat may read."""
    specs: list = []
    for name in PREFERRED_TABLES:
        try:
            specs.extend(await describe_table(user_id, name))
        except Exception as e:
            logger.warning("Could not describe %s for user %s: %s", name, user_id, e)
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


def _build_history_block(history: list | None, max_chars: int = 300) -> str:
    """Format conversation history for prompt injection.

    Agent responses are truncated to keep the prompt compact. Only user
    messages carry the full question context the LLM needs.
    """
    if not history:
        return ""

    turns = []
    current_turn = []
    for msg in history:
        role = "User" if msg["sender"] == "user" else "Agent"
        text = msg["text"]
        if role == "Agent" and len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "…"
        current_turn.append(f"  {role}: {text}")
        # Agent response ends a turn
        if role == "Agent":
            turns.append("\n".join(current_turn))
            current_turn = []
    # Flush any remaining user-only turn
    if current_turn:
        turns.append("\n".join(current_turn))

    numbered = []
    for i, turn in enumerate(turns, 1):
        numbered.append(f"[Turn {i}]\n{turn}")

    return "\n\n".join(numbered)


def make_sql_prompt(query: str, table_specs: list, user_id: int = 0, user_ids: list[int] | None = None, history: list | None = None) -> str:
    """Build the prompt asking the LLM to write a read-only SQL query."""
    schemas = "\n\n".join(
        f"Table {i+1}:\n{spec}" for i, (_, spec) in enumerate(table_specs)
    )

    history_block = _build_history_block(history)
    history_section = ""
    if history_block:
        history_section = (
            "\n\n=== CONVERSATION HISTORY ===\n"
            "The following is the recent conversation between the user and the assistant. "
            "Use this to understand context and resolve references like 'last month', 'those expenses', "
            "'the top category', 'that vendor', etc.\n\n"
            f"{history_block}\n"
            "=== END HISTORY ===\n\n"
        )

    # Build the user_id filter for the SQL prompt
    if user_ids and len(user_ids) > 1:
        ids_str = ", ".join(str(uid) for uid in user_ids)
        user_id_filter = f"ALWAYS filter by user_id IN ({ids_str}) — return data for the whole company."
    else:
        user_id_filter = f"ALWAYS filter by user_id = {user_id} — never return data from other users."

    return (
        "Generate a SQL query to answer the following question from the user:\n"
        f'"{query}"\n\n'
        "The SQL query should use only tables with the following SQL definitions:\n\n"
        f"{schemas}\n\n"
        "IMPORTANT RULES:\n"
        "- Always query only the unified_transactions table — it contains all data.\n"
        f"- {user_id_filter}\n"
        "- Always include user_id in the SELECT list. The query is filtered to the "
        "requesting company using that column before it runs, and cannot run at all "
        "without it.\n"
        "- The 'source' column indicates where the data came from: 'stripe' or 'excel'.\n"
        "- The 'transaction_type' column has values: 'revenue', 'expense', 'refund' (all lowercase).\n"
        "- The 'direction' column has values: 'inflow' (for revenue), 'outflow' (for expense/refund).\n"
        "- For revenue totals, use: WHERE transaction_type = 'revenue'.\n"
        "- For expense totals, use: WHERE transaction_type = 'expense'.\n"
        "- When the user asks for totals, also break down the amounts by source "
        "(stripe vs excel) using GROUP BY source.\n"
        "- Dates are in the 'transaction_date' column.\n"
        "- Make sure you ONLY output a read-only SELECT (or WITH) SQL query and no explanation."
        f"{history_section}"
    )


async def generate_sql_query(sql_prompt: str, settings: dict) -> str:
    """Ask the user's LLM to generate the SQL query as plain text."""
    llm = _llm_for(settings)
    response = await _llm_answer(llm, sql_prompt)
    return response.strip()


async def _execute_scoped(user_id: int, sql_prompt: str, sql_clean: str, settings: dict) -> dict:
    """Run the model's SQL through supabase-mcp, retrying once if unscopable.

    ``run_read_only_sql`` applies the org filter itself, so a query that omits
    ``user_id`` cannot be scoped. That is the one recoverable case: the model is
    asked again with an explicit instruction rather than the user seeing an error.
    """
    try:
        return await run_read_only_sql(user_id=user_id, sql=sql_clean)
    except ScopeError:
        logger.info("Regenerating SQL: projection omitted user_id (user %s)", user_id)
        retry_prompt = (
            f"{sql_prompt}\n\nIMPORTANT: your SELECT list must include the "
            f"user_id column; the query is filtered to the requesting company "
            f"using that column and cannot run without it."
        )
        sql_again = await generate_sql_query(retry_prompt, settings)
        again = sql_again.replace("```sql", "").replace("```", "").strip()
        if again.startswith("[llm error]") or again.startswith("[mock]"):
            raise RagAbort(
                "I couldn't generate a database query with the configured model. "
                "Check the model in Settings, then try again."
            ) from None
        return await run_read_only_sql(user_id=user_id, sql=again)


async def rag_response(query: str, sql_query: str, sql_result: list, settings: dict, history: list | None = None) -> str:
    """Turn the SQL result rows into a concise natural-language answer."""
    prompt = _rag_prompt(query, sql_query, sql_result, history)
    llm = _llm_for(settings)
    return await _llm_answer(llm, prompt)


async def rag_response_stream(query: str, sql_query: str, sql_result: list, settings: dict, history: list | None = None):
    """Yield chunks of the natural-language answer as they arrive."""
    prompt = _rag_prompt(query, sql_query, sql_result, history)
    llm = _llm_for(settings)
    from app.services.llm_factory import generate_text_stream
    async for chunk in generate_text_stream(llm, prompt):
        yield chunk


def _rag_prompt(query: str, sql_query: str, sql_result: list, history: list | None = None) -> str:
    """Build the prompt for the final natural-language RAG response."""
    history_block = _build_history_block(history, max_chars=500)
    history_section = ""
    if history_block:
        history_section = (
            "\n=== CONVERSATION HISTORY ===\n"
            "Previous exchanges for context:\n\n"
            f"{history_block}\n"
            "=== END HISTORY ===\n\n"
        )

    return (
        "You are a financial analyst. Use the information in the JSON table to answer "
        "the following user query. Do not explain anything, just answer concisely in "
        "natural language, not computer formatting.\n"
        f"{history_section}"
        f"USER QUERY: {query}\n\n"
        f"JSON table:\n{json.dumps(sql_result, default=str)}\n\n"
        "This table was generated by the following SQL query:\n"
        f"{sql_query}\n\n"
        "IMPORTANT: The table above contains the data needed to answer the question. "
        "Use it to provide a clear, specific answer with actual numbers and details. "
        "Only answer \"No Information\" if the table is completely empty (has zero rows)."
    )


async def _prepare_query(user_id: int, question: str) -> tuple[str, list, dict, list]:
    """Run every non-streaming step and return ``(sql, rows, settings, history)``.

    Both entry points share this: the streaming variant only differs in how the
    final answer is delivered, so the retrieval work lives in one place.
    """
    # Independent reads run concurrently; the schema call and settings lookup are
    # both thread-bound DB work.
    settings_coro = asyncio.to_thread(get_user_settings, user_id)
    schema_coro = _describe_chat_tables(user_id)
    history_coro = asyncio.to_thread(get_user_chat_history, user_id, 10)
    domain_coro = asyncio.to_thread(get_domain_user_ids, user_id)

    settings, table_specs, history, domain_user_ids = await asyncio.gather(
        settings_coro, schema_coro, history_coro, domain_coro
    )

    if not table_specs:
        raise RagAbort("No database tables available to query.")

    ranked = await rank_tables(question, table_specs, top_n=3)
    sql_prompt = make_sql_prompt(
        question, ranked, user_id=user_id, user_ids=domain_user_ids, history=history
    )
    sql = await generate_sql_query(sql_prompt, settings)
    sql_clean = sql.replace("```sql", "").replace("```", "").strip()
    if sql_clean.startswith("[llm error]") or sql_clean.startswith("[mock]"):
        logger.error("RAG SQL generation failed for user %s: %s", user_id, sql_clean[:300])
        raise RagAbort(
            "I couldn't generate a database query with the configured model. "
            "Check the model in Settings, then try again."
        )
    if not _read_only(sql_clean):
        raise RagAbort("Sorry, I can only run read-only (SELECT) queries.")

    result = await _execute_scoped(user_id, sql_prompt, sql_clean, settings)
    return sql_clean, result["rows"], settings, history


async def answer_with_rag(user_id: int, question: str) -> str:
    """Full Text-to-SQL RAG pipeline for a chat question."""
    try:
        sql_clean, rows, settings, history = await _prepare_query(user_id, question)
    except RagAbort as e:
        return e.message
    except Exception as e:
        logger.error(f"RAG query failed for user {user_id}: {e}")
        return f"Data query failed: {e}"
    return await rag_response(question, sql_clean, rows, settings, history=history)


async def answer_with_rag_stream(user_id: int, question: str):
    """Full Text-to-SQL RAG pipeline that yields the final answer as a stream.

    Non-streaming steps (schema, reranking, SQL generation, query execution)
    happen upfront. Only the final natural-language response is streamed
    token-by-token via ``yield``. This backs ``/api/chat/data-query/stream``,
    the chat entry point the frontend uses.
    """
    try:
        sql_clean, rows, settings, history = await _prepare_query(user_id, question)
    except RagAbort as e:
        yield e.message
        return
    except Exception as e:
        logger.error(f"RAG query failed for user {user_id}: {e}")
        yield f"Data query failed: {e}"
        return

    async for chunk in rag_response_stream(question, sql_clean, rows, settings, history=history):
        yield chunk