# ==========================================================
# stripe-mcp: FastMCP server (stdio transport)
# ==========================================================

from __future__ import annotations

import asyncio
import json
import threading

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stripe-mcp")

# `stripe.api_key` is a module-global in the Stripe SDK, so concurrent fetch
# calls (one long-running task per thread) must serialize the set-then-call
# sequence. Matches the concurrency characteristics of the existing sync loop.
_stripe_lock = threading.Lock()

# Stripe SDK resource names for each fetch tool.
RESSOURCES: dict[str, str] = {
    "fetch_charges": "Charge",
    "fetch_refunds": "Refund",
    "fetch_subscriptions": "Subscription",
    "fetch_transfers": "Transfer",
    "fetch_payouts": "Payout",
}


def _resolve_api_key(user_id: int, api_key: str | None) -> str:
    """Use the passed key, else load the user's stored Stripe secret key."""
    if api_key:
        return api_key.strip()
    from app.db.database import get_user_settings

    settings = get_user_settings(user_id) or {}
    key = (settings.get("stripe_secret_key") or "").strip()
    if not key:
        raise ValueError(f"No Stripe API key configured for user {user_id}")
    return key


def _obj_to_dict(obj) -> dict:
    if hasattr(obj, "to_dict_recursive"):
        return obj.to_dict_recursive()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)


def _list_objects(resource: str, api_key: str, limit: int, start_after: str | None) -> list[dict]:
    import stripe

    with _stripe_lock:
        stripe.api_key = api_key
        method = getattr(stripe, resource).list
        result = method(limit=limit, starting_after=start_after) if start_after else method(limit=limit)
    return [_obj_to_dict(o) for o in result.data]


def _fetch_sync(user_id: int, resource: str, api_key: str | None, limit: int, start_after: str | None) -> list[dict]:
    key = _resolve_api_key(user_id, api_key)
    return _list_objects(resource, key, limit, start_after)


async def _fetch(user_id, resource, api_key, limit, start_after) -> str:
    try:
        objects = await asyncio.to_thread(_fetch_sync, user_id, resource, api_key, limit, start_after)
        return json.dumps(objects)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _make_fetcher(resource: str):
    async def fetcher(
        user_id: int,
        api_key: str | None = None,
        limit: int = 100,
        start_after: str | None = None,
    ) -> str:
        return await _fetch(user_id, resource, api_key, limit, start_after)

    fetcher.__doc__ = (
        f"Fetch recent Stripe {resource.lower()} objects for the user as raw "
        f"object dicts (JSON string). Resolves the user's Stripe key from "
        f"settings unless api_key is passed. start_after: object id for paging."
    )
    return fetcher


for _name, _resource in RESSOURCES.items():
    mcp.tool(name=_name)(_make_fetcher(_resource))


__all__ = ["mcp"]

if __name__ == "__main__":
    mcp.run()