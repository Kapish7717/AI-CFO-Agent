"""Simple session manager for storing per-user LLM configuration.

This provides an in-memory store with a simple thread-safe API so
the rest of the backend can set/get session configs such as the
selected provider, model, and API key. It's intentionally small and
pluggable so it can later be replaced with a database-backed store.

Usage:
    from app.services.session_manager import SessionManager
    manager = SessionManager()
    manager.set_session('sess1', {'provider': 'openai', 'model': 'gpt-4', 'api_key': 'sk...'})
    cfg = manager.get_session('sess1')
"""
from __future__ import annotations

import threading
from typing import Any


class SessionManager:
	def __init__(self) -> None:
		self._lock = threading.RLock()
		self._store: dict[str, dict[str, Any]] = {}

	def set_session(self, session_id: str, config: dict[str, Any]) -> None:
		"""Create or replace a session configuration."""
		with self._lock:
			self._store[session_id] = config.copy()

	def update_session(self, session_id: str, patch: dict[str, Any]) -> None:
		"""Update keys for an existing session (creates if missing)."""
		with self._lock:
			cur = self._store.get(session_id, {})
			cur.update(patch)
			self._store[session_id] = cur

	def get_session(self, session_id: str) -> dict[str, Any] | None:
		"""Return a copy of the session config or None if not present."""
		with self._lock:
			cfg = self._store.get(session_id)
			return cfg.copy() if cfg is not None else None

	def delete_session(self, session_id: str) -> None:
		with self._lock:
			self._store.pop(session_id, None)


# A module-level default manager for convenience in small projects.
default_manager = SessionManager()


__all__ = ["SessionManager", "default_manager"]

