# ==========================================================
# The report window, resolved once per run
# ==========================================================
# The user picks how many months back the report should reach, and that choice
# has to be honoured by everything that reads transactions: the anomaly pass and
# the report generator. If each computed its own window the anomalies listed in
# the PDF and the numbers in its tables would describe different periods, so the
# window is resolved once here and carried in PipelineState for the stages to
# read rather than each recomputing it.
#
# The window is anchored on the newest transaction the user actually has, not on
# today. An account that last synced in June still shows a full period that ends
# in June, rather than a window that is mostly empty recent months.

from __future__ import annotations

import datetime as dt

#: Offered in the settings dropdown.
ALLOWED_MONTHS = (1, 3, 6, 12, 24, 36)

#: What the report used before the period existed, so unset users see no change.
DEFAULT_MONTHS = 12

#: Ceiling for an explicit API value, so one bad request cannot ask for 10 years.
MAX_MONTHS = 60


def normalize_months(months) -> int:
    """Coerce a user-supplied month count into a sane int.

    Anything unparseable falls back to the default rather than raising: a
    missing or malformed preference should still produce a report.
    """
    if months is None:
        return DEFAULT_MONTHS
    try:
        value = int(months)
    except (TypeError, ValueError):
        return DEFAULT_MONTHS
    if value < 1:
        return 1
    return min(value, MAX_MONTHS)


def parse_anchor(value) -> dt.date:
    """Parse an ISO anchor, falling back to today when it is absent or unusable."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        # A stored TIMESTAMP only needs its date part; a plain date is the whole thing.
        for candidate in (text[:10], text):
            try:
                return dt.date.fromisoformat(candidate)
            except ValueError:
                continue
    return dt.date.today()


def _month_start(value: dt.date) -> dt.date:
    return dt.date(value.year, value.month, 1)


def _shift_months(start: dt.date, delta: int) -> dt.date:
    """Shift a month-start by *delta* months without pulling in a date library."""
    total = start.year * 12 + (start.month - 1) + delta
    year, month = divmod(total, 12)
    return dt.date(year, month + 1, 1)


def resolve_window(months, anchor) -> tuple[str, str]:
    """Resolve the reporting window into inclusive ISO bounds.

    Returns ``(start_date, end_date)``. ``end_date`` is the anchor itself, so the
    newest stored transaction is always included, and ``start_date`` is the first
    day of the month *months* back from the anchor's month, which makes the
    window span exactly ``months`` calendar months.
    """
    count = normalize_months(months)
    end = parse_anchor(anchor)
    start = _shift_months(_month_start(end), -(count - 1))
    return start.isoformat(), end.isoformat()
