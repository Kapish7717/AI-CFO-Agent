"""stripe-mcp: fetch tools for the Stripe data source.

Launch (stdio transport, consumed over MCP by the ingestion node)::

    python -m app.mcp.stripe.server

Each tool resolves the user's Stripe API key from ``user_settings`` (falling
back to an explicitly passed key) and returns the raw Stripe object dicts as a
JSON string, ready to be handed to supabase-mcp write tools.
"""