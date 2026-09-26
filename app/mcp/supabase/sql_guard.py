# ==========================================================
# supabase-mcp: guard for LLM-generated SQL
# ==========================================================
# The chat LLM writes SQL, so supabase-mcp never trusts the text it is handed.
# Every check here is enforced by the database tool, not requested in prose:
# the LLM prompt can be wrong or manipulated and the boundary still holds.
#
# Three layers:
#   1. read_only()      - single SELECT/WITH, no mutating keyword
#   2. assert_queryable()- only allowlisted relations, CTE aliases included
#   3. scope_sql()      - wraps the query so rows are filtered to the org

from __future__ import annotations

import re

#: Relations the chat may read. Mirrors the table set the RAG prompt exposes.
QUERYABLE_TABLES = ("unified_transactions",)

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"replace|call|copy|vacuum|analyze|reindex|comment|load|import|attach|"
    r"detach|begin|commit|rollback|savepoint|reset|set|into)\b",
    re.IGNORECASE,
)

#: Relation names following FROM/JOIN. Schema-qualified names are captured whole
#: ("pg_catalog.pg_class") so a qualified name cannot smuggle a table past the
#: allowlist by qualifying it.
_RELATION_RE = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w$]*(?:\.[a-zA-Z_][\w$]*)?)", re.IGNORECASE
)

#: CTE names ("WITH foo AS (", ", bar AS (") are relations too, and are legal.
_CTE_RE = re.compile(
    r"(?:\bwith\b|,)\s*(?:recursive\s+)?([a-zA-Z_][\w$]*)\s+as\s*\(", re.IGNORECASE
)

#: Functions that read files, reach other databases, or stall the server. Every
#: other function is allowed: the read-only transaction blocks writes, so
#: restricting to an allowlist would only break SUM/date_trunc and friends.
_BLOCKED_FUNCTIONS = re.compile(
    r"\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|lo_import|"
    r"lo_export|lo_get|lo_list|dblink|dblink_exec|pg_sleep|pg_terminate_backend|"
    r"pg_cancel_backend|set_config|current_setting|nextval|setval)\b",
    re.IGNORECASE,
)

_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE)


class ScopeError(ValueError):
    """The query could not be scoped to the caller's org.

    Raised for a missing/unusable ``user_id`` column, which is recoverable: the
    caller can regenerate the SQL with a stricter instruction.
    """


def strip_sql_fences(sql: str) -> str:
    """Remove a markdown ```sql fence and any trailing semicolon."""
    cleaned = (sql or "").strip()
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    return cleaned.rstrip(";").strip()


def _strip_sql_literals(sql: str) -> str:
    """Remove comments and string literals so keyword checks see code only."""
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    # Replace single-quoted strings and double-quoted identifiers with spaces.
    s = re.sub(r"'(\\.|[^'\\])*'", " ", s)
    s = re.sub(r'"(\\.|[^"\\])*"', " ", s)
    # Dollar-quoted bodies ($$ ... $$ or $tag$ ... $tag$).
    s = re.sub(r"\$[A-Za-z_0-9]*\$.+?\$[A-Za-z_0-9]*\$", " ", s, flags=re.DOTALL)
    return s


def read_only(sql: str) -> bool:
    """Guard so the chat can only run read-only queries.

    Requires the statement to start with SELECT/WITH AND contain no mutating
    keyword (including inside data-modifying CTEs). A trailing statement
    separator is tolerated, but chained multi-statement payloads are rejected.
    """
    cleaned = _strip_sql_literals(strip_sql_fences(sql)).strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if not lower.startswith(("select", "with")):
        return False
    # Split on ';' - a single trailing terminator is tolerated, but any
    # additional statement (chained multi-statement payloads) is rejected.
    parts = [p.strip() for p in cleaned.split(";")]
    while parts and parts[-1] == "":
        parts.pop()
    if len(parts) > 1:
        return False
    if _FORBIDDEN_KEYWORDS.search(cleaned):
        return False
    return True


def referenced_relations(sql: str) -> set[str]:
    """Return every relation name the query reads, CTE aliases included."""
    cleaned = _strip_sql_literals(strip_sql_fences(sql))
    ctes = {name.lower() for name in _CTE_RE.findall(cleaned)}
    relations = {name.lower() for name in _RELATION_RE.findall(cleaned)}
    # A CTE reference resolves to the CTE, not to a base table.
    return relations - ctes


def assert_queryable(sql: str) -> None:
    """Raise ``ValueError`` unless *sql* reads only allowlisted relations.

    Catches cross-tenant and infrastructure reads: other app tables, the other
    users' settings, ``information_schema``, and ``pg_catalog``.
    """
    cleaned = _strip_sql_literals(strip_sql_fences(sql))
    blocked = _BLOCKED_FUNCTIONS.search(cleaned)
    if blocked:
        raise ValueError(f"function {blocked.group(0)} is not allowed in chat queries")

    allowed = {t.lower() for t in QUERYABLE_TABLES}
    offending = sorted(referenced_relations(cleaned) - allowed)
    if offending:
        raise ValueError(
            "chat queries may only read "
            f"{', '.join(QUERYABLE_TABLES)}; got: {', '.join(offending)}"
        )


def scope_sql(sql: str, user_ids: list[int]) -> str:
    """Wrap *sql* so it can only ever return rows belonging to *user_ids*.

    The predicate is applied by the tool to the query's own output, so it holds
    even when the model omits the filter, filters on the wrong user, or tries to
    widen it. The wrap requires ``user_id`` in the SELECT list; when the model
    left it out the caller gets a ``ScopeError`` and can retry with a stricter
    instruction.
    """
    if not re.search(r"\buser_id\b", _strip_sql_literals(strip_sql_fences(sql))):
        raise ScopeError(
            "query must reference the user_id column so the org scope can be "
            "enforced; include user_id in the SELECT list"
        )
    placeholders = ", ".join(["%s"] * len(user_ids))
    # The LIMIT is applied by the database, not by slicing in Python: a psycopg2
    # client cursor transfers the whole result set on execute(), so a runaway
    # cross join would land in memory before any cap could help.
    return (
        f"SELECT * FROM ({strip_sql_fences(sql)}) AS _scoped "
        f"WHERE _scoped.user_id IN ({placeholders}) LIMIT %s"
    )
