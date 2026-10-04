"""The daily report scheduler.

The loop used to fire only when the current minute string equalled the user's
stored schedule, and kept its once-a-day latch in a module-level dict. Either a
slow tick or a deploy therefore cost that user the whole day silently, and a
report required a report_email even when the user only wanted it generated.
"""

import datetime as dt

import pytest

from app import main


class TestScheduledMoment:
    def test_parses_hh_mm(self):
        day = dt.datetime(2026, 9, 15, 0, 0, 0)
        assert main._scheduled_moment("14:30", day) == dt.datetime(2026, 9, 15, 14, 30)

    def test_tolerates_a_seconds_suffix(self):
        day = dt.datetime(2026, 9, 15, 0, 0, 0)
        assert main._scheduled_moment("14:30:00", day) == dt.datetime(2026, 9, 15, 14, 30)

    def test_tolerates_surrounding_whitespace(self):
        day = dt.datetime(2026, 9, 15, 0, 0, 0)
        assert main._scheduled_moment("  14:30 ", day) == dt.datetime(2026, 9, 15, 14, 30)

    @pytest.mark.parametrize("bad", ["", None, "   ", "9am", "noon", "14", "::30"])
    def test_unparseable_returns_none(self, bad):
        assert main._scheduled_moment(bad, dt.datetime(2026, 9, 15)) is None

    def test_seconds_suffix_is_ignored_rather_than_rejected(self):
        # [:5] means the stored value is trusted down to the minute; a nonsense
        # seconds field is harmless because the schedule is minute-granular.
        day = dt.datetime(2026, 9, 15, 0, 0, 0)
        assert main._scheduled_moment("14:30:99", day) == dt.datetime(2026, 9, 15, 14, 30)

    def test_out_of_range_clock_returns_none(self):
        assert main._scheduled_moment("99:99", dt.datetime(2026, 9, 15)) is None


class TestDueWindow:
    """A schedule is due if its moment falls inside the elapsed window."""

    @staticmethod
    def _due(schedule, window_start, window_end):
        due = main._scheduled_moment(schedule, window_end)
        return due is not None and window_start < due <= window_end

    def test_schedule_inside_the_window_is_due(self):
        # Ticks drift, so a 60s window rarely lands on a minute boundary.
        start = dt.datetime(2026, 9, 15, 14, 0, 30)
        end = dt.datetime(2026, 9, 15, 14, 1, 25)
        assert self._due("14:01", start, end) is True

    def test_schedule_before_the_window_is_not_due(self):
        # This is the old bug: a 09:00 schedule evaluated at 15:00 never matches.
        start = dt.datetime(2026, 9, 15, 14, 59, 0)
        end = dt.datetime(2026, 9, 15, 15, 0, 0)
        assert self._due("09:00", start, end) is False

    def test_a_slow_tick_catches_up_the_missed_minute(self):
        # The loop was meant to tick every 60s but took three minutes; 14:30
        # fell inside the elapsed window and must still run.
        start = dt.datetime(2026, 9, 15, 14, 28, 0)
        end = dt.datetime(2026, 9, 15, 14, 31, 0)
        assert self._due("14:30", start, end) is True

    def test_startup_grace_catches_a_deploy_just_after_the_time(self):
        end = dt.datetime(2026, 9, 15, 14, 5, 0)
        start = end - dt.timedelta(minutes=main._SCHEDULER_STARTUP_GRACE_MINUTES)
        assert self._due("14:00", start, end) is True

    def test_startup_grace_does_not_fire_a_stale_morning_report(self):
        # A deploy at 15:00 must not blast every user a 09:00 report.
        end = dt.datetime(2026, 9, 15, 15, 0, 0)
        start = end - dt.timedelta(minutes=main._SCHEDULER_STARTUP_GRACE_MINUTES)
        assert self._due("09:00", start, end) is False

    def test_window_start_is_exclusive_so_one_minute_fires_once(self):
        # window_start is the previous tick's end, which already processed this
        # minute. Excluding it is what stops a double fire on the next tick.
        start = dt.datetime(2026, 9, 15, 14, 30, 0)
        end = dt.datetime(2026, 9, 15, 14, 31, 0)
        assert self._due("14:30", start, end) is False

    def test_window_end_is_inclusive(self):
        start = dt.datetime(2026, 9, 15, 14, 29, 30)
        end = dt.datetime(2026, 9, 15, 14, 30, 0)
        assert self._due("14:30", start, end) is True

    def test_grace_period_is_short_enough_to_be_safe(self):
        assert main._SCHEDULER_STARTUP_GRACE_MINUTES <= 30


class TestLatch:
    def test_last_run_is_read_from_settings_not_memory(self):
        # The once-a-day guard has to survive a restart, so it lives in the DB.
        assert not hasattr(main, "_report_last_run")


class _FakeCursor:
    def __init__(self):
        self.executed = None
        self.params = None

    def execute(self, sql, params=None):
        self.executed = sql
        self.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        pass


class TestLatchIsPersisted:
    def test_claim_is_written_to_user_settings(self, monkeypatch):
        import app.db.database as database

        fake = _FakeConn()
        monkeypatch.setattr(database, "get_connection", lambda: fake)

        database.update_user_settings(4, {"report_last_run": "2026-09-15"})

        assert "report_last_run = %s" in fake.cursor_obj.executed
        assert fake.cursor_obj.params == ("2026-09-15", 4)
        assert fake.committed is True

    def test_unknown_column_is_still_rejected(self, monkeypatch):
        import app.db.database as database

        fake = _FakeConn()
        monkeypatch.setattr(database, "get_connection", lambda: fake)

        database.update_user_settings(4, {"report_last_run": "x", "not_a_column": "y"})

        # The allow-list drops the unknown key instead of building invalid SQL.
        assert "not_a_column" not in (fake.cursor_obj.executed or "")
        assert "report_last_run = %s" in fake.cursor_obj.executed


class _FrozenClock:
    """Stands in for main.datetime so the loop sees a pinned clock."""

    def __init__(self, frozen: dt.datetime):
        self._frozen = frozen

    def now(self, tz=None):
        return self._frozen


class TestLoopDispatch:
    """Drive one pass of the loop against stubbed settings."""

    @staticmethod
    def _one_pass(monkeypatch, settings_by_user, now):
        import asyncio

        import app.db.database as database

        claims: list[tuple[int, str]] = []
        dispatched: list[int] = []

        monkeypatch.setattr(database, "get_all_user_ids", lambda: list(settings_by_user))
        monkeypatch.setattr(
            database, "get_user_settings", lambda uid: settings_by_user[uid]
        )
        monkeypatch.setattr(
            database,
            "update_user_settings",
            lambda uid, upd: claims.append((uid, upd.get("report_last_run"))),
        )
        monkeypatch.setattr(main, "datetime", _FrozenClock(now))

        async def fake_run(user_id):
            dispatched.append(user_id)

        monkeypatch.setattr(main, "_run_scheduled_pipeline", fake_run)

        # Run exactly one pass, then stop.
        async def fake_sleep(_seconds):
            raise asyncio.CancelledError

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        async def run():
            with pytest.raises(asyncio.CancelledError):
                await main._scheduled_report_loop()

        asyncio.run(run())
        return dispatched, claims

    def test_a_due_user_is_dispatched_and_claims_the_day(self, monkeypatch):
        now = dt.datetime(2026, 9, 15, 14, 30, 0)
        settings = {4: {"report_schedule": "14:30", "report_email": None,
                        "report_last_run": None}}
        dispatched, claims = self._one_pass(monkeypatch, settings, now)
        assert dispatched == [4]
        assert claims == [(4, "2026-09-15")]

    def test_a_report_is_generated_even_without_a_recipient(self, monkeypatch):
        # The old guard required report_email, so a user who only wanted the
        # report stored never got a scheduled run at all.
        now = dt.datetime(2026, 9, 15, 14, 30, 0)
        settings = {4: {"report_schedule": "14:30", "report_email": None,
                        "report_last_run": None}}
        dispatched, _ = self._one_pass(monkeypatch, settings, now)
        assert dispatched == [4]

    def test_a_user_who_already_ran_today_is_skipped(self, monkeypatch):
        now = dt.datetime(2026, 9, 15, 14, 30, 0)
        settings = {4: {"report_schedule": "14:30", "report_email": "a@b.com",
                        "report_last_run": "2026-09-15"}}
        dispatched, claims = self._one_pass(monkeypatch, settings, now)
        assert dispatched == []
        assert claims == []

    def test_yesterdays_latch_does_not_block_today(self, monkeypatch):
        now = dt.datetime(2026, 9, 15, 14, 30, 0)
        settings = {4: {"report_schedule": "14:30", "report_email": "a@b.com",
                        "report_last_run": "2026-09-14"}}
        dispatched, _ = self._one_pass(monkeypatch, settings, now)
        assert dispatched == [4]

    def test_a_user_without_a_schedule_is_skipped(self, monkeypatch):
        now = dt.datetime(2026, 9, 15, 14, 30, 0)
        settings = {4: {"report_schedule": "", "report_email": "a@b.com",
                        "report_last_run": None}}
        dispatched, _ = self._one_pass(monkeypatch, settings, now)
        assert dispatched == []

    def test_a_malformed_schedule_does_not_break_the_loop(self, monkeypatch):
        now = dt.datetime(2026, 9, 15, 14, 30, 0)
        settings = {
            4: {"report_schedule": "banana", "report_email": "a@b.com",
                "report_last_run": None},
            5: {"report_schedule": "14:30", "report_email": "a@b.com",
                "report_last_run": None},
        }
        dispatched, _ = self._one_pass(monkeypatch, settings, now)
        # The bad row is skipped; the good one still runs.
        assert dispatched == [5]


class TestCutover:
    """The new MCP graph is the main path, not the legacy prompt-driven agent."""

    def test_langgraph_json_exports_the_supervisor(self):
        import json
        import pathlib

        cfg = json.loads(
            (pathlib.Path(__file__).resolve().parents[1] / "langgraph.json").read_text()
        )
        assert cfg["graphs"]["agent"] == "./app/graph/supervisor.py:graph"

    def test_scheduled_run_drives_the_graph_with_state_not_a_prompt(self, monkeypatch):
        """A prose prompt makes the model re-derive the period; state cannot."""
        import asyncio

        captured = {}

        class _FakeGraph:
            async def ainvoke(self, state):
                captured.update(state)
                return {
                    "anomaly_result": {"anomaly_count": 2, "rows_analyzed": 100},
                    "report": {"status": "ok"},
                }

        import app.graph.supervisor as supervisor

        monkeypatch.setattr(supervisor, "graph", _FakeGraph())
        asyncio.run(main._run_scheduled_pipeline(4))

        assert captured == {
            "user_id": 4,
            "trigger": "scheduled",
            "source": "stripe",
        }
        # "scheduled" must be a real route in the supervisor, or it dead-ends.
        assert supervisor.ROUTES["scheduled"] == "pipeline"

    def test_scheduled_run_swallowes_graph_failure(self, monkeypatch):
        """One user's broken run must not kill the loop for everyone else."""
        import asyncio

        class _Boom:
            async def ainvoke(self, _state):
                raise RuntimeError("mcp exploded")

        import app.graph.supervisor as supervisor

        monkeypatch.setattr(supervisor, "graph", _Boom())
        # Must not raise.
        asyncio.run(main._run_scheduled_pipeline(4))
