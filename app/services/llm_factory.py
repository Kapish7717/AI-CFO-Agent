"""Lightweight LLM factory that returns provider-specific client wrappers.

This module exposes `create_llm` which returns an object with a single
async method `agenerate(prompt, **kwargs)` that yields a text response.

Only a minimal subset of providers is implemented here (OpenAI via
the REST API and a simple local `mock` provider). Add other providers
by adding new factory branches — the code is intentionally small and
keeps provider logic isolated.
"""
from __future__ import annotations

import asyncio
from typing import Any

# Try to import popular langchain chat model wrappers. If they're not
# available the factory will fall back to a simple mock implementation.
try:
	from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency
	ChatOpenAI = None

try:
	from langchain_groq import ChatGroq
except Exception:  # pragma: no cover
	ChatGroq = None

try:
	from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:  # pragma: no cover
	ChatGoogleGenerativeAI = None

try:
	from langchain_anthropic import ChatAnthropic
except Exception:  # pragma: no cover
	ChatAnthropic = None

try:
	from langchain.schema import HumanMessage
except Exception:  # pragma: no cover - fallback when langchain is not installed
	class HumanMessage:
		def __init__(self, content: str):
			self.content = content


class _MockModel:
	async def agenerate(self, messages: Any):
		await asyncio.sleep(0)
		text = "\n".join(m.content for m in (messages[0] if isinstance(messages, list) and messages else [HumanMessage(content=str(messages))]))
		return "[mock] " + text


class _FallbackModel:
	"""Wrapper that tries the primary LLM and transparently retries with a
	fallback LLM when the primary raises or returns an error.

	Exposes the same async/sync entry points used by ``generate_text`` so the
	wrapper can be dropped in anywhere a single LLM object is expected.
	"""

	def __init__(self, primary: Any, fallback: Any | None = None):
		self._primary = primary
		self._fallback = fallback

	async def _amethod(self, name: str, *args: Any, **kwargs: Any):
		last_err = None
		for model in (self._primary, self._fallback):
			if model is None:
				continue
			fn = getattr(model, name, None)
			if fn is None:
				continue
			try:
				return await fn(*args, **kwargs)
			except Exception as e:
				last_err = e
		raise RuntimeError(f"Both primary and fallback LLM calls failed: {last_err}")

	def _method(self, name: str, *args: Any, **kwargs: Any):
		last_err = None
		for model in (self._primary, self._fallback):
			if model is None:
				continue
			fn = getattr(model, name, None)
			if fn is None:
				continue
			try:
				return fn(*args, **kwargs)
			except Exception as e:
				last_err = e
		raise RuntimeError(f"Both primary and fallback LLM calls failed: {last_err}")

	async def ainvoke(self, *a: Any, **kw: Any):
		return await self._amethod("ainvoke", *a, **kw)

	async def agenerate(self, *a: Any, **kw: Any):
		return await self._amethod("agenerate", *a, **kw)

	def invoke(self, *a: Any, **kw: Any):
		return self._method("invoke", *a, **kw)

	def predict(self, *a: Any, **kw: Any):
		return self._method("predict", *a, **kw)

	def generate(self, *a: Any, **kw: Any):
		return self._method("generate", *a, **kw)


def create_llm_with_fallback(cfg: dict[str, Any]):
	"""Create an LLM that falls back to a secondary provider when the primary fails.

	``cfg`` mirrors the session/user settings keys: ``provider``/``model`` are used
	as the primary; ``llm_fallback_provider``/``llm_fallback_model`` (or their
	``provider``/``model`` fallbacks on user settings) drive the secondary.
	"""
	primary_provider = cfg.get("provider") or cfg.get("llm_primary_provider") or "mock"
	primary_model = cfg.get("model") or cfg.get("llm_primary_model")
	primary = create_llm(
		provider=primary_provider,
		model=primary_model,
		api_key=cfg.get("api_key"),
		**cfg.get("llm_kwargs", {}),
	)

	fallback = None
	fallback_provider = cfg.get("llm_fallback_provider")
	if fallback_provider:
		try:
			fallback = create_llm(
				provider=fallback_provider,
				model=cfg.get("llm_fallback_model"),
				api_key=cfg.get("fallback_api_key") or cfg.get("api_key"),
			)
		except Exception:
			fallback = None

	return _FallbackModel(primary, fallback)


def create_llm(provider: str, model: str | None = None, api_key: str | None = None, **kwargs: Any):
	"""Return a provider-specific LangChain chat model instance.

	Supported providers (if their packages are installed):
	  - openai
	  - groq
	  - gemini
	  - anthropic
	  - mock (fallback)

	Additional provider-specific kwargs are forwarded to the model constructor.
	"""
	provider = (provider or "").lower()

	if provider in ("mock", "local", "none", "test"):
		return _MockModel()

	if provider == "openai":
		if ChatOpenAI is None:
			raise RuntimeError("ChatOpenAI is not available; install langchain and openai extras")
		init = {"model_name": model} if model else {}
		if api_key:
			init["openai_api_key"] = api_key
		init.update(kwargs)
		return ChatOpenAI(**init)

	if provider == "groq":
		if ChatGroq is None:
			raise RuntimeError("ChatGroq is not available; install langchain-groq")
		init = {"model": model} if model else {}
		if api_key:
			init["groq_api_key"] = api_key
		init.update(kwargs)
		return ChatGroq(**init)

	if provider in ("gemini", "google", "google_genai"):
		if ChatGoogleGenerativeAI is None:
			raise RuntimeError("ChatGoogleGenerativeAI is not available; install langchain-google-genai")
		init = {"model": model} if model else {}
		if api_key:
			init["google_api_key"] = api_key
		init.update(kwargs)
		return ChatGoogleGenerativeAI(**init)

	if provider in ("anthropic",):
		if ChatAnthropic is None:
			raise RuntimeError("ChatAnthropic is not available; install langchain-anthropic")
		init = {"model": model} if model else {}
		if api_key:
			init["api_key"] = api_key
		init.update(kwargs)
		return ChatAnthropic(**init)

	raise NotImplementedError(f"LLM provider '{provider}' is not implemented in llm_factory")


def _extract_text(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, str):
		return value
	if isinstance(value, (list, tuple)):
		if not value:
			return ""
		return _extract_text(value[0])
	if isinstance(value, dict):
		if "content" in value:
			return _extract_text(value["content"])
		if "text" in value:
			return _extract_text(value["text"])
		if value:
			return _extract_text(next(iter(value.values())))
	if hasattr(value, "content"):
		return _extract_text(value.content)
	if hasattr(value, "text"):
		return _extract_text(value.text)
	if hasattr(value, "message"):
		return _extract_text(value.message)
	if hasattr(value, "generations"):
		gens = value.generations
		return _extract_text(gens)
	if hasattr(value, "content"):  # fallback for some response objects
		return _extract_text(value.content)
	return str(value)


async def generate_text(model: Any, prompt: str) -> str:
	"""Robust helper to generate text from a LangChain-like chat model.

	This attempts several common async interfaces used by LangChain
	chat models and falls back to synchronous calls when necessary.
	Transient failures (rate limits, timeouts) are retried up to
	``MAX_RETRIES`` times with exponential backoff.
	"""
	import random

	MAX_RETRIES = 3

	async def _invoke_once():
		# Prefer provider-specific async helpers first.
		if hasattr(model, "ainvoke"):
			try:
				return await model.ainvoke([{"role": "user", "content": prompt}])
			except TypeError:
				return await model.ainvoke(prompt)

		if hasattr(model, "agenerate"):
			try:
				return await model.agenerate([HumanMessage(content=prompt)])
			except TypeError:
				return await model.agenerate(prompt)

		if hasattr(model, "invoke"):
			return await asyncio.to_thread(lambda: model.invoke([{"role": "user", "content": prompt}]))

		if hasattr(model, "predict"):
			return await asyncio.to_thread(lambda: model.predict(prompt))

		if hasattr(model, "generate"):
			return await asyncio.to_thread(lambda: model.generate([HumanMessage(content=prompt)]))

		raise RuntimeError("Unsupported model interface")

	async def _extract():
		result = await _invoke_once()

		if hasattr(model, "agenerate"):
			gens = getattr(result, "generations", None)
			if gens:
				return _extract_text(gens)
		return _extract_text(result)

	attempt = 0
	while True:
		attempt += 1
		try:
			return await _extract()
		except Exception as e:
			if attempt >= MAX_RETRIES:
				return f"[llm error] {e}"  # pragma: no cover - runtime fallback
			# Transient failure: back off, then retry.
			await asyncio.sleep(min(0.5 * (2 ** (attempt - 1)), 4) + random.uniform(0, 0.2))


__all__ = ["create_llm", "create_llm_with_fallback", "generate_text"]

