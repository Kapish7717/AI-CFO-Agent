"""Tests for the security layer: password hashing, JWT, and auth dependencies.

These run fully offline — no database or network access required.
"""

import time

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.security import (
    create_access_token,
    decode_access_token,
    get_current_user,
    get_current_user_id,
    hash_password,
    mask_secret,
    verify_password,
)
from app.services.rag import _read_only


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def test_password_hash_roundtrip():
    stored = hash_password("s3cure-password!")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("s3cure-password!", stored) is True
    assert verify_password("wrong-password", stored) is False


def test_password_hashes_are_salted():
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2  # random salt must produce distinct hashes


def test_legacy_sha256_hash_still_verifies():
    import hashlib

    salt = "aabbccddeeff0011"
    digest = hashlib.sha256(b"oldpassword" + salt.encode()).hexdigest()
    legacy = f"{salt}:{digest}"
    assert verify_password("oldpassword", legacy) is True
    assert verify_password("nope", legacy) is False


def test_verify_password_rejects_garbage():
    assert verify_password("x", None) is False
    assert verify_password("x", "") is False
    assert verify_password("x", "not-a-valid-format") is False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def test_jwt_roundtrip():
    token = create_access_token(42, "user@example.com", "Finance Head", "Jane Doe")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["email"] == "user@example.com"
    assert payload["role"] == "Finance Head"


def test_jwt_expiry_rejected():
    expired = jwt.encode(
        {"sub": "1", "exp": int(time.time()) - 10},
        key="any-key",
        algorithm="HS256",
    )
    # Expired token created with a different secret must be rejected regardless.
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(expired)


# --------------------------------------------------------------------------- #
# Masking
# --------------------------------------------------------------------------- #
def test_mask_secret():
    assert mask_secret("sk-live-1234abcd") == "sk-l…abcd"
    assert mask_secret(None) is None
    assert mask_secret("") is None
    assert mask_secret("abc") == "***"


# --------------------------------------------------------------------------- #
# Auth dependency (FastAPI)
# --------------------------------------------------------------------------- #
def _make_app():
    test_app = FastAPI()

    @test_app.get("/me")
    def me(user_id: int = Depends(get_current_user_id)):
        return {"user_id": user_id}

    @test_app.get("/claims")
    def claims(user: dict = Depends(get_current_user)):
        return {"sub": user["sub"], "email": user["email"]}

    return test_app


def test_protected_route_requires_token():
    client = TestClient(_make_app())
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_protected_route_accepts_valid_token():
    client = TestClient(_make_app())
    token = create_access_token(7, "seven@example.com", "user")
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": 7}

    claims_resp = client.get("/claims", headers={"Authorization": f"Bearer {token}"})
    assert claims_resp.json()["email"] == "seven@example.com"


# --------------------------------------------------------------------------- #
# RAG read-only SQL guard
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT * FROM transactions", True),
        ("with x as (select 1) select * from x", True),
        ("SELECT count(*) FROM unified_transactions", True),
        ("WITH x AS (DELETE FROM transactions RETURNING *) SELECT * FROM x", False),
        ("SELECT * FROM transactions; DROP TABLE transactions", False),
        ("UPDATE transactions SET amount = 0", False),
        ("INSERT INTO transactions DEFAULT VALUES", False),
        ("DELETE FROM user_settings", False),
        ("select * from transactions -- drop table x", True),  # comment is inert
    ],
)
def test_rag_read_only_guard(sql, expected):
    assert _read_only(sql) is expected


# --------------------------------------------------------------------------- #
# Endpoint-level auth gate: every /api route must reject anonymous callers
# --------------------------------------------------------------------------- #
def _make_router_app():
    from app.api import (
        agent,
        anomaly,
        auth,
        chat,
        dashboard,
        forecast,
        integrations,
        providers,
        report,
        settings,
    )

    api = FastAPI()
    for module in (auth, chat, dashboard, forecast, anomaly, integrations, providers, report, settings, agent):
        api.include_router(module.router)
    return api


# (method, path, json_body_for_POST)
_PROTECTED_ROUTES = [
    ("GET", "/api/chat/history", None),
    ("GET", "/api/v1/chat/history", None),
    ("POST", "/api/chat/data-query", {"question": "spend?", "user_id": 1}),
    ("GET", "/api/dashboard/overview", None),
    ("POST", "/api/v1/forecast", {"user_id": 1}),
    ("POST", "/api/v1/anomaly", {"user_id": 1}),
    ("POST", "/api/v1/data/connect", {"provider": "postgres"}),
    ("POST", "/api/upload", None),
    ("POST", "/api/integrations/stripe/connect", {"api_key": "sk_test_123"}),
    ("GET", "/api/integrations/stripe/status", None),
    ("POST", "/api/integrations/stripe/disconnect", None),
    ("GET", "/api/v1/providers", None),
    ("GET", "/api/v1/models?provider=groq", None),
    ("POST", "/api/v1/report", {}),
    ("GET", "/api/download-report", None),
    ("GET", "/api/user-settings", None),
    ("POST", "/api/user-settings", {}),
    ("POST", "/api/agent/run", {"to_email": "x@y.z"}),
    ("GET", "/api/auth/me", None),
    ("POST", "/api/auth/google/disconnect", None),
    ("GET", "/auth/url", None),
    ("POST", "/auth/exchange", {"code": "abc123"}),
    ("GET", "/auth/status", None),
]


@pytest.mark.parametrize("method,path,body", _PROTECTED_ROUTES, ids=[f"{m} {p}" for m, p, _ in _PROTECTED_ROUTES])
def test_protected_routes_reject_anonymous(method, path, body):
    client = TestClient(_make_router_app())
    resp = client.request(method, path, json=body if body is not None else None)
    assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"
