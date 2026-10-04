"""Architecture tests for the parallel report narrative.

The narrative used to be one blocking call that asked for six ``|||``-delimited
sections and parsed them back by index. It is now one short call per section,
fanned out across a thread pool. These tests pin that architecture and the
defects found while validating it against the live provider.

Everything here runs offline: ``create_llm`` is replaced with a recorder, except
in the reasoning-effort test, which deliberately builds a real ``ChatGroq`` and
makes no request.
"""

import os
import threading
import time

import pandas as pd
import pytest

from app.services import llm_factory
from app.tools import report_generator
from app.tools.report_generator import ReportGenerator, plain_text

# Phrases that identify which section a prompt is asking for. Each instruction is
# distinct, so the fake provider can tell them apart without relying on ordering.
SECTION_MARKERS = {
    "overall financial health": "exec",
    "revenue performance": "rev",
    "spending performance": "exp",
    "significance of the": "anom",
    "actionable CFO recommendations": "rec",
    "Answer this request": "custom",
}

ALL_BASE_SECTIONS = ("exec", "rev", "exp", "anom", "rec")


def _frame(months: int = 12) -> pd.DataFrame:
    """Twelve months of revenue and expense rows with a few flagged anomalies."""
    rows = []
    for m in range(1, months + 1):
        common = {
            "Date": pd.Timestamp(f"2026-{m:02d}-15"),
            "Anomaly_ZScore": False,
            "Anomaly_IQR": False,
            "Anomaly_RuleBased": False,
        }
        rows.append({**common, "Type": "Revenue", "Category": "Subscription",
                     "Amount": 42_000.0 + 900 * m, "Severity": "Normal"})
        rows.append({**common, "Type": "Expense", "Category": "Travel",
                     "Amount": 6_500.0 + 4_200 * m, "Severity": "High",
                     "Anomaly_ZScore": True})
    return pd.DataFrame(rows)


def _generator(monkeypatch, tmp_path, **kwargs) -> ReportGenerator:
    """A generator wired to a non-empty frame and an explicit LLM config.

    The API key is passed explicitly rather than left to the environment, so
    these tests never depend on a developer's real .env and never make a request.
    """
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    params = {
        "output_path": str(tmp_path / "report.pdf"),
        "llm_config": {"provider": "groq", "model": "test-model", "api_key": "unit-test-key"},
        "report_months": 12,
    }
    params.update(kwargs)
    return ReportGenerator(_frame(), **params)


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeProvider:
    """Stands in for ``create_llm``.

    Records every call so tests can assert on how many requests were made and
    which sections they were for, and can be told to fail, stall or return an
    empty body for chosen sections.
    """

    def __init__(self, *, fail=(), empty=(), delay=0.0, barrier=None, blocks=False):
        self.calls = []
        self.kwargs = []
        self.fail = set(fail)
        self.empty = set(empty)
        self.delay = delay
        self.barrier = barrier
        self.blocks = blocks
        self._lock = threading.Lock()
        self.concurrent_now = 0
        self.peak_concurrent = 0

    def __call__(self, **kwargs):
        self.kwargs.append(kwargs)

        def invoke(messages, config=None):
            prompt = messages[1]["content"]
            key = next(v for k, v in SECTION_MARKERS.items() if k in prompt)
            with self._lock:
                self.calls.append(key)
                self.concurrent_now += 1
                self.peak_concurrent = max(self.peak_concurrent, self.concurrent_now)
            try:
                if self.barrier is not None:
                    # Every section waits for every other section to arrive. If the
                    # pool were serial the first arrival would time out here and the
                    # section would fall back, so a passing test is proof of real
                    # concurrency rather than a lucky stopwatch reading.
                    self.barrier.wait()
                if self.delay:
                    time.sleep(self.delay)
                if key in self.fail:
                    raise RuntimeError(f"provider rejected {key}")
                if key in self.empty:
                    return FakeResponse("   \n  ")
                if self.blocks:
                    return FakeResponse([{"type": "text", "text": f"{key} as blocks"}])
                return FakeResponse(f"  {key} prose.  ")
            finally:
                with self._lock:
                    self.concurrent_now -= 1

        return type("FakeClient", (), {"invoke": staticmethod(invoke)})()


def _install(monkeypatch, provider, workers: int = 6) -> FakeProvider:
    """Point the report at ``provider`` and pin the pool size.

    The worker count is a module global read at call time, so it is patched as an
    attribute rather than through the environment variable; otherwise every test
    would inherit whatever the developer happens to have exported.
    """
    monkeypatch.setattr(llm_factory, "create_llm", provider)
    monkeypatch.setattr(report_generator, "_NARRATIVE_MAX_WORKERS", workers)
    return provider


class TestConcurrency:
    def test_every_section_is_requested_concurrently(self, monkeypatch, tmp_path):
        # A barrier the pool cannot satisfy unless all five base sections are in
        # flight at the same moment.
        provider = _install(monkeypatch, FakeProvider(barrier=threading.Barrier(5, timeout=10)))
        narrative = _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert sorted(provider.calls) == sorted(ALL_BASE_SECTIONS)
        fallbacks = ReportGenerator._NARRATIVE_FALLBACKS
        assert all(narrative[k] != fallbacks[k] for k in ALL_BASE_SECTIONS), narrative

    def test_wall_time_tracks_the_slowest_section_not_their_sum(self, monkeypatch, tmp_path):
        # One section is an order of magnitude slower than the rest. Serial
        # execution would cost every delay; parallel execution costs the largest.
        delays = {"exec": 0.50, "rev": 0.05, "exp": 0.05, "anom": 0.05, "rec": 0.05}

        class Skewed(FakeProvider):
            def __call__(self, **kwargs):
                outer = self

                def invoke(messages, config=None):
                    prompt = messages[1]["content"]
                    key = next(v for k, v in SECTION_MARKERS.items() if k in prompt)
                    time.sleep(delays[key])
                    outer.calls.append(key)
                    return FakeResponse(f"{key} prose.")

                return type("C", (), {"invoke": staticmethod(invoke)})()

        _install(monkeypatch, Skewed())
        started = time.perf_counter()
        _generator(monkeypatch, tmp_path).generate_llm_narrative()
        wall = time.perf_counter() - started

        assert wall < sum(delays.values()) * 0.8, (
            f"wall={wall:.2f}s looks serial against a {sum(delays.values()):.2f}s sum"
        )

    def test_worker_cap_is_respected(self, monkeypatch, tmp_path):
        provider = _install(monkeypatch, FakeProvider(delay=0.08), workers=2)
        _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert len(provider.calls) == 5, "the cap must throttle, not drop work"
        assert provider.peak_concurrent <= 2, provider.peak_concurrent

    def test_a_pool_larger_than_the_section_count_is_harmless(self, monkeypatch, tmp_path):
        provider = _install(monkeypatch, FakeProvider(), workers=64)
        narrative = _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert len(provider.calls) == 5
        assert sorted(narrative) == sorted((*ALL_BASE_SECTIONS, "custom"))


class TestFailureIsolation:
    """One section's failure must not cost the report the other five."""

    def test_a_raising_section_only_loses_its_own_paragraph(self, monkeypatch, tmp_path):
        provider = _install(monkeypatch, FakeProvider(fail={"anom"}))
        narrative = _generator(monkeypatch, tmp_path).generate_llm_narrative()

        fallbacks = ReportGenerator._NARRATIVE_FALLBACKS
        assert narrative["anom"] == fallbacks["anom"]
        for key in ("exec", "rev", "exp", "rec"):
            assert narrative[key] != fallbacks[key], f"{key} should have survived"
        assert len(provider.calls) == 5

    def test_an_empty_response_is_treated_as_a_failure(self, monkeypatch, tmp_path):
        # Whitespace-only prose would render as a blank paragraph, which is worse
        # than the placeholder because it looks like a deliberate omission.
        _install(monkeypatch, FakeProvider(empty={"rec"}))
        narrative = _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert narrative["rec"] == ReportGenerator._NARRATIVE_FALLBACKS["rec"]

    def test_every_section_failing_still_returns_the_full_key_set(self, monkeypatch, tmp_path):
        _install(monkeypatch, FakeProvider(fail=set(SECTION_MARKERS.values())))
        narrative = _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert sorted(narrative) == sorted((*ALL_BASE_SECTIONS, "custom"))
        for key in ALL_BASE_SECTIONS:
            assert narrative[key] == ReportGenerator._NARRATIVE_FALLBACKS[key]

    def test_the_parallel_pass_never_raises(self, monkeypatch, tmp_path):
        class Exploding(FakeProvider):
            def __call__(self, **kwargs):
                def invoke(messages, config=None):
                    raise KeyboardInterrupt("not an Exception subclass")

                return type("C", (), {"invoke": staticmethod(invoke)})()

        _install(monkeypatch, Exploding())
        # KeyboardInterrupt is a BaseException, so it must propagate rather than
        # be swallowed: swallowing it would hide a real shutdown signal.
        with pytest.raises(KeyboardInterrupt):
            _generator(monkeypatch, tmp_path).generate_llm_narrative()


class TestCustomSection:
    def test_it_is_skipped_when_no_request_was_made(self, monkeypatch, tmp_path):
        provider = _install(monkeypatch, FakeProvider())
        narrative = _generator(monkeypatch, tmp_path, custom_instructions="").generate_llm_narrative()

        assert "custom" not in provider.calls, "no request, no LLM call"
        assert "custom" in narrative, "the key must exist for the PDF builder"
        assert not narrative["custom"], "empty, not the placeholder, so the PDF skips it"

    def test_it_is_requested_when_there_is_a_request(self, monkeypatch, tmp_path):
        provider = _install(monkeypatch, FakeProvider())
        narrative = _generator(
            monkeypatch, tmp_path, custom_instructions="Why is travel climbing?"
        ).generate_llm_narrative()

        assert "custom" in provider.calls
        assert narrative["custom"].strip() == "custom prose."

    def test_the_prompt_carries_the_users_own_request(self, monkeypatch, tmp_path):
        seen = []

        class Capturing(FakeProvider):
            def __call__(self, **kwargs):
                def invoke(messages, config=None):
                    seen.append(messages[1]["content"])
                    return FakeResponse("ok")

                return type("C", (), {"invoke": staticmethod(invoke)})()

        _install(monkeypatch, Capturing())
        _generator(
            monkeypatch, tmp_path, custom_instructions="Compare travel to payroll."
        ).generate_llm_narrative()

        assert any("Compare travel to payroll." in p for p in seen)


class TestSectionPrompts:
    """Guards the wording defects that only a live provider exposed.

    The first version of these prompts named the section inside its instruction
    ("Anomaly Explanation: ..."), and the model echoed the name back into a
    paragraph the PDF had already headed. Asking for "3 recommendations" also came
    back as a numbered list, and "directly address this request" was unbounded,
    producing 2000+ character answers. None of that is visible to a mock, so the
    shape of the instruction is pinned here.
    """

    def test_no_section_instruction_leads_with_its_own_label(self, monkeypatch, tmp_path):
        sections = _generator(monkeypatch, tmp_path)._narrative_sections(3)
        labels = (
            "Executive Summary", "Revenue Insights", "Expense Insights",
            "Anomaly Explanation", "Conclusion & Recommendations",
        )
        for key, instruction in sections.items():
            assert not instruction.startswith(labels), f"{key} invites label echo"

    def test_recommendations_demand_prose_not_a_list(self, monkeypatch, tmp_path):
        instruction = _generator(monkeypatch, tmp_path)._narrative_sections(0)["rec"]
        assert "paragraph" in instruction.lower()
        assert "not number or bullet" in instruction.lower()

    def test_the_custom_section_is_length_bounded(self, monkeypatch, tmp_path):
        instruction = _generator(
            monkeypatch, tmp_path, custom_instructions="Explain the travel spike."
        )._narrative_sections(0)["custom"]
        assert "at most" in instruction.lower()

    def test_the_anomaly_count_reaches_its_prompt(self, monkeypatch, tmp_path):
        assert "17 anomalies" in _generator(monkeypatch, tmp_path)._narrative_sections(17)["anom"]

    def test_burn_rate_is_labelled_by_period(self, monkeypatch, tmp_path):
        # The prompt used to offer only a whole-period burn figure with no period
        # label, and live runs described it as "a monthly burn rate of $42,000"
        # while the KPI card printed $71,950/mo on the same page.
        prompts = []

        class Recorder(FakeProvider):
            def __call__(self, **kwargs):
                def invoke(messages, config=None):
                    prompts.append(messages[1]["content"])
                    return FakeResponse("ok")

                return type("C", (), {"invoke": staticmethod(invoke)})()

        _install(monkeypatch, Recorder())
        _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert prompts, "no prompt captured"
        for prompt in prompts:
            assert "NOT monthly" in prompt
            assert "Average Monthly Spend" in prompt
            assert "whole reporting period" in prompt

        # Only the trailing instruction is meant to differ. Every worker must be
        # handed an identical data block, so the facts cannot drift between
        # sections the way they did when one call assembled its own summary.
        blocks = {p.split("\n\nWrite")[0] for p in prompts}
        assert len(blocks) == 1, "sections received different data blocks"


class TestProviderWiring:
    def test_reasoning_effort_is_passed_top_level(self, monkeypatch, tmp_path):
        # Regression guard. reasoning_effort used to travel inside model_kwargs,
        # which langchain-groq 1.x rejects outright, so every section failed to
        # build a client and the whole narrative silently became placeholder text.
        provider = _install(monkeypatch, FakeProvider())
        _generator(monkeypatch, tmp_path).generate_llm_narrative()

        for kwargs in provider.kwargs:
            assert "model_kwargs" not in kwargs, kwargs
            assert kwargs.get("reasoning_effort") == "low"
            assert kwargs.get("request_timeout") == report_generator._NARRATIVE_SECTION_TIMEOUT

    def test_the_real_groq_client_accepts_the_arguments_used(self):
        # Builds a genuine ChatGroq and asserts nothing goes over the wire, which
        # is what makes this a real guard rather than a restatement of the stub.
        from app.services.llm_factory import create_llm

        client = create_llm(
            provider="groq",
            model="openai/gpt-oss-120b",
            api_key="not-a-real-key",
            reasoning_effort="low",
            request_timeout=report_generator._NARRATIVE_SECTION_TIMEOUT,
            max_retries=1,
        )
        assert client.reasoning_effort == "low"

    def test_the_old_model_kwargs_form_is_still_rejected(self):
        # Guards the guard: if a future langchain-groq accepts model_kwargs again,
        # this test fails and the explicit-parameter form above can be revisited.
        from pydantic import ValidationError

        from app.services.llm_factory import create_llm

        with pytest.raises(ValidationError):
            create_llm(
                provider="groq",
                model="openai/gpt-oss-120b",
                api_key="not-a-real-key",
                model_kwargs={"reasoning_effort": "low"},
            )

    def test_reasoning_effort_is_withheld_from_providers_without_it(self, monkeypatch, tmp_path):
        provider = _install(monkeypatch, FakeProvider())
        gen = _generator(monkeypatch, tmp_path)
        gen.llm_config = {"provider": "gemini", "model": "m", "api_key": "k"}
        gen.generate_llm_narrative()

        for kwargs in provider.kwargs:
            assert "reasoning_effort" not in kwargs, kwargs

    def test_list_shaped_content_is_flattened(self, monkeypatch, tmp_path):
        _install(monkeypatch, FakeProvider(blocks=True))
        narrative = _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert narrative["exec"] == "exec as blocks"

    def test_surrounding_whitespace_is_stripped(self, monkeypatch, tmp_path):
        _install(monkeypatch, FakeProvider())
        narrative = _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert narrative["exec"] == "exec prose."


class TestTracingIsolation:
    def test_a_previously_set_value_is_restored(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        _install(monkeypatch, FakeProvider())
        _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"

    def test_an_unset_value_is_removed_again(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
        _install(monkeypatch, FakeProvider())
        _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert "LANGCHAIN_TRACING_V2" not in os.environ

    def test_tracing_is_off_while_the_pool_runs(self, monkeypatch, tmp_path):
        # LangSmith's background threads can deadlock when initialised inside the
        # reporting-mcp subprocess, so it has to be off for the whole fan-out, not
        # just for the moment each worker builds its client.
        observed = []

        class Watching(FakeProvider):
            def __call__(self, **kwargs):
                def invoke(messages, config=None):
                    observed.append(os.environ.get("LANGCHAIN_TRACING_V2"))
                    return FakeResponse("ok")

                return type("C", (), {"invoke": staticmethod(invoke)})()

        _install(monkeypatch, Watching())
        _generator(monkeypatch, tmp_path).generate_llm_narrative()

        assert observed and all(v == "false" for v in observed), observed


class TestNoApiKey:
    def test_the_whole_pass_is_skipped(self, monkeypatch, tmp_path):
        provider = FakeProvider()
        monkeypatch.setattr(llm_factory, "create_llm", provider)
        gen = _generator(monkeypatch, tmp_path)
        gen.llm_config = {"provider": "groq", "model": "m", "api_key": None}
        # Blanked after the generator is built: _generator seeds the environment
        # with a placeholder key so no test can accidentally reach a real provider.
        monkeypatch.setenv("GROQ_API_KEY", "")

        narrative = gen.generate_llm_narrative()

        assert provider.calls == [], "no client should be built without a key"
        assert sorted(narrative) == sorted((*ALL_BASE_SECTIONS, "custom"))
        assert narrative["exec"].startswith("LLM narrative generation skipped")


class TestTextNormalisation:
    """The Unicode space family, which the Latin-1 filter used to delete.

    A live report came out reading "July2026": the model emitted U+202F between
    the month and the year, that codepoint is outside Latin-1, and the
    unrenderable-character filter stripped it instead of normalising it, welding
    the two words together.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("July\u202f2026", "July 2026"),
            ("35\u2009%", "35 %"),
            ("cost\u00a0control", "cost control"),
            ("a\u2007b", "a b"),
            ("a\u2002b", "a b"),
            ("x\u205fy", "x y"),
        ],
    )
    def test_spaces_survive(self, raw, expected):
        assert plain_text(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2028\u201101\u201116", "2028-01-16"),
            ("cash\u2011burn", "cash-burn"),
            ("a\u2014b", "a-b"),
            ("a\u2013b", "a-b"),
            ("\u201cx\u201d", '"x"'),
            ("a\u2019b", "a'b"),
        ],
    )
    def test_the_earlier_replacements_still_hold(self, raw, expected):
        assert plain_text(raw) == expected

    def test_no_codepoint_outside_latin1_survives(self):
        out = plain_text("a\u202fb\u2009c\ufffdd")
        assert all(ch <= "\xff" for ch in out)
