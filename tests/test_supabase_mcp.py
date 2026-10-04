"""Tests for supabase-mcp: org scoping helpers, read tool internals, and server
tool registration.

Runs fully offline — DB access is patched; no Postgres/Supabase or MCP
transport is required.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.mcp.supabase import org, tools_read


# --------------------------------------------------------------------------- #
# org scoping helpers
# --------------------------------------------------------------------------- #
def test_resolve_org_scope_expands_to_domain(monkeypatch):
    monkeypatch.setattr(
        org, "get_user_by_id", lambda uid: {"id": uid, "email": f"u{uid}@acme.com"}
    )
    monkeypatch.setattr(org, "get_domain_user_ids", lambda uid: [uid, 2, 3])
    assert org.resolve_org_scope(41) == [41, 2, 3]


def test_resolve_org_scope_isolates_domainless_user(monkeypatch):
    monkeypatch.setattr(org, "get_user_by_id", lambda uid: {"id": uid})
    monkeypatch.setattr(org, "get_domain_user_ids", lambda uid: [uid])
    assert org.resolve_org_scope(9) == [9]


def test_resolve_org_scope_rejects_unknown_user(monkeypatch):
    monkeypatch.setattr(org, "get_user_by_id", lambda uid: None)
    with pytest.raises(ValueError):
        org.resolve_org_scope(999)


def test_resolve_org_scope_rejects_missing_user_id():
    with pytest.raises(ValueError):
        org.resolve_org_scope(None)


def test_jsonable_converts_row_types():
    row = {
        "amount": Decimal("12.34"),
        "transaction_date": dt.datetime(2026, 1, 2, 3, 4, 5),
        "raw_payload": {"nested": [Decimal("1.5")], "blob": b"xx"},
    }
    out = org.jsonable(row)
    assert out["amount"] == 12.34
    assert out["transaction_date"] == "2026-01-02T03:04:05"
    assert out["raw_payload"] == {"nested": [1.5], "blob": "xx"}


# --------------------------------------------------------------------------- #
# read tools (org scoping + query building)
# --------------------------------------------------------------------------- #
class _FakeRowsCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed = sql
        self.params = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.cursor_obj = None

    def cursor(self):
        self.cursor_obj = _FakeRowsCursor(self._rows)
        return self.cursor_obj

    def close(self):
        pass


@pytest.fixture
def scope_patches(monkeypatch):
    monkeypatch.setattr(org, "get_user_by_id", lambda uid: {"id": uid})
    monkeypatch.setattr(org, "get_domain_user_ids", lambda uid: [uid, uid + 1])
    return [7, 8]


def test_read_org_transactions_scopes_and_filters(monkeypatch, scope_patches):
    fake = _FakeConn(
        [
            {
                "id": 10,
                "user_id": 7,
                "external_id": "ch_1",
                "source": "stripe",
                "transaction_type": "revenue",
                "direction": "inflow",
                "amount": Decimal("50.0"),
                "currency": "USD",
                "transaction_date": None,
                "description": "sale",
                "category": "revenue",
                "counterparty": "Acme",
                "status": "succeeded",
                "payment_method": "card",
            }
        ]
    )
    monkeypatch.setattr(tools_read, "get_connection", lambda: fake)

    out = tools_read._read_org_transactions(7, 25, source="stripe")

    assert fake.cursor_obj.executed is not None
    assert "WHERE user_id IN (%s, %s)" in fake.cursor_obj.executed
    assert "AND source = %s" in fake.cursor_obj.executed
    assert fake.cursor_obj.params == (7, 8, "stripe", 25)
    assert out[0]["amount"] == 50.0


def test_read_org_transactions_includes_date_bounds(monkeypatch, scope_patches):
    fake = _FakeConn([])
    monkeypatch.setattr(tools_read, "get_connection", lambda: fake)

    tools_read._read_org_transactions(
        7, 10, start_date="2026-01-01", end_date="2026-01-31"
    )

    sql = fake.cursor_obj.executed
    assert "transaction_date >= %s" in sql
    assert "transaction_date <= %s" in sql
    assert fake.cursor_obj.params == (7, 8, "2026-01-01", "2026-01-31", 10)


@pytest.mark.parametrize("bad", ["2026-13-45", "01/31/2026", "yesterday", "2026-99-99"])
def test_read_org_transactions_rejects_malformed_date_bounds(
    monkeypatch, scope_patches, bad
):
    # A typo is a valid string to parameterize, so without validation the query
    # runs and returns zero rows, which reads as "no transactions" rather than
    # "bad filter".
    fake = _FakeConn([])
    monkeypatch.setattr(tools_read, "get_connection", lambda: fake)

    with pytest.raises(ValueError, match="ISO date"):
        tools_read._read_org_transactions(7, 10, start_date=bad)
    # No query was ever issued, so this cannot be mistaken for an empty result.
    assert fake.cursor_obj is None


def test_read_org_transactions_accepts_a_full_timestamp_bound(
    monkeypatch, scope_patches
):
    fake = _FakeConn([])
    monkeypatch.setattr(tools_read, "get_connection", lambda: fake)

    tools_read._read_org_transactions(7, 10, start_date="2026-01-01T09:30:00")
    assert "transaction_date >= %s" in fake.cursor_obj.executed


def test_read_org_transactions_allows_absent_bounds(monkeypatch, scope_patches):
    fake = _FakeConn([])
    monkeypatch.setattr(tools_read, "get_connection", lambda: fake)

    tools_read._read_org_transactions(7, 10)
    assert "transaction_date >=" not in fake.cursor_obj.executed



# --------------------------------------------------------------------------- #
# server registration (FastMCP transport surface lives in the tools)
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_server_registers_expected_tools():
    from app.mcp.supabase.server import mcp

    tools = await mcp.list_tools()
    # Read-only by construction: writes happen in the sync loop, the webhook and
    # the upload ingest, none of which go through MCP.
    assert {t.name for t in tools} == {
        "list_transactions",
        "describe_table",
        "run_read_only_sql",
    }
