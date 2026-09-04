"""End-to-end tests for the Text-to-SQL RAG chat pipeline.

The RAG service (``app/services/rag.py``) is the single data-querying path for
the AI Chat. These tests run the full pipeline offline against an in-memory
SQLite database (with the schema introspection query canned) and a stubbed LLM:

    extract schema -> rank tables -> generate SQL -> read-only guard ->
    execute -> natural-language answer.

This replaces the coverage that the removed ``query_financial_data`` MCP tool
used to provide for data questions.
"""

import sqlite3
from unittest.mock import patch

import pytest

from app.services import rag

SCHEMA_ROWS = [
    {"table_name": "transactions", "column_name": "user_id", "data_type": "integer"},
    {"table_name": "transactions", "column_name": "category", "data_type": "text"},
    {"table_name": "transactions", "column_name": "amount", "data_type": "numeric"},
    {"table_name": "transactions", "column_name": "type", "data_type": "text"},
    {"table_name": "transactions", "column_name": "date", "data_type": "date"},
    {"table_name": "unified_transactions", "column_name": "id", "data_type": "integer"},
    {"table_name": "user_settings", "column_name": "user_id", "data_type": "integer"},
    {"table_name": "user_settings", "column_name": "report_email", "data_type": "text"},
]


class _FakeCursor:
    """Canned schema introspection + delegated SQL execution on SQLite."""

    def __init__(self, sqlite_conn):
        self._cur = sqlite_conn.cursor()
        self._rows = []

    def execute(self, sql: str):
        if "information_schema.columns" in sql:
            self._rows = list(SCHEMA_ROWS)
        else:
            self._cur.execute(sql)
            self._rows = [dict(r) for r in self._cur.fetchall()]
        return self

    def fetchall(self):
        return self._rows


class _FakeConnection:
    """Minimal stand-in for a DB connection with a Postgres-like cursor.

    Exposes the surface ``app/services/rag.py`` touches: ``cursor``,
    ``set_session``, ``rollback`` and ``close``.
    """

    def __init__(self):
        self._sqlite = sqlite3.connect(":memory:")
        self._sqlite.row_factory = sqlite3.Row
        self._sqlite.executescript(
            "CREATE TABLE transactions (user_id INTEGER, category TEXT, amount NUMERIC, type TEXT, date TEXT);"
            "INSERT INTO transactions VALUES (1, 'Marketing', 1200, 'Expense', '2026-01-05');"
            "INSERT INTO transactions VALUES (1, 'Payroll', 5000, 'Expense', '2026-01-10');"
            "INSERT INTO transactions VALUES (1, 'Sales', 8000, 'Revenue', '2026-01-15');"
        )

    def cursor(self):
        return _FakeCursor(self._sqlite)

    def set_session(self, *args, **kwargs):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _stub_pipeline(monkeypatch, fake_generate_text):
    """Wire the RAG pipeline to the fake connection + stubbed LLM."""
    monkeypatch.setattr(rag, "get_connection", lambda: _FakeConnection())
    monkeypatch.setattr(rag, "get_user_settings", lambda user_id: {"llm_primary_provider": "mock", "api_key": ""})
    monkeypatch.setattr(rag, "JINA_API_KEY", "")
    return patch("app.services.llm_factory.generate_text", fake_generate_text)


async def _realistic_llm(model, prompt: str) -> str:
    """Stub LLM: writes SQL for the schema prompt, answers for the response prompt."""
    if "Generate a SQL query" in prompt:
        return (
            "SELECT category, SUM(amount) AS total FROM transactions "
            "WHERE type = 'Expense' GROUP BY category"
        )
    return "Total expense by category: Marketing $1200, Payroll $5000."


# --------------------------------------------------------------------------- #
# Pipeline pieces
# --------------------------------------------------------------------------- #
def test_extract_schema_returns_preferred_tables():
    specs = rag.extract_schema(_FakeConnection())
    joined = "\n".join(specs)
    assert "CREATE TABLE transactions" in joined
    assert "CREATE TABLE unified_transactions" in joined
    assert "CREATE TABLE user_settings" not in joined


def test_rank_tables_returns_unranked_without_key(monkeypatch):
    monkeypatch.setattr(rag, "JINA_API_KEY", "")
    specs = ["CREATE TABLE transactions (id int);", "CREATE TABLE user_settings (id int);"]
    ranked = rag.rank_tables("marketing spend", specs)
    assert len(ranked) == 2
    assert all(score == 0.0 for score, _ in ranked)


def test_sql_response_executes_select():
    conn = _FakeConnection()
    rows = rag.sql_response(
        "SELECT category, SUM(amount) AS total FROM transactions GROUP BY category",
        conn,
    )
    totals = {r["category"]: r["total"] for r in rows}
    assert totals == {"Marketing": 1200.0, "Payroll": 5000.0, "Sales": 8000.0}


# --------------------------------------------------------------------------- #
# End-to-end
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_rag_pipeline_end_to_end(monkeypatch):
    """Full pipeline: schema -> SQL -> execute -> grounded answer."""
    with _stub_pipeline(monkeypatch, _realistic_llm):
        answer = await rag.answer_with_rag(user_id=1, question="How much did we spend on Marketing?")
    assert "Marketing $1200" in answer


@pytest.mark.anyio
async def test_rag_pipeline_rejects_mutating_sql(monkeypatch):
    """A non-SELECT query generated by the LLM must be refused before execution."""

    async def _bad_sql(model, prompt: str) -> str:
        return "DELETE FROM transactions"

    with _stub_pipeline(monkeypatch, _bad_sql):
        answer = await rag.answer_with_rag(user_id=1, question="delete everything")
    assert "read-only" in answer


@pytest.mark.anyio
async def test_rag_pipeline_rejects_chained_statements(monkeypatch):
    """Multi-statement payloads must be refused even if they start with SELECT."""

    async def _chained_sql(model, prompt: str) -> str:
        return "SELECT * FROM transactions; DROP TABLE transactions"

    with _stub_pipeline(monkeypatch, _chained_sql):
        answer = await rag.answer_with_rag(user_id=1, question="anything")
    assert "read-only" in answer