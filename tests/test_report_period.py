import datetime as dt

import pytest

from app.graph.period import (
    ALLOWED_MONTHS,
    DEFAULT_MONTHS,
    MAX_MONTHS,
    normalize_months,
    parse_anchor,
    resolve_window,
)


class TestNormalizeMonths:
    def test_none_falls_back_to_default(self):
        assert normalize_months(None) == DEFAULT_MONTHS

    def test_accepted_value_is_kept(self):
        for months in ALLOWED_MONTHS:
            assert normalize_months(months) == months

    def test_string_number_is_coerced(self):
        assert normalize_months("6") == 6

    def test_float_is_truncated(self):
        assert normalize_months(6.9) == 6

    @pytest.mark.parametrize("bad", ["", "soon", [], {}, object()])
    def test_unparseable_falls_back_to_default(self, bad):
        assert normalize_months(bad) == DEFAULT_MONTHS

    def test_zero_and_negative_clamp_to_one(self):
        assert normalize_months(0) == 1
        assert normalize_months(-5) == 1

    def test_absurd_value_is_capped(self):
        assert normalize_months(10_000) == MAX_MONTHS

    def test_default_is_unchanged_from_previous_behaviour(self):
        # The report used to be hard-coded to 12; an unset preference must not move it.
        assert DEFAULT_MONTHS == 12


class TestParseAnchor:
    def test_iso_date_string(self):
        assert parse_anchor("2026-09-15") == dt.date(2026, 9, 15)

    def test_iso_timestamp_string_uses_the_date_part(self):
        assert parse_anchor("2026-09-15T13:45:00") == dt.date(2026, 9, 15)

    def test_date_and_datetime_objects_pass_through(self):
        assert parse_anchor(dt.date(2026, 9, 15)) == dt.date(2026, 9, 15)
        assert parse_anchor(dt.datetime(2026, 9, 15, 23, 59)) == dt.date(2026, 9, 15)

    @pytest.mark.parametrize("bad", [None, "", "   ", "not-a-date", "15/09/2026"])
    def test_unusable_falls_back_to_today(self, bad):
        assert parse_anchor(bad) == dt.date.today()


class TestResolveWindow:
    def test_twelve_months_spans_twelve_calendar_months(self):
        start, end = resolve_window(12, "2026-09-15")
        assert start == "2025-10-01"
        assert end == "2026-09-15"

    def test_start_is_the_first_of_the_month(self):
        start, _ = resolve_window(3, "2026-09-15")
        assert start == "2026-07-01"

    def test_single_month_is_the_anchor_month(self):
        start, end = resolve_window(1, "2026-09-15")
        assert (start, end) == ("2026-09-01", "2026-09-15")

    def test_anchor_includes_the_whole_anchor_month(self):
        # A transaction later in the anchor month must survive the window.
        start, end = resolve_window(1, "2026-09-01")
        assert end == "2026-09-01"

    def test_missing_anchor_uses_today(self):
        _, end = resolve_window(6, None)
        assert end == dt.date.today().isoformat()

    def test_january_rolls_back_into_the_previous_year(self):
        start, _ = resolve_window(3, "2026-01-20")
        assert start == "2025-11-01"

    def test_window_is_inclusive_of_both_bounds(self):
        start, end = resolve_window(3, "2026-09-15")
        first = dt.date.fromisoformat(start)
        last = dt.date.fromisoformat(end)
        months = set()
        cursor = first
        while cursor <= last:
            months.add((cursor.year, cursor.month))
            cursor = dt.date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        assert months == {(2026, 7), (2026, 8), (2026, 9)}

    def test_unparseable_months_do_not_raise(self):
        start, end = resolve_window("nonsense", "2026-09-15")
        assert (start, end) == resolve_window(DEFAULT_MONTHS, "2026-09-15")

    def test_longer_window_starts_earlier(self):
        short, _ = resolve_window(3, "2026-09-15")
        long, _ = resolve_window(24, "2026-09-15")
        assert long < short


class TestReportGeneratorPeriod:
    def _frame(self):
        pd = pytest.importorskip("pandas")
        return pd.DataFrame({
            "Date": pd.to_datetime(
                ["2026-09-10", "2026-08-10", "2026-05-10", "2025-06-10"]
            ),
            "Type": ["Expense"] * 4,
            "Amount": [1.0, 2.0, 3.0, 4.0],
        })

    def test_generator_keeps_only_the_requested_months(self):
        from app.tools.report_generator import ReportGenerator

        gen = ReportGenerator(self._frame(), report_months=3)
        months = gen.df["Date"].dt.to_period("M").tolist()
        assert all(m >= dt.date(2026, 7, 1).strftime("%Y-%m") for m in map(str, months))

    def test_generator_default_still_spans_twelve_months(self):
        from app.tools.report_generator import ReportGenerator

        gen = ReportGenerator(self._frame())
        assert gen.report_months == DEFAULT_MONTHS
        assert len(gen.df) == 3  # 2025-06 falls outside a 12-month window from 2026-09

    def test_narrower_window_drops_the_older_rows(self):
        from app.tools.report_generator import ReportGenerator

        assert len(ReportGenerator(self._frame(), report_months=1).df) == 1
        assert len(ReportGenerator(self._frame(), report_months=3).df) == 2


class TestPeriodHelpersAreAlwaysInScope:
    """Regression: normalize_months used to be imported inside a branch.

    ``generate_cfo_pdf_report`` normalized the month count on a line *after* an
    ``if not (start_date and end_date):`` block that did the importing. Every
    caller that resolves the window first - which is the supervisor, so the
    production path - skipped the block and hit an UnboundLocalError, so no
    report was generated at all. The import must be unconditional.
    """

    def test_period_helpers_are_module_level_imports(self):
        import app.agents.mcp_server as srv

        assert srv.normalize_months is not None
        assert srv.resolve_window is not None
        assert srv.DEFAULT_MONTHS is not None

    def test_no_function_imports_period_helpers_locally(self):
        import ast
        import inspect

        import app.agents.mcp_server as srv

        tree = ast.parse(inspect.getsource(srv))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, (ast.Import, ast.ImportFrom)):
                    continue
                mod = getattr(inner, "module", "") or ""
                names = {a.asname or a.name for a in inner.names}
                if "app.graph.period" in mod or names & {
                    "normalize_months",
                    "resolve_window",
                    "DEFAULT_MONTHS",
                }:
                    offenders.append(f"{node.name} L{inner.lineno}")
        assert not offenders, f"local period imports shadow module scope: {offenders}"

    def test_explicit_dates_still_normalize(self):
        from app.graph.period import normalize_months, resolve_window

        # The supervisor always passes explicit bounds, so the fallback branch
        # is skipped entirely; normalization must work without it.
        start, end = resolve_window(6, "2026-09-28")
        assert normalize_months(6) == 6
        assert start < end
