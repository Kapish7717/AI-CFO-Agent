"""Multi-agent LangGraph pipeline for the CFO data flows.

Step 6 shape. Two layers, so a new source or a new entry point does not edit the
other:

- ``pipeline`` — the data flow: ``stripe_ingest -> anomaly_detect`` then a
  conditional edge into ``reporting``. Deterministic, and it never talks to an
  MCP server directly.
- ``supervisor`` — ``supervisor`` reads ``trigger`` and delegates to a subgraph:
  ``new_data``/``scheduled`` enter the pipeline, ``chat`` enters the analyst.
  It holds no business logic and makes no dispatch decision.

Both are compiled in this module, so ``app.graph.graph`` is the top-level entry
point to register with LangGraph. ``app.graph.pipeline.graph`` stays available
for callers that want the data flow without routing.
"""

from app.graph.pipeline import graph as pipeline_graph
from app.graph.supervisor import graph

__all__ = ["graph", "pipeline_graph"]
