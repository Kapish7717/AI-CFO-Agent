"""supabase-mcp query tools: org scoping and SQL guard.

This is the tenant boundary for the chat. The LLM writes the SQL, so every
test here is an attempt to read data the caller must not see.
"""

import pytest

from app.mcp.supabase import tools_query
from app.mcp.supabase.sql_guard import (
    QUERYABLE_TABLES,
    ScopeError,
    assert_queryable,
    read_only,
    referenced_relations,
    scope_sql,
    strip_sql_fences,
)


class _FakeCursor:
    """Records every statement and params tuple it is handed."""

    def __init__(self, owner):
        self._owner = owner
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._owner.executed.append((sql, params))
        if "information_schema.columns" in sql:
            self._rows = [
                {"column_name": "id", "data_type": "integer"},
                {"column_name": "user_id", "data_type": "integer"},
                {"column_name": "amount", "data_type": "numeric"},
            ]
        return self

    def fetchall(self):
        return self._rows

    def fetchmany(self, size):
        return self._rows[:size]


class _FakeConnection:
    def __init__(self, owner):
        self._owner = owner
        self.executed = owner.executed

    def cursor(self):
        return _FakeCursor(self._owner)

    def set_session(self, **kwargs):
        self._owner.sessions.append(kwargs)

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    """A stand-in connection plus a stubbed org scope of users [4, 7]."""
    class _Holder:
        def __init__(self):
            self.executed = []
            self.sessions = []

    holder = _Holder()
    monkeypatch.setattr(tools_query, "get_connection", lambda: _FakeConnection(holder))
    monkeypatch.setattr(tools_query, "resolve_org_scope", lambda user_id: [4, 7])
    return holder


def _last_query(holder):
    """The scoped statement, i.e. the last one that is not SET LOCAL."""
    for sql, params in reversed(holder.executed):
        if not sql.startswith("SET LOCAL"):
            return sql, params
    raise AssertionError("no query executed")


# --------------------------------------------------------------------------- #
# read_only guard
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT 1", True),
        ("  with x as (select 1) select * from x ", True),
        ("SELECT * FROM unified_transactions;", True),
        ("SELECT * FROM unified_transactions WHERE a = 'drop table'", True),
        ("-- select\nSELECT 1", True),
        ("DELETE FROM unified_transactions", False),
        ("INSERT INTO unified_transactions VALUES (1)", False),
        ("UPDATE unified_transactions SET amount = 0", False),
        ("SELECT 1; DROP TABLE unified_transactions", False),
        ("SELECT * INTO evil FROM unified_transactions", False),
        ("COPY unified_transactions TO '/tmp/x'", False),
        ("SET search_path = public", False),
        # Blocked functions are read-only in form; assert_queryable rejects them.
        ("SELECT lo_import('/etc/passwd')", True),
        ("", False),
    ],
)
def test_read_only(sql, expected):
    assert read_only(sql) is expected


def test_strip_sql_fences():
    assert strip_sql_fences("```sql\nSELECT 1\n```") == "SELECT 1"
    assert strip_sql_fences("SELECT 1;") == "SELECT 1"
    assert strip_sql_fences("  ```\nSELECT 2;\n```  ") == "SELECT 2"


# --------------------------------------------------------------------------- #
# relation allowlist
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT user_id FROM user_settings",
        "SELECT user_id FROM public.user_settings",
        "SELECT user_id FROM information_schema.tables",
        "SELECT user_id FROM pg_catalog.pg_class",
        "SELECT user_id FROM unified_transactions JOIN user_settings USING (user_id)",
        "SELECT user_id FROM unified_transactions u JOIN stripe_transactions s ON s.user_id = u.user_id",
    ],
)
def test_non_queryable_relations_are_rejected(sql):
    with pytest.raises(ValueError):
        assert_queryable(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT user_id FROM unified_transactions",
        "WITH recent AS (SELECT user_id FROM unified_transactions) SELECT * FROM recent",
        "SELECT user_id FROM unified_transactions ORDER BY transaction_date DESC",
    ],
)
def test_queryable_relations_are_accepted(sql):
    assert_queryable(sql)


def test_cte_aliases_are_not_treated_as_tables():
    sql = "WITH mine AS (SELECT user_id FROM unified_transactions) SELECT * FROM mine"
    assert referenced_relations(sql) == {"unified_transactions"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT user_id, lo_import('/etc/passwd') FROM unified_transactions",
        "SELECT user_id FROM unified_transactions WHERE x = pg_sleep(10)",
        "SELECT user_id FROM unified_transactions, dblink('x', 'y')",
    ],
)
def test_dangerous_functions_are_rejected(sql):
    with pytest.raises(ValueError):
        assert_queryable(sql)


def test_queryable_tables_is_only_the_unified_table():
    assert QUERYABLE_TABLES == ("unified_transactions",)


# --------------------------------------------------------------------------- #
# scope_sql
# --------------------------------------------------------------------------- #
def test_scope_sql_wraps_with_the_org_filter():
    scoped = scope_sql("SELECT user_id, amount FROM unified_transactions", [4, 7])

    assert scoped == (
        "SELECT * FROM (SELECT user_id, amount FROM unified_transactions) AS _scoped "
        "WHERE _scoped.user_id IN (%s, %s) LIMIT %s"
    )


def test_scope_sql_caps_rows_in_sql():
    """The cap must be applied by Postgres, not by slicing in Python."""
    assert scope_sql("SELECT user_id FROM unified_transactions", [4]).endswith("LIMIT %s")


def test_scope_sql_requires_user_id_in_the_projection():
    with pytest.raises(ScopeError):
        scope_sql("SELECT SUM(amount) FROM unified_transactions", [4, 7])


def test_scope_sql_does_not_trust_the_models_own_filter():
    """A model-written filter for another user is still bounded by the org scope."""
    scoped = scope_sql(
        "SELECT user_id, amount FROM unified_transactions WHERE user_id = 999", [4, 7]
    )
    assert "_scoped.user_id IN (%s, %s)" in scoped
    assert "user_id = 999" in scoped


# --------------------------------------------------------------------------- #
# describe_table
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_describe_table_returns_create_table_text(fake_db):
    specs = await tools_query.describe_table(4)

    assert len(specs) == 1
    assert specs[0].startswith("CREATE TABLE unified_transactions (")
    assert "user_id integer" in specs[0]


@pytest.mark.anyio
async def test_describe_table_refuses_other_tables(fake_db):
    with pytest.raises(ValueError):
        await tools_query.describe_table(4, "user_settings")


# --------------------------------------------------------------------------- #
# run_read_only_sql
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_run_read_only_sql_binds_the_org_scope(fake_db):
    result = await tools_query.run_read_only_sql(
        4, "SELECT user_id, amount FROM unified_transactions"
    )

    sql, params = _last_query(fake_db)
    assert "_scoped.user_id IN (%s, %s)" in sql
    # 4 and 7 for the scope, then the row cap.
    assert params == (4, 7, tools_query.MAX_ROWS + 1)
    assert set(result) == {"rows", "row_count", "truncated"}


@pytest.mark.anyio
async def test_run_read_only_sql_uses_a_readonly_transaction(fake_db):
    await tools_query.run_read_only_sql(4, "SELECT user_id, amount FROM unified_transactions")

    assert {"readonly": True} in fake_db.sessions
    assert any(sql.startswith("SET LOCAL statement_timeout") for sql, _ in fake_db.executed)


@pytest.mark.anyio
async def test_run_read_only_sql_caps_rows(fake_db, monkeypatch):
    """A runaway result set is truncated at the cap rather than returned whole."""
    many = [{"user_id": 4, "amount": 1}]

    class _ManyRows(_FakeCursor):
        def fetchmany(self, size):
            return many * (size + 1)

    def _conn():
        conn = _FakeConnection(fake_db)
        conn.cursor = lambda: _ManyRows(fake_db)
        return conn

    monkeypatch.setattr(tools_query, "get_connection", _conn)

    result = await tools_query.run_read_only_sql(
        4, "SELECT user_id, amount FROM unified_transactions", max_rows=5
    )

    assert result["row_count"] == 5
    assert len(result["rows"]) == 5
    assert result["truncated"] is True


@pytest.mark.anyio
async def test_run_read_only_sql_rejects_mutations(fake_db):
    with pytest.raises(ValueError):
        await tools_query.run_read_only_sql(4, "DELETE FROM unified_transactions")
    assert fake_db.executed == [], "rejected SQL must not reach the database"


@pytest.mark.anyio
async def test_run_read_only_sql_rejects_other_tables(fake_db):
    with pytest.raises(ValueError):
        await tools_query.run_read_only_sql(4, "SELECT user_id, api_key FROM user_settings")
    assert fake_db.executed == []


@pytest.mark.anyio
async def test_run_read_only_sql_rejects_unscopable_projection(fake_db):
    with pytest.raises(ScopeError):
        await tools_query.run_read_only_sql(4, "SELECT SUM(amount) FROM unified_transactions")


@pytest.mark.anyio
async def test_run_read_only_sql_refuses_an_unknown_caller(monkeypatch):
    """A caller id that does not exist must not fall back to an empty scope."""

    def _boom(user_id):
        raise ValueError("No user found with id 999")

    monkeypatch.setattr(tools_query, "resolve_org_scope", _boom)

    with pytest.raises(ValueError):
        await tools_query.run_read_only_sql(999, "SELECT user_id FROM unified_transactions")


@pytest.mark.anyio
async def test_server_registers_the_query_tools():
    from app.mcp.supabase.server import mcp

    names = {tool.name for tool in await mcp.list_tools()}

    assert {"describe_table", "run_read_only_sql"} <= names
