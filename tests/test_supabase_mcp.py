"""Tests for supabase-mcp: org scoping helpers, read/write tool internals, and
server tool registration.

Runs fully offline — DB access is patched; no Postgres/Supabase or MCP
transport is required.
"""

import datetime as dt
from decimal import Decimal
from unittest.mock import Mock

import pytest

from app.mcp.supabase import org, tools_read, tools_transactions


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


def test_read_stripe_transactions_scoped(monkeypatch, scope_patches):
    fake = _FakeConn([{"id": 1, "external_id": "re_1", "raw_payload": {"x": 1}}])
    monkeypatch.setattr(tools_read, "get_connection", lambda: fake)

    out = tools_read._read_stripe_transactions(7, 5)

    assert "WHERE user_id IN (%s, %s)" in fake.cursor_obj.executed
    assert fake.cursor_obj.params == (7, 8, 5)
    assert out[0]["raw_payload"] == {"x": 1}


def test_get_sync_status_reads_store(monkeypatch, scope_patches):
    monkeypatch.setattr(
        tools_read,
        "_store_get_sync_status",
        lambda source: {
            "source": source,
            "status": "healthy",
            "last_synced_at": dt.datetime(2026, 1, 1, 12, 0),
            "record_count": 5,
            "error_message": None,
        },
    )

    out = tools_read._read_sync_status(7, "stripe")

    assert out == {
        "source": "stripe",
        "status": "healthy",
        "last_synced_at": "2026-01-01T12:00:00",
        "record_count": 5,
        "error_message": None,
    }


# --------------------------------------------------------------------------- #
# write tools
# --------------------------------------------------------------------------- #
def test_write_transactions_normalizes_and_writes(monkeypatch, scope_patches):
    mock_write = Mock(return_value=1)
    monkeypatch.setattr(tools_transactions, "write_to_unified_store", mock_write)
    payload = [
        {
            "object": "charge",
            "id": "ch_1",
            "amount": 5000,
            "currency": "usd",
            "status": "succeeded",
            "created": 1767465600,
            "billing_details": {"name": "Acme"},
        }
    ]

    out = tools_transactions._write_transactions(7, "stripe", payload)

    assert out == {"inserted": 1, "total": 1}
    written = mock_write.call_args.args[0]
    assert written[0]["user_id"] == 7
    assert written[0]["source"] == "stripe"
    assert written[0]["amount"] == 50.0  # 5000 cents -> dollars


def test_write_transactions_empty(monkeypatch, scope_patches):
    monkeypatch.setattr(tools_transactions, "write_to_unified_store", lambda recs, user_id: 0)
    out = tools_transactions._write_transactions(7, "stripe", [])
    assert out == {"inserted": 0, "total": 0}


def test_mark_sync_status(monkeypatch, scope_patches):
    captured = {}

    def fake_update(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(tools_transactions, "update_sync_status", fake_update)

    out = tools_transactions._mark_sync_status(7, "stripe", "healthy", record_count=3)

    assert captured == {
        "source": "stripe",
        "status": "healthy",
        "record_count": 3,
        "error_message": None,
    }
    assert out == {"source": "stripe", "status": "healthy", "record_count": 3}


def test_write_stripe_transactions(monkeypatch, scope_patches):
    mock_store = Mock(return_value=2)
    monkeypatch.setattr(tools_transactions, "store_stripe_transactions", mock_store)

    out = tools_transactions._write_stripe_transactions(
        7, [{"id": "ch_1"}, {"id": "ch_2"}, {"id": "ch_3"}]
    )

    assert out == {"inserted": 2, "total": 3}
    written = mock_store.call_args.args[0]
    assert [r["id"] for r in written] == ["ch_1", "ch_2", "ch_3"]


def test_write_stripe_transactions_empty(monkeypatch, scope_patches):
    monkeypatch.setattr(tools_transactions, "store_stripe_transactions", lambda recs, user_id: 0)
    assert tools_transactions._write_stripe_transactions(7, []) == {"inserted": 0, "total": 0}


# --------------------------------------------------------------------------- #
# server registration (FastMCP transport surface lives in the tools)
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_server_registers_expected_tools():
    from app.mcp.supabase.server import mcp

    tools = await mcp.list_tools()
    assert {t.name for t in tools} == {
        "list_transactions",
        "list_stripe_transactions",
        "get_sync_status",
        "describe_table",
        "run_read_only_sql",
        "write_transactions",
        "write_stripe_transactions",
        "mark_sync_status",
    }