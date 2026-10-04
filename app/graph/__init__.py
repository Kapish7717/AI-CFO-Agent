"""Multi-agent LangGraph pipeline for the CFO data flows.

Every entry point in the app goes through the supervisor: the scheduler
(``app/main.py``), the manual run endpoint (``app/api/agent.py``) and chat
(``app/api/chat.py``) all invoke ``app.graph.graph`` with a different
``trigger``. Two layers, so a new source or a new entry point does not edit the
other:

- ``pipeline`` — the data flow: ``anomaly_detect`` then a conditional edge into
  ``reporting``. Deterministic, read-only against Supabase, and it never talks to
  an MCP server directly.
- ``supervisor`` — ``supervisor`` reads ``trigger`` and delegates to a subgraph:
  ``new_data``/``scheduled`` enter the pipeline, ``chat`` enters the analyst.
  It holds no business logic and makes no dispatch decision.

``app.graph.graph`` (the supervisor) is the only entry point to register with
LangGraph; ``langgraph.json`` points at it. ``app.graph.pipeline_graph`` stays
available for callers that want the data flow without routing.
"""

from app.graph.pipeline import graph as pipeline_graph
from app.graph.supervisor import graph

__all__ = ["graph", "pipeline_graph"]
