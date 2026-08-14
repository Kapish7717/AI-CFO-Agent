"""List available models for a provider.

Usage:
    python scripts/model_options.py [provider] [api_key]

The API key is read from the `GROQ_API_KEY` (groq), `OPENAI_API_KEY` (openai),
`GEMINI_API_KEY` (gemini), or `OPENROUTER_API_KEY` (openrouter) environment
variables, or can be passed as the second CLI argument.
"""

import os
import sys

import requests


def list_models(provider: str = "groq", api_key: str = None):
    provider = provider.lower()
    api_key = (api_key or "").strip() or {
        "groq": os.environ.get("GROQ_API_KEY", ""),
        "openai": os.environ.get("OPENAI_API_KEY", ""),
        "openrouter": os.environ.get("OPENROUTER_API_KEY", ""),
        "gemini": os.environ.get("GEMINI_API_KEY", ""),
        "google": os.environ.get("GEMINI_API_KEY", ""),
    }.get(provider, "")

    if not api_key:
        sys.exit(f"[ERROR] No API key provided for provider '{provider}'. "
                 "Pass one as the second argument or set the matching environment variable.")

    if provider in ("gemini", "google"):
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {}
        params = {"key": api_key}
    else:
        base = {
            "groq": "https://api.groq.com/openai/v1",
            "openai": "https://api.openai.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
        }.get(provider)
        if not base:
            sys.exit(f"[ERROR] Unsupported provider '{provider}'.")
        url = f"{base}/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {}

    response = requests.get(url, headers=headers, params=params, timeout=15)

    if response.status_code != 200:
        sys.exit(f"[ERROR] {response.status_code}: {response.text}")

    data = response.json().get("data", [])
    if provider in ("gemini", "google"):
        models = sorted({m["name"].split("/")[-1] for m in data if m.get("name")})
    else:
        models = sorted({m["id"] for m in data if m.get("id")})

    print(f"Found {len(models)} models:\n")
    for model in models:
        print(model)


if __name__ == "__main__":
    provider = sys.argv[1] if len(sys.argv) > 1 else "groq"
    api_key = sys.argv[2] if len(sys.argv) > 2 else None
    list_models(provider, api_key)
