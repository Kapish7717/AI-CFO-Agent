# MCP Servers & Agent Node Flow

Simple reference for how MCP servers are wired and how a request travels through the graph.

---

## 1. MCP Servers — 3 total

All are **FastMCP**, all use **stdio** transport (spawned as Python subprocesses).

| # | Server | File | Tools |
|---|---|---|---|
| 1 | `supabase-mcp` | `app/mcp/supabase/server.py:20` | `list_transactions`, `describe_table`, `run_read_only_sql` |
| 2 | `reporting-mcp` | `app/mcp/reporting/server.py:32` | `generate_cfo_pdf_report`, `send_email_report`, `schedule_budget_review` |
| 3 | `CFO_Central_Server` (legacy) | `app/agents/mcp_server.py:25` | `authenticate_google`, `ingest_financial_data`, `detect_financial_anomalies`, `generate_cfo_pdf_report`, `send_email_report`, `schedule_meeting` |

**Only #1 and #2 are connected to the graph** (`app/graph/mcp_client.py:14`). #3 is the old
implementation library that `reporting-mcp` wraps — plus direct imports from some API routes.
It is not a live MCP server in the graph.

So the agent sees **6 tools total**.

### Tool detail

**`supabase-mcp`** (read-only, org-scoped)
- `list_transactions(user_id, source, category, direction, transaction_type, start_date, end_date, limit)`
  Reads `unified_transactions` scoped to the user's whole org via `resolve_org_scope`.
- `describe_table(user_id, table_name)`
  Returns `CREATE TABLE`-style schema for whitelisted tables only (`QUERYABLE_TABLES`).
- `run_read_only_sql(user_id, sql, max_rows)`
  Model-written SQL. Guards: read-only check, table whitelist, org scoping, PG `readonly=True`,
  `statement_timeout = 15000ms`.

**`reporting-mcp`** (thin `dict`-returning wrappers over the legacy central server)
- `generate_cfo_pdf_report(user_id, custom_instructions, start_date, end_date, report_months)`
  Builds the executive CFO PDF via `ReportGenerator`, uploads to Supabase Storage.
- `send_email_report(user_id, to_email, subject, body)`
  Gmail send with the PDF attached + budget breach warning if a breaches file exists.
- `schedule_budget_review(user_id, attendees, start_time, end_time)`
  Google Calendar event in `Asia/Kolkata`.

### Client wiring

`app/graph/mcp_client.py`
- `MCP_SERVERS` map (`:14-27`) — `supabase` and `reporting`, both `transport: "stdio"`,
  launched via `sys.executable -m app.mcp.<name>.server`.
- `get_pipeline_tools()` (`:33-48`) — builds a `MultiServerMCPClient`, calls `get_tools()`,
  caches in module globals. **Returns `[]` on failure** so nodes degrade to an explicit error
  record instead of crashing the run.

---

## 2. The Node Flow, Simply

```
Request comes in (scheduler / POST /api/agent/run / chat endpoint)
        │
        ▼
   ┌─────────────┐
   │ supervisor  │  ← looks at state["trigger"], picks one path
   └──────┬──────┘
          │  "new_data" or "scheduled" ──▶ pipeline      │  "chat" ──▶ analyst
          │                                              │
   ┌──────▼───────────────────────┐              ┌───────▼────────┐
   │ 1. anomaly_detect            │              │    analyst     │
   │    ⚡ MCP: list_transactions │              │ (chat/RAG,     │
   │       → supabase-mcp        │              │  no MCP call)  │
   │    → runs detector, no LLM  │              └───────┬────────┘
   └──────┬───────────────────────┘                      │
          │                                              ▼
          │ found anomalies? (or force_report)            END
          ├── no ──▶ END
          ▼ yes
   ┌──────────────────────┐
   │ 2. reporting         │
   │  ⚡ MCP: generate_cfo_pdf_report  │
   │  ⚡ MCP: send_email_report  (if recipient)
   │  ⚡ MCP: schedule_budget_review  (if meeting details)
   └──────────┬───────────┘
              ▼
             END
```

### Nodes — there are only 4

| Node | Defined at | Registered at | Role |
|---|---|---|---|
| `supervisor` | `app/graph/supervisor.py:39` | `supervisor.py:94` | Router. No MCP. |
| `pipeline` | `app/graph/pipeline.py:36` | `supervisor.py:95` | Composite node wrapping the subgraph below. |
| `anomaly_detect` | `app/graph/anomaly_node.py:140` | `pipeline.py:38` | Deterministic detection. **Calls MCP.** |
| `reporting` | `app/graph/reporting_node.py:78` | `pipeline.py:39` | PDF + email + calendar. **Calls MCP.** |
| `analyst` | `app/graph/analyst_node.py:34` | `analyst_node.py:61`, `supervisor.py:96` | Chat / Text-to-SQL RAG. No MCP. |

### Edges

**Supervisor graph** (`app/graph/supervisor.py`)

| From | To | Kind |
|---|---|---|
| `START` | `supervisor` | `:98` |
| `supervisor` | `pipeline` / `analyst` / `END` | conditional `:99-103` via `route_after_trigger` `:88` |
| `pipeline` | `END` | `:104` |
| `analyst` | `END` | `:105` |

```python
ROUTES = {                      # supervisor.py:32-36
    "new_data":  "pipeline",
    "scheduled": "pipeline",
    "chat":      "analyst",
}
# unknown / blank trigger -> route=None -> `or "end"` -> END
```

When routing to `pipeline`, the supervisor also resolves the report window **once per run**
(`_resolve_report_window`, `:57-85`) so the anomaly pass and the PDF cover identical dates:
`report_months` → `get_user_settings()` → default `12`; anchor = `get_max_transaction_date()`.

**Pipeline subgraph** (`app/graph/pipeline.py`)

| From | To | Kind |
|---|---|---|
| `START` | `anomaly_detect` | `:41` |
| `anomaly_detect` | `reporting` / `END` | conditional `:42-46` via `route_after_anomaly` `:18` |
| `reporting` | `END` | `:47` |

```python
if state.get("force_report"):          return "reporting"   # manual button: clean == finding
if not result.get("success"):          return "end"        # nothing trustworthy
if result.get("anomaly_count", 0) > 0: return "reporting" # something flagged
return "end"                                                 # scheduled runs stay quiet
```

**Analyst subgraph** (`app/graph/analyst_node.py`)
`START → analyst → END` (`:62`, `:63`).

### Entry points

| Caller | File | Trigger |
|---|---|---|
| Background scheduler loop (60s tick) | `app/main.py:182-240`, dispatch `:230` | `"scheduled"` |
| `POST /api/agent/run` | `app/api/agent.py:89`, invoke `:114` | `"new_data"` (+ `force_report: True`) |
| `POST /api/chat/data-query` | `app/api/chat.py:66`, invoke `:78` | `"chat"` |
| `POST /api/chat/data-query/stream` | `app/api/chat.py:98`, `astream` `:124` | `"chat"` |
| CLI `python -m app.graph.run_sync <user_id>` | `app/graph/run_sync.py:13` | `"new_data"` |

Registered graph: `langgraph.json:3` → `./app/graph/supervisor.py:graph`.

There is **no dedicated output node** — results are read off the returned state dict:

- data runs → `result["anomaly_result"]` + `result["report"]`
- chat runs → `result["analyst"]["answer"]`
- any run → `result["route_error"]` means failure

---

## 3. Where MCP Fires

| Node | Call site | Tool | Server |
|---|---|---|---|
| `anomaly_detect` | `app/graph/anomaly_node.py:155` | *(bind both servers)* | — |
| `anomaly_detect` | `app/graph/anomaly_node.py:158` | `list_transactions` | `supabase-mcp` |
| `reporting` | `app/graph/reporting_node.py:86` | *(bind both servers)* | — |
| `reporting` | `app/graph/reporting_node.py:90` | `generate_cfo_pdf_report` | `reporting-mcp` |
| `reporting` | `app/graph/reporting_node.py:126` | `send_email_report` | `reporting-mcp` |
| `reporting` | `app/graph/reporting_node.py:143` | `schedule_budget_review` | `reporting-mcp` |

`supervisor` never calls MCP (direct DB reads via `asyncio.to_thread`).
`analyst` does **not** go through the stdio MCP client — it imports `describe_table` /
`run_read_only_sql` in-process from `app/services/rag.py:31-32`. Org scoping is preserved,
but it is a direct Python call, not an MCP round-trip.

---

## 4. Key Points

- **4 nodes total**, no loops, no cycles, no swarm. A shallow DAG of depth 2.
- **All tool calls funnel through one helper**: `app/graph/mcp_tools.py:139` `_call()`.
  It applies timeouts (PDF 300s, email 180s, default 120s, env override `MCP_CALL_TIMEOUT`),
  unwraps MCP `[{"type":"text","text":"<json>"}]` envelopes, logs timing, and converts
  failures/timeout/missing-tool into `{"error": ...}` data instead of raising.
  Consequence: a wedged MCP subprocess fails one node stage, never the whole run.
- **Reporting early-returns on PDF failure** (`reporting_node.py:102-111`) — email and
  calendar are never attempted without a PDF.
- **Conditional dispatch**: `send_email_report` only if a recipient exists (state
  `report_email` → `get_user_settings`); `schedule_budget_review` only if `state["meeting"]`
  has `attendees`, `start_time`, and `end_time`.
- **Determinism**: only the PDF narrative and the analyst RAG involve an LLM.
  `supervisor`, `anomaly_detect`, and both routers are pure logic. The reporting brief is
  built deterministically (`_build_instructions`, `reporting_node.py:20-61`) so the same
  anomalies always produce the same brief.
- **No checkpointers, no `Command`, no `interrupt`, no reducers** on the `PipelineState`
  TypedDict (`app/graph/state.py:19-43`).
