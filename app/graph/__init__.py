"""Multi-agent LangGraph pipeline for the CFO data flows.

Current graph (Step 3): a single deterministic node ``stripe_ingest`` that
fetches from stripe-mcp and persists through supabase-mcp. Later steps add the
anomaly node, reporting node, and a supervisor that routes on trigger type.
"""