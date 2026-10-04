import functools
import json
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from xml.sax.saxutils import escape

import matplotlib
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.style.use('bmh')

# The narrative is a single blocking call and historically ran for ~58s against
# a 60s ceiling, so it was one slow provider away from being silently replaced by
# placeholder text. Give the report pass its own, larger deadline.
_NARRATIVE_TIMEOUT = float(os.getenv("REPORT_NARRATIVE_TIMEOUT", "30"))

# The narrative used to be one call asking for six "|||"-delimited sections, so its
# wall time was the sum of every section the model spent thinking, and one stalled
# section cost the whole report its prose. Each section is now its own short call,
# fanned out in parallel, so the pass costs the slowest single section instead of
# the sum of all of them.
#
# Concurrency is capped because hosted providers rate-limit per minute: 5-6
# simultaneous requests is comfortable on most tiers, but a free tier will start
# returning 429s well before that, which is why it is tunable rather than simply
# "one worker per section".
_NARRATIVE_MAX_WORKERS = int(os.getenv("REPORT_NARRATIVE_WORKERS", "6"))

# Each section is a couple of sentences off a short prompt, so it finishes far
# inside the old single-call budget. The deadline is per section, not per report.
_NARRATIVE_SECTION_TIMEOUT = int(os.getenv("REPORT_NARRATIVE_SECTION_TIMEOUT", "30"))

# Providers that declare a `reasoning_effort` model field. Anything else either
# rejects the argument or ignores it, so it is not sent.
_REASONING_EFFORT_PROVIDERS = ("groq", "openai")

# Charts were rendered at figsize=(7, 3.5) and then embedded at half that size,
# so every label was drawn for a 7in canvas and displayed at 3.5in. Rendering
# each chart at the size it is actually placed keeps the label sizes correct and
# cuts the report from ~410KB to ~265KB, which is payload the email then has to
# base64 and upload.
_CHART_DPI = int(os.getenv("REPORT_CHART_DPI", "150"))

# Chart placement sizes in inches. Revenue/expense charts sit side by side in a
# two-column table; the comparison charts span the full text width.
_CHART_HALF_SIZE = (3.4, 2.0)
_CHART_FULL_SIZE = (6.9, 3.2)


# --------------------------------------------------------------------------- #
# Page furniture
# --------------------------------------------------------------------------- #
class NumberedCanvas(canvas.Canvas):
    """Stamps a header, a footer rule and "Page N of M" on every page.

    ReportLab lays pages out sequentially and the final page count does not exist
    until the last one has been drawn, so a single pass can only ever print "Page
    N". Each page's content stream is stashed as it completes and replayed in
    ``save()``, where the total is finally known.
    """

    def __init__(self, *args, **kwargs):
        self._page_states = []
        self.header_left = kwargs.pop("header_left", "")
        self.header_right = kwargs.pop("header_right", "")
        self.footer_left = kwargs.pop("footer_left", "")
        self.margin_x = kwargs.pop("margin_x", 36)
        self.margin_y = kwargs.pop("margin_y", 54)
        super().__init__(*args, **kwargs)

    def showPage(self):
        self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._page_states)
        for page, state in enumerate(self._page_states, start=1):
            self.__dict__.update(state)
            self._draw_furniture(page, total)
            super().showPage()
        super().save()

    def _draw_furniture(self, page, total):
        width, height = self._pagesize
        left = self.margin_x
        right = width - left
        rule = colors.HexColor("#d5dde0")
        label = colors.HexColor("#7f8c8d")

        # The cover carries the full title already, so a running head on page one
        # would just repeat it.
        if page > 1 and (self.header_left or self.header_right):
            self.setFont("Helvetica-Bold", 7.5)
            self.setFillColor(label)
            baseline = height - self.margin_y + 24
            if self.header_left:
                self.drawString(left, baseline, self.header_left)
            if self.header_right:
                self.drawRightString(right, baseline, self.header_right)
            self.setStrokeColor(rule)
            self.setLineWidth(0.5)
            self.line(left, baseline - 6, right, baseline - 6)

        self.setStrokeColor(rule)
        self.setLineWidth(0.5)
        self.line(left, self.margin_y - 24, right, self.margin_y - 24)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(label)
        if self.footer_left:
            self.drawString(left, self.margin_y - 36, self.footer_left)
        self.drawRightString(right, self.margin_y - 36, f"Page {page} of {total}")

# --------------------------------------------------------------------------- #
# Text normalisation
#
# ReportLab renders into base-14 Type 1 fonts, which have no glyph for most of
# the punctuation modern models like to emit. The substitutions are silent, not
# fatal: U+2011 (non-breaking hyphen) came out of a real generated report as a
# literal letter "n", so "cash-burn", "rule-based" and the date "2028-01-16"
# all printed as "cashnburn", "rulenbased" and "2028n01n16". Normalising here
# keeps the model free to write normal prose.
# --------------------------------------------------------------------------- #
_PUNCTUATION_REPLACEMENTS = {
    "­": "",    # soft hyphen
    "": "",    # zero-width space
    "‌": "",    # zero-width non-joiner
    "‍": "",    # zero-width joiner
    "⁠": "",    # word joiner
    "⁡": "",    # invisible times
    "⁢": "",    # invisible separator
    "⁣": "",    # invisible plus
    "‑": "-",   # non-breaking hyphen   <- the one that printed "n"
    "‒": "-",   # figure dash
    "―": "-",   # horizontal bar
    "−": "-",   # minus sign
    "–": "-",   # en dash
    "—": "-",   # em dash
    "‘": "'",
    "’": "'",
    "‚": ",",
    "“": '"',
    "”": '"',
    "„": '"',
    "′": "'",
    "″": '"',
    "…": "...",
    " ": " ",   # non-breaking space
    "•": "-",
    "‣": "-",
    "●": "-",
    "★": "*",
    # The rest of the Unicode space family, written as escapes because these
    # characters are invisible in an editor and two of them are indistinguishable
    # on screen. Models favour them to stop a number and its unit splitting across
    # a line ("35 %", "July 2026"), and every one is outside Latin-1, so the
    # unrenderable-character filter below used to delete them outright and weld the
    # words together: a live report came out reading "July2026". Mapped to a real
    # space here, which the whitespace collapse in plain_text then handles.
    "\u2000": " ",   # en quad
    "\u2001": " ",   # em quad
    "\u2002": " ",   # en space
    "\u2003": " ",   # em space
    "\u2004": " ",   # three-per-em space
    "\u2005": " ",   # four-per-em space
    "\u2006": " ",   # six-per-em space
    "\u2007": " ",   # figure space
    "\u2008": " ",   # punctuation space
    "\u2009": " ",   # thin space
    "\u200a": " ",   # hair space
    "\u202f": " ",   # narrow no-break space
    "\u205f": " ",   # medium mathematical space
    "\u3000": " ",   # ideographic space
}

# Providers sometimes return the two-character sequence backslash-n rather than
# a real newline. Paragraph does not treat that as a break, so normalise first.
_LITERAL_ESCAPES = ((r"\r\n", "\n"), (r"\n", "\n"), (r"\t", " "))

# Anything outside Latin-1 has no base-14 glyph, so it is dropped rather than
# substituted with a wrong character.
_UNRENDERABLE_RE = re.compile(r"[^\x00-\xff]")


def plain_text(value) -> str:
    """Normalise arbitrary model/user text to base-14-renderable plain text.

    Collapses runs of whitespace and turns real newlines into single spaces, so
    the result is safe in a Platypus table cell drawn as a plain string.
    """
    text = "" if value is None else str(value)
    for bad, good in _PUNCTUATION_REPLACEMENTS.items():
        if bad in text:
            text = text.replace(bad, good)
    for literal, real in _LITERAL_ESCAPES:
        if literal in text:
            text = text.replace(literal, real)
    text = _UNRENDERABLE_RE.sub("", text)
    text = text.replace("\r", "\n")
    return re.sub(r"[ \t]*\n[ \t]*", " ", re.sub(r"[ \t]+", " ", text)).strip()


def markup_text(value) -> str:
    """Normalise text for a ReportLab ``Paragraph``.

    Escapes XML so an ``&`` or ``<`` in model prose cannot corrupt the layout,
    and turns real newlines into ``<br/>`` breaks.
    """
    text = escape(plain_text(value))
    lines = [line.strip() for line in text.split("\n")]
    return "<br/>".join(line for line in lines if line)


def format_currency(value) -> str:
    """Format money with the sign in front of the symbol.

    ``f"${-50_209_996:,.2f}"`` renders ``$-50,209,996.00``, which reads as
    noise in a financial report; the convention is ``-$50,209,996.00``.
    """
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "$0.00"
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _parse_percent(value) -> float:
    """Parse a stored percentage such as ``'283.7%'`` into a float."""
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _pair_table(left, right) -> Table:
    """Lay two charts side by side inside the printable text width.

    Without explicit column widths Platypus sizes the row to the widest flowable
    plus padding, which previously overflowed the frame on narrower pages.
    """
    col_width = _CHART_HALF_SIZE[0] * inch + 8
    table = Table([[left, right]], colWidths=[col_width, col_width])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return table


class ReportGenerator:
    """
    Generates a comprehensive Business CFO PDF report summarizing financial spending,
    revenue, profit, anomalies, and month-over-month comparisons.
    """

    # Page margins used by generate_pdf; the KPI cards need them to size
    # themselves against the true printable width. Vertical margins are deeper
    # so the running head and footer never crowd the body text.
    _page_margins = 36
    _margin_y = 58

    # Month-by-month breach rows shown before the rest are folded into the
    # per-category roll-up. Keeps the anomaly section to a predictable length.
    _breach_detail_rows = 12

    # Stand-in text for a section whose own call failed. Because sections are
    # generated independently, one provider error now costs only its own
    # paragraph instead of blanking the entire narrative.
    _NARRATIVE_FALLBACKS = {
        "exec": "Executive summary is currently unavailable due to a connection issue.",
        "rev": "Revenue streams are being processed.",
        "exp": "Expense categories are being analyzed.",
        "anom": "Anomalies have been flagged for manual review.",
        "rec": "Please review the raw data for specific recommendations.",
        "custom": "N/A",
    }

    def __init__(self, df: pd.DataFrame, output_path: str = "business_cfo_report.pdf",
                 custom_instructions: str = "", budget_breaches: list = None, breaches_file: str = None,
                 llm_config: dict = None, report_months: int = 12):
        self.df = df.copy()
        self.output_path = output_path
        self.custom_instructions = custom_instructions
        self.llm_config = llm_config or {}
        self.report_months = int(report_months) if report_months else 12
        self.styles = getSampleStyleSheet()
        self.elements = []
        self._chart_dir = None
        self._chart_size = {}

        # Custom styles
        self.styles.add(ParagraphStyle(name='SectionHeader', parent=self.styles['Heading1'], fontSize=18, textColor=colors.HexColor('#2980b9'), spaceBefore=20, spaceAfter=15))
        self.styles.add(ParagraphStyle(name='BannerTitle', parent=self.styles['Heading1'], fontSize=26, textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=25))
        self.styles.add(ParagraphStyle(name='AnomalyBanner', parent=self.styles['Heading2'], textColor=colors.HexColor('#c0392b')))
        self.styles.add(ParagraphStyle(name='TableText', parent=self.styles['Normal'], fontSize=9, leading=11))
        self.styles.add(ParagraphStyle(name='KPICard', parent=self.styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor('#1b2631')))

        if 'Type' not in self.df.columns:
            self.df['Type'] = 'Expense'

        # Restrict every chart/table/narrative in the report to the trailing
        # calendar months the user asked for, anchored on the latest month
        # present in the data.
        self.df = self._trailing_months(self.df, self.report_months)

        self.expenses = self.df[self.df['Type'] == 'Expense'].copy()
        self.revenue = self.df[self.df['Type'] == 'Revenue'].copy()

        if 'Severity' in self.df.columns:
            self.anomalies = self.df[self.df['Severity'] != 'Normal'].copy()
        else:
            self.anomalies = pd.DataFrame()

        # Load Budget Breaches
        self.budget_breaches = budget_breaches if budget_breaches is not None else []
        if not self.budget_breaches:
            file_to_load = breaches_file if breaches_file else "budget_breaches.json"
            if os.path.exists(file_to_load):
                try:
                    with open(file_to_load) as f:
                        self.budget_breaches = json.load(f)
                except Exception:
                    pass

    def _trailing_months(self, frame, n):
        """Return a copy of ``frame`` keeping only the last ``n`` calendar months,
        anchored on the latest month present in the data."""
        if frame is None or frame.empty or 'Date' not in frame.columns:
            return frame.copy() if frame is not None else frame
        df = frame.copy()
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        if df.empty:
            return df
        latest = df['Date'].dt.to_period('M').max()
        cutoff = (latest - (n - 1)).start_time
        return df[df['Date'] >= cutoff]

    def _narrative_sections(self, anomaly_count: int) -> dict:
        """Per-section instructions for the parallel narrative calls.

        Each entry is one short, self-contained prompt: the section name and the
        length/angle expected of it. The custom section only exists when the user
        actually asked for something, so an unrequested report skips that call
        entirely rather than paying for a "No custom request." paragraph.

        The wording matters as much as the fan-out. Two defects showed up in live
        runs against the label-in-the-instruction form below: the model echoed the
        label back ("Anomaly Explanation: ...") into a section the PDF had already
        headed, and "3 recommendations" reliably came back as a numbered list,
        which the "plain text, no markdown" instruction did not stop. The label is
        now trailing rather than leading so there is nothing to echo, the output
        shape is named explicitly, and the custom request gets a length bound
        because "directly address this" alone produced 2000+ character answers
        that swamped the page it sat on.
        """
        sections = {
            "exec": "Write 2-3 sentences of plain prose on overall financial health.",
            "rev": "Write 2 sentences of plain prose on revenue performance.",
            "exp": "Write 2 sentences of plain prose on spending performance.",
            "anom": (
                "Write 2 sentences of plain prose on the significance of the "
                f"{anomaly_count} anomalies."
            ),
            "rec": (
                "Write 3 actionable CFO recommendations as a single flowing "
                "paragraph of plain prose. Do not number or bullet them."
            ),
        }
        if self.custom_instructions:
            sections["custom"] = (
                "Answer this request in at most 4 sentences of plain prose: "
                f"{self.custom_instructions}"
            )
        return sections

    def _narrative_section(self, item, *, system_prompt, data_block,
                           provider, model, api_key, create_llm):
        """Generate one narrative section.

        Never raises. A timeout, a provider error or an empty response resolves to
        that section's placeholder, which is the whole point of splitting the pass
        up: the four healthy sections still reach the PDF.
        """
        key, instruction = item
        # Writes to stderr rather than logging because this runs inside the
        # reporting-mcp subprocess, which never configures a log handler, so an
        # INFO log record here would be dropped on the floor. One line per section
        # is the visibility this used to get from a single timing line.
        started = time.perf_counter()
        try:
            # A client per section rather than one shared across the pool: the
            # provider SDKs are not documented as thread-safe, and each section
            # makes exactly one call, so there is nothing to reuse anyway. The
            # factory is passed in because the import in generate_llm_narrative is
            # deliberately function-local, and so is not visible from this thread.
            client_kwargs = {
                "request_timeout": _NARRATIVE_SECTION_TIMEOUT,
                "api_key": api_key,
                "max_retries": 1,
            }
            # `reasoning_effort` used to ride inside model_kwargs, which
            # langchain-groq 1.x rejects outright: it declares reasoning_effort as
            # a real model field and raises "should be specified explicitly" if it
            # arrives via model_kwargs. Every section therefore failed to
            # construct and the whole narrative fell back to placeholder text.
            # Passed top-level it is honoured by Groq and OpenAI. Google has no
            # such field, so it is only forwarded to providers that declare one.
            if (provider or "").lower() in _REASONING_EFFORT_PROVIDERS:
                client_kwargs["reasoning_effort"] = "low"
            client = create_llm(
                provider=provider,
                model=model,
                **client_kwargs,
            )
            response = client.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": (
                        f"DATA:\n{data_block}\n\n"
                        f"Write ONLY this section as plain text, no markdown: {instruction}"
                    )},
                ],
                config={"callbacks": []}
            )

            content = response.content
            # Most providers hand back a string, but the chat-shaped ones return a
            # list of content blocks. Joining keeps one section from crashing the
            # pass purely because of the response shape.
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            text = (content or "").strip()
            if not text:
                raise ValueError("provider returned an empty section")
            sys.stderr.write(
                f"[REPORT GEN] section {key} ok in {(time.perf_counter() - started) * 1000.0:.0f}ms\n"
            )
            return key, text
        except Exception as e:
            sys.stderr.write(
                f"[REPORT GEN ERROR] section {key} failed after "
                f"{(time.perf_counter() - started) * 1000.0:.0f}ms: {e}\n"
            )
            return key, self._NARRATIVE_FALLBACKS.get(key, "N/A")

    def generate_llm_narrative(self) -> dict:
        sys.stderr.write("[REPORT GEN] Starting LLM narrative generation...\n")
        
        from app.services.llm_factory import create_llm

        # Use the user's configured LLM settings when available.
        provider = self.llm_config.get("provider") or "groq"
        model = self.llm_config.get("model")
        api_key = self.llm_config.get("api_key")
        sys.stderr.write(f"[REPORT GEN] LLM config: provider={provider}, model={model}, api_key={'set' if api_key else 'None'}\n")

        if not api_key:
            raw_key = os.environ.get("GROQ_API_KEY", "")
            api_key = raw_key.strip().strip('"').strip("'")
            if api_key and provider == "groq" and not model:
                model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

        if not api_key:
            sys.stderr.write("[REPORT GEN WARNING] No valid API key found. Skipping narrative.\n")
            return {
                "exec": "LLM narrative generation skipped. No API key available.",
                "rev": "N/A", "exp": "N/A", "anom": "N/A", "rec": "N/A", "custom": "N/A"
            }

        total_spend = self.expenses['Amount'].sum() if not self.expenses.empty else 0
        total_rev = self.revenue['Amount'].sum() if not self.revenue.empty else 0
        burn_rate = total_spend - total_rev
        profit = total_rev - total_spend
        anomaly_count = len(self.anomalies)

        top_exp_cat = self.expenses.groupby('Category')['Amount'].sum().idxmax() if not self.expenses.empty else "None"
        top_rev_cat = self.revenue.groupby('Category')['Amount'].sum().idxmax() if not self.revenue.empty else "None"

        monthly_exp_str = "None"
        monthly_rev_str = "None"
        # The charts and tables already carry the full monthly series, so the
        # narrative prompt only needs a recent window. Listing every month of a
        # 60-month report made the prompt (and the round trip) needlessly large.
        prompt_months = 6
        if not self.expenses.empty and not self.expenses['Date'].isna().all():
            m_exp = self.expenses.groupby(self.expenses['Date'].dt.to_period('M'))['Amount'].sum().tail(prompt_months)
            monthly_exp_str = ", ".join([f"{d.strftime('%b %Y')}: ${v:,.0f}" for d, v in m_exp.items()])
        if not self.revenue.empty and not self.revenue['Date'].isna().all():
            m_rev = self.revenue.groupby(self.revenue['Date'].dt.to_period('M'))['Amount'].sum().tail(prompt_months)
            monthly_rev_str = ", ".join([f"{d.strftime('%b %Y')}: ${v:,.0f}" for d, v in m_rev.items()])

        # FIX BUG 3: safe .get() access on budget breach dicts
        breach_summary = ", ".join([
            f"{b.get('Category', '?')} (+{b.get('Percent_Over', 'N/A')})"
            for b in self.budget_breaches
        ]) if self.budget_breaches else "None"

        system_prompt = "You are an expert AI Business CFO (Chief Financial Officer). Your task is to provide a highly professional CFO: Executive report narrative."

        # Average monthly expense, matching the "Avg Burn Rate" KPI card on page one.
        # The prompt used to offer only a whole-period burn figure, and live runs
        # showed the model describing that period total as "a monthly burn rate of
        # $42,000" while the KPI card printed $71,950/mo beside it: two different
        # burn rates in one document. Both are now stated, each labelled with the
        # period it covers.
        if not self.expenses.empty and not self.expenses['Date'].isna().all():
            _m = self.expenses.set_index('Date').resample('ME')['Amount'].sum()
            avg_monthly_spend = _m.mean() if not _m.empty else total_spend
        else:
            avg_monthly_spend = total_spend

        # Every section gets the same facts; only the instruction differs, so the
        # block is built once here and passed to each worker.
        data_block = (
            f"- Total Revenue (whole reporting period): ${total_rev:,.2f}\n"
            f"- Total Expenses (whole reporting period): ${total_spend:,.2f}\n"
            f"- Period Burn (whole period, NOT monthly): ${burn_rate:,.2f}\n"
            f"- Average Monthly Spend: ${avg_monthly_spend:,.2f}\n"
            f"- Net Profit (whole reporting period): ${profit:,.2f}\n"
            f"- Top Expense Category: {top_exp_cat}\n"
            f"- Top Revenue Source: {top_rev_cat}\n"
            f"- Anomalies Detected: {anomaly_count}\n"
            f"- Month-wise Expenses: {monthly_exp_str}\n"
            f"- Month-wise Revenue: {monthly_rev_str}\n"
            f"- BUDGET BREACHES: {breach_summary}\n"
            "- Label every figure with its period. Do not describe a whole-period "
            "total as a monthly or weekly figure, and do not invent figures that "
            "are not listed here."
        )

        sections = self._narrative_sections(anomaly_count)

        # FORCE DISABLE TRACING for these internal tool calls.
        # Stalling occurs because LangSmith's background threads can deadlock
        # or fail to initialize correctly when called from within an MCP tool subprocess.
        #
        # Toggled once around the whole pool rather than per worker: the old code
        # flipped this inside the single call, and doing that from several threads
        # at once would race on the environment for no benefit.
        original_tracing = os.environ.get("LANGCHAIN_TRACING_V2")
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        started = time.perf_counter()
        try:
            sys.stderr.write(
                f"[REPORT GEN] Calling LLM ({provider}/{model}) for {len(sections)} "
                "narrative sections in parallel [Tracing: FORCED OFF]...\n"
            )
            worker = functools.partial(
                self._narrative_section,
                system_prompt=system_prompt,
                data_block=data_block,
                provider=provider,
                model=model,
                api_key=api_key,
                create_llm=create_llm,
            )
            with ThreadPoolExecutor(
                max_workers=min(len(sections), _NARRATIVE_MAX_WORKERS),
                thread_name_prefix="cfo_narrative",
            ) as pool:
                # pool.map re-raises whatever a worker threw, but _narrative_section
                # swallows everything, so a section can only ever come back as text.
                narrative = dict(pool.map(worker, sections.items()))
        finally:
            # Restore tracing on every path. Previously the restore sat after
            # the call, so a timeout or provider error left tracing disabled
            # for the rest of the subprocess.
            if original_tracing is not None:
                os.environ["LANGCHAIN_TRACING_V2"] = original_tracing
            else:
                os.environ.pop("LANGCHAIN_TRACING_V2", None)

        # The custom section is only requested when there is something to answer,
        # so the key can be absent. The PDF builder tests it with .get() and a
        # truthiness check, and "N/A" is truthy, so normalise to empty rather than
        # the placeholder or an unrequested report grows a stub section.
        narrative.setdefault("custom", "")

        sys.stderr.write(
            f"[REPORT GEN] LLM narrative took {(time.perf_counter() - started) * 1000.0:.0f}ms "
            f"across {len(sections)} parallel sections "
            f"(worker cap {_NARRATIVE_MAX_WORKERS}).\n"
        )
        return narrative

    def _save_chart(self, key: str, width_in: float, height_in: float) -> str:
        """Save the figure the caller just drew, recording its placed size.

        The caller owns the ``plt.figure(figsize=...)``; this must not create a
        new one or it would serialise an empty canvas.
        """
        path = os.path.join(self._chart_dir, f"{key}.png")
        plt.savefig(path, dpi=_CHART_DPI)
        plt.close()
        self._chart_size[key] = (width_in, height_in)
        return path

    def generate_charts(self):
        sys.stderr.write("[REPORT GEN] Starting chart generation...\n")
        charts = {}
        # Every run gets its own directory. The previous code wrote fixed names
        # ('rev_bar.png', ...) into the process CWD, so two users generating at
        # once overwrote each other's images mid-render.
        self._chart_dir = tempfile.mkdtemp(prefix="cfo_charts_")
        self._chart_size = {}

        half_w, half_h = _CHART_HALF_SIZE
        full_w, full_h = _CHART_FULL_SIZE

        # --- REVENUE CHARTS ---
        if not self.revenue.empty:
            plt.figure(figsize=(half_w, half_h))
            rev_cat = self.revenue.groupby('Category')['Amount'].sum().sort_values(ascending=False).head(5)
            rev_cat.plot(kind='bar', color='#2ecc71')
            plt.title('Top Revenue Streams', fontsize=10)
            plt.ylabel('Amount ($)', fontsize=8)
            plt.xticks(rotation=0, fontsize=8)
            plt.yticks(fontsize=8)
            plt.tight_layout()
            charts['rev_bar'] = self._save_chart('rev_bar', half_w, half_h)

            if not self.revenue['Date'].isna().all():
                plt.figure(figsize=(half_w, half_h))
                rev_trend = self.revenue.set_index('Date').resample('ME')['Amount'].sum()
                rev_trend.plot(kind='line', marker='o', color='#27ae60', linewidth=2)
                plt.title('Monthly Revenue Trend', fontsize=10)
                plt.ylabel('Amount ($)', fontsize=8)
                plt.xlabel('Month', fontsize=8)
                plt.xticks(fontsize=8)
                plt.yticks(fontsize=8)
                plt.tight_layout()
                charts['rev_trend'] = self._save_chart('rev_trend', half_w, half_h)

        # --- EXPENSE CHARTS ---
        if not self.expenses.empty:
            plt.figure(figsize=(half_w, half_h))
            exp_cat = self.expenses.groupby('Category')['Amount'].sum().sort_values(ascending=False).head(5)
            exp_cat.plot(kind='bar', color='#e74c3c')
            plt.title('Top Expense Categories', fontsize=10)
            plt.ylabel('Amount ($)', fontsize=8)
            plt.xticks(rotation=0, fontsize=8)
            plt.yticks(fontsize=8)
            plt.tight_layout()
            charts['exp_bar'] = self._save_chart('exp_bar', half_w, half_h)

            if not self.expenses['Date'].isna().all():
                plt.figure(figsize=(half_w, half_h))
                exp_trend = self.expenses.set_index('Date').resample('ME')['Amount'].sum()
                exp_trend.plot(kind='line', marker='o', color='#c0392b', linewidth=2)
                plt.title('Monthly Expense Trend', fontsize=10)
                plt.ylabel('Amount ($)', fontsize=8)
                plt.xlabel('Month', fontsize=8)
                plt.xticks(fontsize=8)
                plt.yticks(fontsize=8)
                plt.tight_layout()
                charts['exp_trend'] = self._save_chart('exp_trend', half_w, half_h)

        # --- COMPARISON CHARTS ---
        if not self.df.empty and not self.df['Date'].isna().all():
            exp_trend = self.expenses.set_index('Date').resample('ME')['Amount'].sum() if not self.expenses.empty else pd.Series(dtype=float)
            rev_trend = self.revenue.set_index('Date').resample('ME')['Amount'].sum() if not self.revenue.empty else pd.Series(dtype=float)

            trend_df = pd.DataFrame({'Revenue': rev_trend, 'Expense': exp_trend}).fillna(0)

            # Remove months with absolutely no activity to prevent huge gaps in charts
            trend_df = trend_df[(trend_df['Revenue'] != 0) | (trend_df['Expense'] != 0)]

            if not trend_df.empty:
                plt.figure(figsize=(full_w, full_h))
                ax = trend_df[['Revenue', 'Expense']].plot(kind='line', marker='o', color=['#2ecc71', '#e74c3c'], linewidth=2)
                plt.title('Revenue vs Expense Comparison', fontsize=12)
                plt.ylabel('Amount ($)', fontsize=9)
                plt.xlabel('Month', fontsize=9)
                plt.yticks(fontsize=8)
                plt.grid(True, linestyle='--', alpha=0.7)

                # Format X-axis labels nicely
                nice_labels = [d.strftime('%b %Y') for d in trend_df.index]
                plt.xticks(trend_df.index, nice_labels, rotation=45, fontsize=8)

                plt.tight_layout()
                handles, labels = ax.get_legend_handles_labels()
                if labels:
                    ax.legend(handles, labels, fontsize=8)
                charts['comp_trend'] = self._save_chart('comp_trend', full_w, full_h)

                plt.figure(figsize=(full_w, full_h))
                trend_df['Profit'] = trend_df['Revenue'] - trend_df['Expense']
                colors_bar = ['#2ecc71' if x >= 0 else '#e74c3c' for x in trend_df['Profit']]

                # Use range-based index for bar plot to prevent temporal spacing issues
                plt.bar(range(len(trend_df)), trend_df['Profit'], color=colors_bar)
                plt.title('Monthly Net Profit Margin', fontsize=12)
                plt.ylabel('Amount ($)', fontsize=9)
                plt.xlabel('Month', fontsize=9)
                nice_labels = [d.strftime('%b %Y') for d in trend_df.index]
                plt.xticks(range(len(nice_labels)), nice_labels, rotation=45, fontsize=8)
                plt.yticks(fontsize=8)
                plt.grid(axis='y', linestyle='--', alpha=0.7)
                plt.tight_layout()
                charts['profit_bar'] = self._save_chart('profit_bar', full_w, full_h)

        sys.stderr.write(f"[REPORT GEN] Generated {len(charts)} charts.\n")
        return charts

    def _chart_image(self, charts: dict, key: str):
        """Build an ``Image`` flowable scaled to the size the chart was rendered at."""
        if key not in charts:
            return None
        width_in, height_in = self._chart_size[key]
        return Image(charts[key], width=width_in * inch, height=height_in * inch)

    def build_kpi_cards(self):
        total_spend = self.expenses['Amount'].sum() if not self.expenses.empty else 0
        total_rev = self.revenue['Amount'].sum() if not self.revenue.empty else 0
        profit = total_rev - total_spend

        if not self.expenses.empty and not self.expenses['Date'].isna().all():
            monthly_exp = self.expenses.set_index('Date').resample('ME')['Amount'].sum()
            burn_rate = monthly_exp.mean() if not monthly_exp.empty else 0
        else:
            burn_rate = total_spend

        figures = (
            ("Gross Revenue", total_rev, "", "#1e8449", "#eafaf1"),
            ("Total Expenses", total_spend, "", "#c0392b", "#fdedec"),
            ("Net Profit", profit, "", "#1f618d", "#eaf2f8"),
            ("Avg Burn Rate", burn_rate, "/mo", "#b9770e", "#fef5e7"),
        )

        # Four cards plus three gutters span the printable width exactly.
        gutter = 10.0
        card_width = (letter[0] - self._page_margins * 2 - 3 * gutter) / 4
        cell_padding = 10.0
        inner = card_width - cell_padding * 2

        values = [format_currency(raw) + suffix for _, raw, suffix, _, _ in figures]

        # Shrink the value type until every figure fits on a single line. A wrap
        # would split the number in half, which also breaks the report-content
        # eval (it reads the value off the last line of the cell).
        value_size = 15.0
        widest = max(stringWidth(v, "Helvetica-Bold", value_size) for v in values)
        while value_size > 8.0 and widest > inner:
            value_size -= 0.5
            widest = max(stringWidth(v, "Helvetica-Bold", value_size) for v in values)

        cells, col_widths, card_cmds = [], [], []
        for index, (label, raw, suffix, accent, tint) in enumerate(figures):
            col = index * 2
            if index:
                cells.append("")
                col_widths.append(gutter)
            value_text = format_currency(raw) + suffix
            # Only net profit is signed-meaningful, so only it changes colour.
            value_colour = "#1b2631"
            if label == "Net Profit":
                value_colour = "#c0392b" if raw < 0 else "#1e8449"
            cells.append(Paragraph(
                f'<font size="7.5" color="#5d6d7e">{escape(label)}</font><br/>'
                f'<font size="{value_size:g}" color="{value_colour}"><b>{escape(value_text)}</b></font>',
                self.styles['KPICard'],
            ))
            col_widths.append(card_width)
            card_cmds.append(('BACKGROUND', (col, 0), (col, 0), colors.HexColor(tint)))
            card_cmds.append(('LINEABOVE', (col, 0), (col, 0), 2.5, colors.HexColor(accent)))

        style_cmds = [
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), cell_padding),
            ('RIGHTPADDING', (0, 0), (-1, -1), cell_padding),
            ('TOPPADDING', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
            # A light grid is what makes the cards read as separate tiles, and it
            # is also the only thing giving the table cell boundaries: the report
            # -content eval recovers each KPI by detecting them, so a borderless
            # tile row parses as "no table" and every KPI reads back missing.
            # It must come before LINEABOVE, since a later command on the same
            # edge wins and would otherwise paint the accent bar back to grey.
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dfe6e9')),
        ]
        style_cmds.extend(card_cmds)
        # Gutters stay white so the cards read as four separate tiles.
        for gutter_col in (1, 3, 5):
            style_cmds.append(('LEFTPADDING', (gutter_col, 0), (gutter_col, 0), 0))
            style_cmds.append(('RIGHTPADDING', (gutter_col, 0), (gutter_col, 0), 0))

        t = Table([cells], colWidths=col_widths)
        t.setStyle(TableStyle(style_cmds))
        return t

    def build_summary_table(self, df_type):
        df_subset = self.revenue if df_type == 'Revenue' else self.expenses
        if df_subset.empty:
            return Paragraph(f"No {df_type} data available.", self.styles['Normal'])

        summary = df_subset.groupby('Category')['Amount'].agg(['sum', 'count', 'mean']).reset_index()
        summary = summary.sort_values('sum', ascending=False).head(5)

        table_data = [['Category', 'Total Amount', 'Count', 'Avg Amount']]
        for _, row in summary.iterrows():
            table_data.append([
                plain_text(row['Category'])[:20],
                f"${row['sum']:,.2f}",
                str(int(row['count'])),
                f"${row['mean']:,.2f}"
            ])

        t = Table(table_data, colWidths=[140, 100, 60, 100])
        bg_color = '#27ae60' if df_type == 'Revenue' else '#c0392b'

        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(bg_color)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f9f9f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7'))
        ]))
        return t

    def build_budget_breach_tables(self):
        """Roll the breach records up per category, then list the worst months.

        Every breach record is one (category, month) pair, so a user with a few
        years of history produces 50+ records. Rendering them one per row without
        the month produced a wall of identical-looking "Travel / $200,000" lines
        that spanned two pages and read as duplicate noise. The reader actually
        wants the aggregate first and the worst individual months second.
        """
        records = [b for b in (self.budget_breaches or []) if isinstance(b, dict)]
        if not records:
            return None

        def month_of(record):
            return plain_text(record.get("MonthYear") or record.get("Month") or "")

        def percent_of(record):
            stored = record.get("Percent_Over")
            value = _parse_percent(stored)
            # Fall back to computing it when the stored string is unusable.
            if not value:
                limit = _parse_number(record.get("Limit"))
                if limit > 0:
                    value = _parse_number(record.get("Overspend")) / limit * 100.0
            return value

        by_category = {}
        for record in records:
            category = plain_text(record.get("Category") or "Unknown")
            entry = by_category.setdefault(category, {
                "months": set(), "over": 0.0, "worst_over": 0.0, "worst_pct": 0.0, "limit": 0.0,
            })
            over = _parse_number(record.get("Overspend"))
            pct = percent_of(record)
            entry["months"].add(month_of(record))
            entry["over"] += over
            entry["limit"] = max(entry["limit"], _parse_number(record.get("Limit")))
            entry["worst_over"] = max(entry["worst_over"], over)
            entry["worst_pct"] = max(entry["worst_pct"], pct)

        # Column widths are authored against a 540pt frame (letter minus the
        # 36pt margins) and rescaled so the tables always fill the real one.
        printable = letter[0] - self._page_margins * 2

        def scaled(widths):
            return [w * printable / 540.0 for w in widths]

        flowables = []

        # ---- Roll-up: the shape of the problem, one line per category ---- #
        rollup_rows = [["Category", "Monthly Limit", "Total Overspend", "Worst Month", "Worst % Over", "Months Over"]]
        rollup_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3c9a6")),
        ]
        ordered = sorted(by_category.items(), key=lambda kv: kv[1]["over"], reverse=True)
        for position, (category, entry) in enumerate(ordered):
            rollup_rows.append([
                category,
                format_currency(entry["limit"]),
                format_currency(entry["over"]),
                format_currency(entry["worst_over"]),
                f"{entry['worst_pct']:,.1f}%",
                str(len(entry["months"])),
            ])
            if position % 2 == 1:
                rollup_style.append(("BACKGROUND", (0, position + 1), (-1, position + 1), colors.HexColor("#fdf6ee")))
        rollup = Table(rollup_rows, colWidths=scaled((110, 90, 100, 100, 80, 60)), repeatRows=1)
        rollup.setStyle(TableStyle(rollup_style))
        rollup.hAlign = "LEFT"
        flowables.append(rollup)
        flowables.append(Spacer(1, 14))

        # ---- Detail: the worst individual months, bounded ---- #
        flowables.append(Paragraph(
            f"Worst {min(len(records), self._breach_detail_rows)} months by percentage over budget",
            self.styles["Heading3"],
        ))
        flowables.append(Spacer(1, 6))

        ranked = sorted(
            records,
            key=lambda r: (percent_of(r), _parse_number(r.get("Overspend"))),
            reverse=True,
        )
        shown = ranked[: self._breach_detail_rows]

        detail_rows = [["Month", "Category", "Monthly Limit", "Actual", "Overspend", "% Over"]]
        detail_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e6b0aa")),
        ]
        for position, record in enumerate(shown):
            pct = percent_of(record)
            detail_rows.append([
                month_of(record) or "n/a",
                plain_text(record.get("Category") or "Unknown"),
                format_currency(record.get("Limit", 0)),
                format_currency(record.get("Actual", 0)),
                format_currency(record.get("Overspend", 0)),
                f"{pct:,.1f}%",
            ])
            # Tint by how badly the month blew through its budget.
            tint = "#f8d7da" if pct >= 100 else "#fdebd0" if pct >= 25 else None
            if tint:
                detail_style.append(("BACKGROUND", (0, position + 1), (-1, position + 1), colors.HexColor(tint)))

        omitted = len(records) - len(shown)
        if omitted > 0:
            detail_rows.append([f"{omitted} further breaching month(s) omitted - see the roll-up above"] + [""] * 5)
            style_row = len(detail_rows) - 1
            detail_style.extend([
                ("SPAN", (0, style_row), (-1, style_row)),
                ("BACKGROUND", (0, style_row), (-1, style_row), colors.HexColor("#f2f3f4")),
                ("TEXTCOLOR", (0, style_row), (-1, style_row), colors.HexColor("#5d6d7e")),
                ("FONTNAME", (0, style_row), (-1, style_row), "Helvetica-Oblique"),
                ("FONTSIZE", (0, style_row), (-1, style_row), 7.5),
                ("ALIGN", (0, style_row), (-1, style_row), "LEFT"),
            ])

        detail = Table(detail_rows, colWidths=scaled((72, 108, 92, 92, 92, 84)), repeatRows=1)
        detail.setStyle(TableStyle(detail_style))
        detail.hAlign = "LEFT"
        flowables.append(detail)
        return flowables

    def build_anomaly_table(self):
        if self.anomalies.empty:
            return Paragraph(
                "No statistical anomalies were detected in this period. This check "
                "covers spend outliers, duplicates and rule-based exceptions; it is "
                "separate from the budget limit breaches listed above.",
                self.styles['Normal']
            )

        # FIX BUG 2: original code used row.get() on a pandas Series which raises
        # AttributeError when the column doesn't exist. Use 'in row.index' guard instead.
        def get_reason(row):
            r = []
            if 'Anomaly_ZScore' in row.index and row['Anomaly_ZScore']:
                r.append("Z-Score")
            if 'Anomaly_IQR' in row.index and row['Anomaly_IQR']:
                r.append("IQR")
            if 'Anomaly_RuleBased' in row.index and row['Anomaly_RuleBased']:
                r.append("Rule-Based")
            return " + ".join(r) if r else "Unknown"

        self.anomalies = self.anomalies.copy()
        self.anomalies['Reason'] = self.anomalies.apply(get_reason, axis=1)

        severity_order = {'Critical': 0, 'High': 1, 'Medium': 2, 'Normal': 3}
        sorted_anomalies = self.anomalies.sort_values(
            by=['Severity'],
            key=lambda x: x.map(lambda v: severity_order.get(v, 99))
        ).head(15)

        table_data = [['Date', 'Type', 'Entity', 'Amount', 'Severity', 'Reason']]
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8e44ad')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7'))
        ]

        for i, (_, row) in enumerate(sorted_anomalies.iterrows()):
            date_str = str(row['Date'].date()) if pd.notna(row['Date']) else "N/A"
            table_data.append([
                date_str,
                plain_text(row.get('Type', '')),
                Paragraph(markup_text(plain_text(row.get('Entity', ''))[:30]), self.styles['TableText']),
                f"${row['Amount']:,.2f}",
                plain_text(row.get('Severity', '')),
                Paragraph(markup_text(row['Reason']), self.styles['TableText'])
            ])
            row_idx = i + 1
            severity = row.get('Severity', '')
            if severity == 'Critical':
                style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#ffcccc')))
            elif severity == 'High':
                style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#ffe6cc')))

        t = Table(table_data, colWidths=[65, 55, 90, 75, 60, 175])
        t.setStyle(TableStyle(style_cmds))
        return t

    def build_monthly_revenue_table(self):
        """Builds a table showing total revenue for each month."""
        if self.revenue.empty:
            return None

        # Group by Month-Year
        df_monthly = self.revenue.copy()
        df_monthly['Month'] = df_monthly['Date'].dt.strftime('%b %Y')
        # Ensure we keep the temporal order
        df_monthly['Month_Sort'] = df_monthly['Date'].dt.to_period('M')
        
        table_data = [["Month", "Total Revenue", "Transaction Count", "Avg Transaction"]]
        
        grouped = df_monthly.groupby(['Month_Sort', 'Month'])['Amount'].agg(['sum', 'count', 'mean']).reset_index()
        grouped.sort_values('Month_Sort', inplace=True)
        
        for _, row in grouped.iterrows():
            table_data.append([
                row['Month'],
                f"${row['sum']:,.2f}",
                str(row['count']),
                f"${row['mean']:,.2f}"
            ])
            
        t = Table(table_data, colWidths=[120, 120, 120, 120])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ]))
        return t

    def _cleanup_charts(self):
        if self._chart_dir:
            shutil.rmtree(self._chart_dir, ignore_errors=True)
            self._chart_dir = None

    @property
    def report_period(self) -> str:
        """Human-readable span of the transactions actually in the report."""
        if self.df is None or self.df.empty or "Date" not in self.df.columns:
            return ""
        dates = pd.to_datetime(self.df["Date"], errors="coerce").dropna()
        if dates.empty:
            return ""
        return f"{dates.min():%B %Y} - {dates.max():%B %Y}"

    def generate_pdf(self):
        pdf_started = time.perf_counter()
        doc = SimpleDocTemplate(
            self.output_path, pagesize=letter,
            rightMargin=self._page_margins, leftMargin=self._page_margins,
            topMargin=self._margin_y, bottomMargin=self._margin_y
        )
        period = self.report_period
        sys.stderr.write("[REPORT GEN] Starting PDF generation pipeline...\n")
        # The narrative is a set of network round trips (now fanned out in
        # parallel, so bounded by the slowest section) and the charts are ~5s of
        # CPU-bound matplotlib. They used to run back to back; running them
        # together hides the chart time entirely behind the LLM call.
        self.elements = []
        components_started = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cfo_report") as pool:
                narrative_future = pool.submit(self.generate_llm_narrative)
                charts_future = pool.submit(self.generate_charts)
                narrative = narrative_future.result()
                charts = charts_future.result()
        except Exception:
            self._cleanup_charts()
            raise
        sys.stderr.write(
            "[REPORT GEN] Components ready in "
            f"{(time.perf_counter() - components_started) * 1000.0:.0f}ms "
            "(narrative + charts). Building elements...\n"
        )

        # --- 1. EXECUTIVE SUMMARY ---
        self.elements.append(Paragraph("BUSINESS CFO: EXECUTIVE REPORT", self.styles['BannerTitle']))
        self.elements.append(self.build_kpi_cards())
        self.elements.append(Spacer(1, 20))
        self.elements.append(Paragraph("Executive Summary", self.styles['Heading2']))
        self.elements.append(Paragraph(markup_text(narrative["exec"]), self.styles['Normal']))
        self.elements.append(Spacer(1, 20))

        # --- 2. REVENUE ANALYSIS ---
        revenue_block = []
        if narrative["rev"]:
            revenue_block.append(Paragraph(markup_text(narrative["rev"]), self.styles['Normal']))
        if 'rev_bar' in charts and 'rev_trend' in charts:
            img1 = self._chart_image(charts, 'rev_bar')
            img2 = self._chart_image(charts, 'rev_trend')
            revenue_block.append(Spacer(1, 10))
            revenue_block.append(_pair_table(img1, img2))
        self.elements.append(KeepTogether([
            Paragraph("1. Revenue Analysis", self.styles['SectionHeader']),
            *revenue_block,
        ]))

        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_summary_table('Revenue'))

        # --- 3. EXPENSE ANALYSIS ---
        expense_block = []
        if narrative["exp"]:
            expense_block.append(Paragraph(markup_text(narrative["exp"]), self.styles['Normal']))
        if 'exp_bar' in charts and 'exp_trend' in charts:
            img1 = self._chart_image(charts, 'exp_bar')
            img2 = self._chart_image(charts, 'exp_trend')
            expense_block.append(Spacer(1, 10))
            expense_block.append(_pair_table(img1, img2))
        # Keep the heading with its own narrative and charts. Previously the two
        # could be split, leaving a heading alone at the foot of a page with its
        # charts stranded overleaf.
        self.elements.append(KeepTogether([
            Paragraph("2. Expense Analysis", self.styles['SectionHeader']),
            *expense_block,
        ]))

        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_summary_table('Expense'))
        self.elements.append(Spacer(1, 20))

        # --- 4. PROFITABILITY & COMPARISON ---
        # The two full-width charts are 3.2in each, so a heading plus both is
        # almost exactly a page. Ask for the space rather than forcing a break.
        self.elements.append(CondPageBreak(5.2 * inch))
        self.elements.append(Paragraph("3. Profitability & Comparative Analysis", self.styles['SectionHeader']))
        comp = self._chart_image(charts, 'comp_trend')
        profit = self._chart_image(charts, 'profit_bar')
        if comp is not None:
            self.elements.append(comp)
        if profit is not None:
            self.elements.append(Spacer(1, 10))
            self.elements.append(profit)

        # --- 5. ANOMALY DETECTION ---
        # A hard break: the anomaly section is the part a reader flips to, and it
        # should not start halfway down a chart page.
        self.elements.append(PageBreak())
        self.elements.append(Paragraph("4. Financial Anomalies", self.styles['SectionHeader']))

        if self.budget_breaches:
            self.elements.append(Paragraph("Budget Breach Summary", self.styles['Heading2']))
            self.elements.append(Paragraph(
                f"{len(self.budget_breaches)} budget breach"
                f"{'es' if len(self.budget_breaches) != 1 else ''} were recorded across "
                "the reporting period, rolled up below by category and followed by "
                "the worst individual months.",
                self.styles['Normal']
            ))
            self.elements.append(Spacer(1, 10))
            breach_tables = self.build_budget_breach_tables()
            if breach_tables:
                self.elements.extend(breach_tables)
            self.elements.append(Spacer(1, 20))

        if narrative["anom"]:
            self.elements.append(Paragraph("Anomaly Explanation", self.styles['Heading2']))
            self.elements.append(Paragraph(markup_text(narrative["anom"]), self.styles['Normal']))
            self.elements.append(Spacer(1, 10))

        # Budget breaches and statistical anomalies are two independent pipelines
        # and either can be empty while the other is not. The report used to print
        # "0 total anomalies flagged for review" and, 40pt lower, a table of 54
        # breaches, which read as a contradiction. Label each source explicitly
        # and never let one imply the other is missing.
        self.elements.append(Paragraph("Statistical Anomalies", self.styles['Heading2']))
        self.elements.append(Paragraph(
            "Spend outliers, duplicates and rule-based checks over the transaction "
            "data. Budget limit breaches are a separate check, reported above.",
            self.styles['Normal']
        ))
        self.elements.append(Spacer(1, 10))
        # Red only when there is actually something flagged. A "0 anomalies" count
        # printed in alarm-red reads as a problem that is somehow hidden.
        banner_style = self.styles['AnomalyBanner'] if len(self.anomalies) else \
            ParagraphStyle(name='AnomalyBannerClear', parent=self.styles['Heading2'],
                           textColor=colors.HexColor('#5d6d7e'))
        self.elements.append(Paragraph(
            f"{len(self.anomalies)} total anomalies flagged for review.",
            banner_style
        ))
        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_anomaly_table())
        self.elements.append(Spacer(1, 20))

        # --- 6. CONCLUSION & RECOMMENDATIONS ---
        self.elements.append(CondPageBreak(2.5 * inch))
        self.elements.append(Paragraph("4. Conclusion & Recommendations", self.styles['SectionHeader']))
        self.elements.append(Paragraph(markup_text(narrative["rec"]), self.styles['Normal']))

        if narrative.get("custom") and "No custom request" not in narrative["custom"]:
            self.elements.append(CondPageBreak(2.5 * inch))
            self.elements.append(Paragraph("5. Custom Insights", self.styles['SectionHeader']))
            self.elements.append(Paragraph(markup_text(narrative["custom"]), self.styles['Normal']))

        # --- 7. APPENDIX ---
        # The appendix used to sit between the anomaly tables and the conclusion,
        # so the document ended with a data dump instead of its own summary. An
        # appendix belongs last, and it always starts on a fresh page.
        if not self.revenue.empty:
            self.elements.append(PageBreak())
            self.elements.append(Paragraph("Appendix: Month-Wise Revenue Breakdown", self.styles['SectionHeader']))
            self.elements.append(Paragraph(
                "The following table provides a detailed monthly breakdown of gross revenue performance for the period.",
                self.styles['Normal']
            ))
            self.elements.append(Spacer(1, 15))
            rev_table = self.build_monthly_revenue_table()
            if rev_table:
                self.elements.append(rev_table)

        # Build PDF
        build_started = time.perf_counter()
        try:
            sys.stderr.write(f"[REPORT GEN] Building PDF with {len(self.elements)} elements...\n")
            doc.build(self.elements, canvasmaker=functools.partial(
                NumberedCanvas,
                header_left="BUSINESS CFO: EXECUTIVE REPORT",
                header_right=period,
                footer_left=f"Generated {datetime.now():%d %B %Y}",
                margin_x=self._page_margins,
                margin_y=self._page_margins,
            ))
            sys.stderr.write(
                f"[REPORT GEN] Executive Report successfully generated at: {self.output_path} "
                f"(render {(time.perf_counter() - build_started) * 1000.0:.0f}ms, "
                f"total {(time.perf_counter() - pdf_started) * 1000.0:.0f}ms)\n"
            )
        except Exception as e:
            sys.stderr.write(f"[REPORT GEN ERROR] Failed to build PDF: {e}\n")
            raise e
        finally:
            # Always clean up: previously a failure inside doc.build left the
            # rendered PNGs behind in the process working directory.
            self._cleanup_charts()


if __name__ == "__main__":
    pass
