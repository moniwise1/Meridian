"""
Report Generator (BUILD SPEC sections 24, 25) - the Meridian report
standard.

Builds a management-ready PDF from a query's already-computed,
already-validated result snapshot. It never re-derives a business number
and never invents one: every figure printed here was produced by the
analysis pipeline, and a section whose underlying data is absent is
omitted rather than filled with a plausible-looking zero.

Structure, in the order a reader needs it:

  1. Cover - the question verbatim, the query id, the report status
  2. Executive answer - KPI cards, then the plain-language read
  3. Charts - each with its unit, source, and what it means
  4. Notable findings
  5. Data quality - per-area confidence, stated as a table
  6. Scope and limitations
  7. Recommended actions
  8. Methodology and sources

The one thing this file will refuse to do quietly is present a broken
figure as a sound one. When a percentage field carries values that
cannot be percentages (the 9,420% case - see report_format.py), the
chart still renders with the real values, a warning is printed beside
it, and the cover is stamped DRAFT - DATA VALIDATION REQUIRED. Repairing
the number here would hide a defect that only the customer's source can
actually fix.

Charts are drawn with fpdf2's own primitives rather than rendered by a
plotting library. That keeps the deployed image small and avoids a
headless-backend/font dependency on Railway; everything the standard
asks a chart to carry - gridlines, axis values, data labels, unit,
source note, explanation - is drawn explicitly below.
"""
import os
import uuid
from datetime import date

from fpdf import FPDF

from app.config import settings
from app.agents.report_format import (
    as_number, abbreviate, fmt_number, fmt_percent, format_metric, percent_warnings,
)

# The Meridian visual system. Deep green carries structure, mint marks
# the positive/primary accent, gold marks comparison and secondary
# series, red is reserved for genuine warnings and nothing else.
# fpdf2 wants plain (r, g, b) int tuples, not hex strings.
_DEEP_GREEN = (18, 63, 59)      # #123F3B
_MINT = (34, 185, 154)          # #22B99A
_GOLD = (197, 138, 52)          # #C58A34
_NAVY = (16, 38, 51)            # #102633
_SLATE = (82, 97, 107)          # #52616B
_PALE_GREEN = (233, 242, 240)   # #E9F2F0
_NEUTRAL = (245, 247, 247)      # #F5F7F7
_DIVIDER = (216, 225, 223)      # #D8E1DF
_RED = (184, 75, 69)            # #B84B45
_WHITE = (255, 255, 255)

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "meridian_mark.png")

_UNICODE_TO_LATIN1 = str.maketrans({
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...",
    # fpdf2's core fonts are Latin-1, which has no Naira glyph - without
    # this, "₦" silently became "?" (see _safe()'s fallback below), which
    # showed up as e.g. "?m" in a real exported report. "NGN " reads
    # unambiguously in a plain-text PDF instead of a confusing "?".
    "₦": "NGN ",
})

_CONFIDENCE_COLOR = {
    "high": _DEEP_GREEN, "moderate": _GOLD, "low": _SLATE, "unusable": _RED,
}

# A4 with 16mm side margins, per the standard's minimum.
_MARGIN = 16.0
_BAND_H = 13.0
_BODY_PT = 10.0      # standard's floor is 9pt
_CHART_LABEL_PT = 8.0


def _safe(text: str) -> str:
    # fpdf2's core fonts are Latin-1; translate common smart punctuation
    # (em dashes, curly quotes) to ASCII equivalents first, then fall back
    # to '?' only for anything genuinely unrepresentable, rather than
    # silently mangling ordinary LLM/UI punctuation.
    return (text or "").translate(_UNICODE_TO_LATIN1).encode("latin-1", "replace").decode("latin-1")


class MeridianPDF(FPDF):
    """Every content page carries the same green band, meta line and
    footer, so a multi-page report reads as one designed document rather
    than a branded first page followed by defaults. The cover suppresses
    both - it is its own full-bleed design."""

    # The cover is always the first page. This is checked by page number
    # rather than by a flag the caller flips, because fpdf2 calls
    # footer() when a page is CLOSED - by which time a flag cleared right
    # after drawing the cover has already been cleared, and the cover got
    # a page number and a footer rule it should never have had.
    COVER_PAGE = 1

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.meta_left = ""
        self.meta_right = ""

    def _is_cover(self) -> bool:
        return self.page_no() == self.COVER_PAGE

    def header(self):
        if self._is_cover():
            return
        self.set_fill_color(*_DEEP_GREEN)
        self.rect(0, 0, self.w, _BAND_H, style="F")
        if os.path.exists(_LOGO_PATH):
            self.image(_LOGO_PATH, x=self.l_margin, y=2, h=9)
            text_x = self.l_margin + 11
        else:
            text_x = self.l_margin
        self.set_xy(text_x, 2.5)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_NEUTRAL)
        self.cell(0, 8, "MERIDIAN", align="L")
        if self.meta_left:
            self.set_xy(self.l_margin, _BAND_H + 1.5)
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(*_SLATE)
            self.cell(0, 4, _safe(self.meta_left), align="L")
            self.set_xy(self.l_margin, _BAND_H + 1.5)
            self.cell(0, 4, _safe(self.meta_right), align="R")
        self.set_y(_BAND_H + 9)
        self.set_text_color(*_NAVY)

    def footer(self):
        if self._is_cover():
            return
        self.set_y(-14)
        self.set_draw_color(*_DIVIDER)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-11)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*_SLATE)
        self.cell(0, 6, "Made by Meridian - getmeridiananalytics.com", align="L")
        self.set_y(-11)
        self.cell(0, 6, f"Page {self.page_no()}", align="R")


def generate_report_pdf(title: str, question: str, insight: dict, metrics: dict = None,
                        by_group: list[dict] | None = None, data_quality: dict = None,
                        anomalies: list[dict] = None, sql: str = "", query_id: str = "",
                        charts: list[dict] | None = None, analysis: dict | None = None,
                        period: str | None = None, currency: str = "NGN") -> str:
    """Renders the report and returns the path it was written to.

    `period` and `currency` are optional and additive: a caller that has
    a real reporting period passes it, and one that does not gets a
    report that simply does not claim a period, rather than one showing
    a range nobody established.
    """
    metrics = metrics or {}
    data_quality = data_quality or {}
    anomalies = anomalies or []
    analysis = analysis or {}

    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, f"report-{uuid.uuid4().hex}.pdf")

    charts = charts or []
    # Validation runs BEFORE any page is laid out, because its outcome
    # decides what the cover says about the report's status.
    warnings: list[str] = []
    for chart in charts:
        warnings.extend(percent_warnings(
            chart.get("labels") or [], chart.get("values") or [],
            chart.get("unit"), chart.get("title"),
        ))
    insight_failed = "error" in (insight or {})
    draft = bool(warnings) or insight_failed

    pdf = MeridianPDF()
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.meta_left = f"ANALYTICS REPORT  |  {(query_id or '').upper()}"
    pdf.meta_right = f"Prepared {date.today().strftime('%d %B %Y')}"

    content_w = pdf.w - _MARGIN * 2

    # ---------------------------------------------------------------- helpers

    # Everything is left-aligned rather than justified: fpdf2 justifies by
    # stretching word spacing, which on a narrow bullet or a short line
    # opens visible rivers of white down the paragraph.
    def body(text: str, h: float = 5.2, size: float = _BODY_PT, color=_NAVY) -> None:
        if not text:
            return
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(*color)
        pdf.set_x(_MARGIN)
        pdf.multi_cell(content_w, h, _safe(text), align="L")

    def bullet(text: str) -> None:
        if not text:
            return
        pdf.set_font("Helvetica", "", _BODY_PT)
        pdf.set_text_color(*_MINT)
        pdf.set_x(_MARGIN)
        pdf.cell(4, 5.2, "-")
        pdf.set_text_color(*_NAVY)
        pdf.multi_cell(content_w - 4, 5.2, _safe(text), align="L")

    def room_for(height: float) -> float:
        """fpdf2's auto page break only fires on text writes, not on raw
        rect()/line() calls, so anything drawn with primitives has to ask
        for its space explicitly or it silently spills off the page."""
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page()
        return pdf.get_y()

    def divider() -> None:
        """The mint-and-gold rule that separates sections."""
        y = pdf.get_y()
        pdf.set_fill_color(*_MINT)
        pdf.rect(_MARGIN, y, content_w * 0.22, 0.8, style="F")
        pdf.set_fill_color(*_GOLD)
        pdf.rect(_MARGIN + content_w * 0.22, y, content_w * 0.06, 0.8, style="F")
        pdf.set_fill_color(*_DIVIDER)
        pdf.rect(_MARGIN + content_w * 0.28, y, content_w * 0.72, 0.8, style="F")
        pdf.set_y(y + 4)

    def section(kicker: str, heading: str, need: float = 34.0) -> None:
        """A kicker, a heading and a rule. `need` reserves room for the
        heading plus the first lines of whatever follows, so a heading is
        never left stranded at the foot of a page."""
        room_for(need)
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(*_MINT)
        pdf.set_x(_MARGIN)
        pdf.cell(content_w, 4, _safe(kicker.upper()), align="L")
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*_DEEP_GREEN)
        pdf.set_x(_MARGIN)
        pdf.multi_cell(content_w, 6.5, _safe(heading))
        pdf.ln(1.5)
        divider()
        pdf.set_text_color(*_NAVY)

    def callout(text: str, tone: str = "calm") -> None:
        """A panel that never splits across a page - a bottom line broken
        over a page break stops being a bottom line."""
        if not text:
            return
        fill = _PALE_GREEN if tone == "calm" else (250, 235, 234)
        edge = _MINT if tone == "calm" else _RED
        pdf.set_font("Helvetica", "", _BODY_PT)
        lines = max(1, len(pdf.multi_cell(content_w - 10, 5, _safe(text),
                                          dry_run=True, output="LINES")))
        height = lines * 5 + 7
        y = room_for(height + 3)
        pdf.set_fill_color(*fill)
        pdf.rect(_MARGIN, y, content_w, height, style="F")
        pdf.set_fill_color(*edge)
        pdf.rect(_MARGIN, y, 1.4, height, style="F")
        pdf.set_xy(_MARGIN + 6, y + 3.5)
        pdf.set_text_color(*_NAVY)
        pdf.multi_cell(content_w - 10, 5, _safe(text), align="L")
        pdf.set_y(y + height + 4)

    def kpi_cards(cards: list[tuple[str, str, str]]) -> None:
        """Up to four figures across the top of the executive answer.
        Drawn as one block so the row never splits across a page."""
        if not cards:
            return
        cards = cards[:4]
        n = len(cards)
        gap = 4.0
        card_w = (content_w - gap * (n - 1)) / n
        card_h = 26.0
        y = room_for(card_h + 6)
        for i, (label, value, note) in enumerate(cards):
            x = _MARGIN + i * (card_w + gap)
            pdf.set_fill_color(*_PALE_GREEN)
            pdf.rect(x, y, card_w, card_h, style="F")
            pdf.set_fill_color(*_MINT)
            pdf.rect(x, y, card_w, 1.2, style="F")
            pdf.set_xy(x + 3, y + 3.2)
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_text_color(*_SLATE)
            pdf.multi_cell(card_w - 6, 3.6, _safe(label.upper()), align="L")
            pdf.set_xy(x + 3, y + 11.5)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*_DEEP_GREEN)
            pdf.multi_cell(card_w - 6, 6, _safe(value), align="L")
            if note:
                pdf.set_xy(x + 3, y + 20)
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*_SLATE)
                pdf.multi_cell(card_w - 6, 3.4, _safe(note), align="L")
        pdf.set_y(y + card_h + 5)

    def table(headers: list[str], rows: list[list[str]], widths: list[float],
              statuses: list[str] | None = None) -> None:
        """A table whose header row repeats on every page it continues
        onto - a continuation page of unlabelled columns is unreadable.
        `statuses` colours the second column by confidence level."""
        if not rows:
            return
        row_h = 5.0

        def draw_header() -> None:
            y = pdf.get_y()
            pdf.set_fill_color(*_DEEP_GREEN)
            pdf.rect(_MARGIN, y, content_w, 6.5, style="F")
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_text_color(*_NEUTRAL)
            x = _MARGIN
            for head, w in zip(headers, widths):
                pdf.set_xy(x + 2, y + 1.6)
                pdf.cell(w - 4, 3.4, _safe(head), align="L")
                x += w
            pdf.set_y(y + 6.5)

        room_for(6.5 + row_h * 2)
        draw_header()
        for index, row in enumerate(rows):
            pdf.set_font("Helvetica", "", 8)
            heights = []
            for cell_text, w in zip(row, widths):
                heights.append(len(pdf.multi_cell(w - 4, row_h, _safe(str(cell_text)),
                                                  dry_run=True, output="LINES")))
            height = max(heights) * row_h + 2.5
            if pdf.get_y() + height > pdf.page_break_trigger:
                pdf.add_page()
                draw_header()
            y = pdf.get_y()
            if index % 2 == 0:
                pdf.set_fill_color(*_NEUTRAL)
                pdf.rect(_MARGIN, y, content_w, height, style="F")
            x = _MARGIN
            for col, (cell_text, w) in enumerate(zip(row, widths)):
                color = _NAVY
                if statuses and col == 1:
                    color = _CONFIDENCE_COLOR.get((statuses[index] or "").lower(), _NAVY)
                    pdf.set_font("Helvetica", "B", 8)
                else:
                    pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*color)
                pdf.set_xy(x + 2, y + 1.2)
                pdf.multi_cell(w - 4, row_h, _safe(str(cell_text)), align="L")
                x += w
            pdf.set_draw_color(*_DIVIDER)
            pdf.set_line_width(0.1)
            pdf.line(_MARGIN, y + height, _MARGIN + content_w, y + height)
            pdf.set_y(y + height)
        pdf.set_y(pdf.get_y() + 4)
        pdf.set_text_color(*_NAVY)

    # ------------------------------------------------------------- charts

    def _truncate(text: str, max_chars: int) -> str:
        s = str(text)
        return s if len(s) <= max_chars else s[: max(1, max_chars - 1)] + "."

    def _series_format(numbers: list[float]):
        """One number format for a whole chart, so an axis never mixes
        '55' with '48.10'. Millions and above are abbreviated; otherwise
        the series takes no decimals when every value is whole and one
        decimal when any value is not."""
        biggest = max((abs(n) for n in numbers), default=0.0)
        if biggest >= 1_000_000:
            return abbreviate
        decimals = 0 if all(abs(n - round(n)) < 1e-9 for n in numbers) else 1
        return lambda n: f"{n:,.{decimals}f}"

    class Plot:
        """The drawn plot area: its geometry plus the scale that maps a
        value to a y coordinate."""

        def __init__(self, x: float, y: float, w: float, h: float,
                     low: float, high: float, fmt) -> None:
            self.x, self.y, self.w, self.h = x, y, w, h
            self.low, self.high, self.fmt = low, high, fmt

        def y_of(self, value: float) -> float:
            return self.y + self.h - ((value - self.low) / (self.high - self.low)) * self.h

    def chart_frame(values: list[float]) -> Plot:
        """Draws the gridlines, y-axis values and baseline, and returns
        the plot the series draws into.

        The top of the scale is lifted above the largest value so a data
        label printed above the tallest bar or highest point still falls
        inside the plot instead of colliding with the heading above it.
        """
        plot_h = 48.0
        label_w = 17.0
        y = room_for(plot_h + 16)
        x0 = _MARGIN + label_w
        plot_w = content_w - label_w

        low = min(values + [0.0])
        high = max(values + [0.0])
        if high == low:
            high = low + 1
        high += (high - low) * 0.14
        ticks = [low + (high - low) * f for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
        fmt = _series_format(values + ticks)
        plot = Plot(x0, y, plot_w, plot_h, low, high, fmt)

        pdf.set_font("Helvetica", "", _CHART_LABEL_PT)
        for tick in ticks:
            ty = plot.y_of(tick)
            pdf.set_draw_color(*_DIVIDER)
            pdf.set_line_width(0.1)
            pdf.line(x0, ty, x0 + plot_w, ty)
            pdf.set_text_color(*_SLATE)
            pdf.set_xy(_MARGIN, ty - 1.8)
            pdf.cell(label_w - 2, 3.6, _safe(fmt(tick)), align="R")
        # The baseline is drawn last and darker so it reads as the axis
        # rather than as one more gridline.
        pdf.set_draw_color(*_SLATE)
        pdf.set_line_width(0.3)
        base_y = plot.y_of(0.0) if low < 0 else y + plot_h
        pdf.line(x0, base_y, x0 + plot_w, base_y)
        return plot

    def draw_bar(chart: dict) -> None:
        labels = chart.get("labels") or []
        values = [as_number(v) or 0.0 for v in (chart.get("values") or [])]
        if not labels or not values:
            return
        plot = chart_frame(values)
        n = len(values)
        gap = 2.5
        bar_w = max((plot.w - gap * (n - 1)) / n, 2.0)
        zero_y = plot.y_of(0.0) if plot.low < 0 else plot.y + plot.h
        for i, (label, value) in enumerate(zip(labels, values)):
            bx = plot.x + i * (bar_w + gap)
            vy = plot.y_of(value)
            top = min(vy, zero_y)
            height = abs(zero_y - vy)
            pdf.set_fill_color(*(_RED if value < 0 else _DEEP_GREEN))
            pdf.rect(bx, top, bar_w, max(height, 0.4), style="F")
            pdf.set_font("Helvetica", "", _CHART_LABEL_PT)
            pdf.set_text_color(*_SLATE)
            pdf.set_xy(bx - gap, top - 4.2)
            pdf.cell(bar_w + gap * 2, 3.6, _safe(plot.fmt(value)), align="C")
            pdf.set_xy(bx - gap, plot.y + plot.h + 1.5)
            pdf.cell(bar_w + gap * 2, 3.6,
                     _safe(_truncate(label, max(3, int(bar_w / 1.5)))), align="C")
        pdf.set_text_color(*_NAVY)
        pdf.set_y(plot.y + plot.h + 6)

    def draw_line(chart: dict) -> None:
        labels = chart.get("labels") or []
        values = [as_number(v) or 0.0 for v in (chart.get("values") or [])]
        if not labels or not values:
            return
        plot = chart_frame(values)
        n = len(values)
        step = plot.w / (n - 1) if n > 1 else 0.0
        points = [(plot.x + i * step, plot.y_of(v)) for i, v in enumerate(values)]
        pdf.set_draw_color(*_DEEP_GREEN)
        pdf.set_line_width(0.7)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            pdf.line(x1, y1, x2, y2)
        pdf.set_fill_color(*_MINT)
        for (px, py), label, value in zip(points, labels, values):
            pdf.ellipse(px - 1.1, py - 1.1, 2.2, 2.2, style="F")
            pdf.set_font("Helvetica", "", _CHART_LABEL_PT)
            pdf.set_text_color(*_SLATE)
            pdf.set_xy(px - 9, py - 4.8)
            pdf.cell(18, 3.6, _safe(plot.fmt(value)), align="C")
            pdf.set_xy(px - 9, plot.y + plot.h + 1.5)
            pdf.cell(18, 3.6, _safe(_truncate(label, 8)), align="C")
        pdf.set_text_color(*_NAVY)
        pdf.set_line_width(0.2)
        pdf.set_y(plot.y + plot.h + 6)

    def render_chart(chart: dict) -> None:
        heading = chart.get("title") or "Breakdown"
        section("Chart", heading, need=80)
        # What is measured, in what unit, over what period, from where.
        meta = []
        if chart.get("unit"):
            meta.append(f"Measured in {_safe(str(chart['unit'])).strip()}")
        if period:
            meta.append(period)
        if chart.get("location"):
            meta.append(f"Source: {chart['location']}")
        if meta:
            body("  |  ".join(meta), h=4.4, size=8, color=_SLATE)
            pdf.ln(1)
        if (chart.get("chart_type") or "").lower() == "line":
            draw_line(chart)
        else:
            # A pie draws as a bar: the same proportions read accurately
            # without a sector-fill the standard discourages anyway.
            draw_bar(chart)
        chart_warnings = percent_warnings(
            chart.get("labels") or [], chart.get("values") or [],
            chart.get("unit"), chart.get("title"),
        )
        for warning in chart_warnings:
            callout(warning, tone="warn")
        if chart.get("insight"):
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*_DEEP_GREEN)
            pdf.set_x(_MARGIN)
            pdf.cell(content_w, 4.5, "What this means")
            pdf.ln(5)
            body(chart["insight"])
            pdf.ln(2)

    # ---------------------------------------------------------------- cover

    # The cover is composed at fixed positions down to the foot of the
    # page. With auto page break left on, writing the domain line near
    # the bottom edge silently spawned a second, blank page.
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_fill_color(*_DEEP_GREEN)
    pdf.rect(0, 0, pdf.w, pdf.h, style="F")

    if os.path.exists(_LOGO_PATH):
        pdf.image(_LOGO_PATH, x=_MARGIN, y=24, h=12)
        mark_w = 14
    else:
        pdf.set_fill_color(*_MINT)
        pdf.rect(_MARGIN, 24, 11, 11, style="F")
        pdf.set_xy(_MARGIN, 25.6)
        pdf.set_font("Helvetica", "B", 15)
        pdf.set_text_color(*_WHITE)
        pdf.cell(11, 8, "M", align="C")
        mark_w = 14
    pdf.set_xy(_MARGIN + mark_w, 26.5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_WHITE)
    pdf.cell(80, 6, "M E R I D I A N", align="L")

    pdf.set_xy(_MARGIN, 104)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*_WHITE)
    pdf.multi_cell(content_w, 11.5, _safe(title), align="L")

    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*_PALE_GREEN)
    pdf.ln(2)
    pdf.multi_cell(content_w, 5.6, _safe(
        "Sales, cost, operations and data-quality analysis prepared by Meridian."
    ), align="L")

    # Status badge - the standard requires an invalid report to say so on
    # its face, not in a footnote on page 7.
    badge = "DRAFT - DATA VALIDATION REQUIRED" if draft else "ANALYTICS REPORT"
    pdf.ln(5)
    badge_y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 8)
    badge_w = pdf.get_string_width(badge) + 9
    pdf.set_fill_color(*(_RED if draft else _MINT))
    pdf.rect(_MARGIN, badge_y, badge_w, 7, style="F")
    pdf.set_xy(_MARGIN, badge_y + 0.6)
    pdf.set_text_color(*_WHITE)
    pdf.cell(badge_w, 6, _safe(badge), align="C")

    # The question block flows below the badge rather than sitting at a
    # fixed y, so a two-line title pushes it down instead of colliding
    # with it.
    pdf.ln(22)
    rule_y = pdf.get_y()
    pdf.set_fill_color(*_MINT)
    pdf.rect(_MARGIN, rule_y, 26, 0.8, style="F")
    pdf.set_xy(_MARGIN, rule_y + 5)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*_MINT)
    pdf.cell(content_w, 4, "ORIGINAL QUESTION")
    pdf.set_xy(_MARGIN, rule_y + 10)
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(*_WHITE)
    # Verbatim, per the standard - never paraphrased, never tidied up.
    pdf.multi_cell(content_w, 6.4, _safe(f'"{question}"'), align="L")

    pdf.ln(4)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_PALE_GREEN)
    ref = f"Query ID  {query_id}"
    if period:
        ref += f"  |  Source period  {period}"
    pdf.multi_cell(content_w, 5, _safe(ref), align="L")

    pdf.set_xy(_MARGIN, pdf.h - 20)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*_MINT)
    pdf.cell(content_w, 5, "getmeridiananalytics.com", align="L")
    pdf.set_auto_page_break(auto=True, margin=18)

    # ------------------------------------------------------- executive answer

    pdf.add_page()

    if insight_failed:
        section("Executive answer", "The explanation step did not complete")
        callout(
            "The analysis ran and the figures below are real, but the step that writes the "
            "explanation failed, so this report has no narrative summary. The data quality "
            "and methodology sections still describe the underlying data accurately.",
            tone="warn",
        )
    else:
        section("Executive answer", "What the numbers say")

        # KPI cards, built only from figures that actually exist. A card
        # with no value is dropped rather than shown as zero or "N/A".
        cards: list[tuple[str, str, str]] = []
        for metric in (analysis.get("metrics") or [])[:3]:
            formatted = format_metric(metric.get("label"), metric.get("value"), currency)
            if formatted:
                cards.append((str(metric.get("label") or "Metric"), formatted, ""))
        if len(cards) < 4:
            rows_analysed = as_number(data_quality.get("row_count"))
            if rows_analysed is not None:
                cards.append(("Rows analysed", fmt_number(rows_analysed), "In the verified result"))
        if len(cards) < 4:
            completeness = as_number(data_quality.get("completeness_pct"))
            if completeness is not None:
                cards.append(("Completeness", fmt_percent(completeness), "Of required fields"))
        if len(cards) < 4 and insight.get("confidence"):
            cards.append((
                "Confidence", str(insight["confidence"]).title(),
                "Stated by the analysis",
            ))
        kpi_cards(cards)

        if insight.get("what"):
            body(insight["what"])
            pdf.ln(2)

        # The rest of the answer takes one of three shapes, checked in
        # this order: the current document-only shape (extraction_summary
        # is only ever set by explain_document_only_v2 - see
        # insight_agent.py), then the OLD document-only shape ("body",
        # from the superseded explain_document_only - kept working so a
        # QueryRecord written before v2 can still be re-exported), then
        # the database-metric shape every other analysis uses.
        extraction_summary = insight.get("extraction_summary")
        legacy_body = insight.get("body")
        if extraction_summary:
            findings = insight.get("key_findings") or []
            if findings:
                section("The plain-language read", "What was found in the source", need=30)
                for finding in findings:
                    text = finding.get("finding", "")
                    where = finding.get("location", "")
                    level = finding.get("confidence", "")
                    suffix = " ".join(p for p in (f"[{where}" if where else "",
                                                  f"- {level} confidence]" if level else "]") if p)
                    bullet(f"{text} {suffix}".strip() if where or level else text)
                pdf.ln(1)
            flagged = insight.get("flagged_items") or []
            if flagged:
                section("Flagged", "Items the analysis could not stand behind", need=30)
                for item in flagged:
                    bullet(str(item))
                pdf.ln(1)
            section("Extraction", "What was read out of the source", need=26)
            body(
                f"{extraction_summary.get('total_rows_or_items', 0)} row(s)/item(s) across "
                f"{extraction_summary.get('sheets_or_pages_or_slides', 0)} sheet(s)/page(s)/slide(s). "
                f"Extraction confidence: {extraction_summary.get('extraction_confidence', 'not stated')}."
            )
            for flag in extraction_summary.get("flags", []):
                bullet(str(flag))
        elif legacy_body:
            # The Where/When/Contributors boxes below are a template for
            # one computed database metric; forcing an open-ended
            # document answer into them produced a real, reported
            # "gibberish" report, so the answer is printed as written.
            section("Analysis", "The answer in full", need=30)
            body(legacy_body)
        else:
            if insight.get("where") or insight.get("when"):
                section("Where and when", "The scope of the figures", need=26)
                if insight.get("where"):
                    bullet(f"Where: {insight['where']}")
                if insight.get("when"):
                    bullet(f"When: {insight['when']}")
            if insight.get("contributors"):
                section("Drivers", "What contributed to the result", need=26)
                body(insight["contributors"])

        if insight.get("confidence"):
            level = str(insight["confidence"]).lower()
            explanation = insight.get("confidence_explanation") or ""
            callout(f"Confidence: {insight['confidence']}. {explanation}".strip())

    # ---------------------------------------------------------------- charts

    if charts:
        for chart in charts:
            render_chart(chart)
    elif by_group:
        render_chart({
            "chart_type": "bar",
            "title": "Breakdown by group",
            "labels": [row.get("group") for row in by_group],
            "values": [row.get("total") for row in by_group],
        })

    # ------------------------------------------------------ notable findings

    if anomalies:
        section("Notable findings", "What stands out in the data", need=30)
        for anomaly in anomalies[:5]:
            bullet(
                f"{anomaly.get('what', '')} ({anomaly.get('magnitude', '')}) "
                f"[{anomaly.get('confidence', '')} confidence]"
            )
        pdf.ln(1)

    # ----------------------------------------------------------- data quality

    section("Data quality", "What can be trusted - and what cannot", need=44)
    body(
        "Good analysis separates sound business signals from fields that need repair. "
        "Nothing below has been corrected in this report; a defect is reported, not hidden."
    )
    pdf.ln(2)

    quality_rows: list[list[str]] = []
    statuses: list[str] = []
    rows_analysed = as_number(data_quality.get("row_count"))
    if rows_analysed is not None:
        quality_rows.append(["Rows analysed", "Reported", fmt_number(rows_analysed)])
        statuses.append("high")
    completeness = as_number(data_quality.get("completeness_pct"))
    if completeness is not None:
        level = "high" if completeness >= 98 else "moderate" if completeness >= 90 else "low"
        quality_rows.append(["Field completeness", level.title(), fmt_percent(completeness)])
        statuses.append(level)
    duplicates = as_number(data_quality.get("duplicate_pct"))
    if duplicates is not None:
        level = "high" if duplicates == 0 else "moderate" if duplicates < 5 else "low"
        quality_rows.append(["Duplicate rows", level.title(), fmt_percent(duplicates)])
        statuses.append(level)
    # Per-measure confidence from the analysis contract, when present.
    for name, confidence in (analysis.get("confidence") or {}).items():
        level = str(confidence.get("level", "")).replace("_", " ")
        quality_rows.append([str(name).title(), level.title(), confidence.get("reason", "")])
        statuses.append(level.split()[0] if level else "")
    if warnings:
        quality_rows.append(["Percentage fields", "Unusable",
                             "Values outside 0-100% are present; see the warning beside the chart."])
        statuses.append("unusable")

    if quality_rows:
        table(["Area", "Status", "Assessment"],
              quality_rows, [content_w * 0.26, content_w * 0.17, content_w * 0.57],
              statuses=statuses)
    for note in data_quality.get("notes", []):
        bullet(str(note))
    # The full wording of a percentage warning is printed beside the
    # chart it belongs to; repeating it here would say the same thing
    # twice in one report, so the table row points back to it instead.

    # --------------------------------------------------- scope & limitations

    scope = analysis.get("scope") or {}
    quality = analysis.get("quality") or {}
    limitations = [
        scope.get("metric_definition") or "The metric definition was not independently established.",
        *(scope.get("assumptions") or []),
        *(quality.get("limitations") or []),
    ]
    limitations = [str(item) for item in limitations if item]
    if limitations:
        section("Risks and limitations", "What these figures do not cover", need=30)
        for item in limitations:
            bullet(item)
        pdf.ln(1)

    # ------------------------------------------------- recommended actions

    # Only ever the actions the analysis itself produced. The standard
    # asks for ranked next steps; it does not permit inventing them, so
    # an analysis that offered none gets no section rather than filler.
    findings = analysis.get("findings") or []
    actions = [f.get("text", "") for f in findings
               if str(f.get("kind", "")).lower() in ("recommendation", "action", "next_step")]
    if not actions and insight.get("next_question"):
        actions = [f"Next question to ask: {insight['next_question']}"]
    if actions:
        section("Decision support", "What to do next, in priority order", need=30)
        for i, action in enumerate(actions[:5], start=1):
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*_GOLD)
            pdf.set_x(_MARGIN)
            pdf.cell(7, 5.2, f"{i:02d}")
            pdf.set_font("Helvetica", "", _BODY_PT)
            pdf.set_text_color(*_NAVY)
            pdf.multi_cell(content_w - 7, 5.2, _safe(str(action)))
            pdf.ln(0.8)
        pdf.ln(1)

    # Other findings, kept distinct from recommendations so an observation
    # is never read as advice.
    observations = [f for f in findings
                    if str(f.get("kind", "")).lower() not in ("recommendation", "action", "next_step")]
    if observations:
        section("Findings", "What the analysis established", need=28)
        for finding in observations:
            bullet(f"[{finding.get('kind', '')}] {finding.get('text', '')}")
        pdf.ln(1)

    # --------------------------------------------------------- methodology

    section("Methodology and assumptions", "How this report was produced", need=34)
    body(
        "Generated by an AI analytics agent restricted to read-only, authorized queries. "
        "All figures were computed deterministically, not by the language model; the model "
        "was used only to translate the question into a query and to interpret results that "
        "had already been computed.",
        h=4.6, size=9, color=_SLATE,
    )
    if sql:
        pdf.ln(1)
        body(f"Query: {sql}", h=4.2, size=8, color=_SLATE)
    pdf.ln(1)
    body(
        "This report reflects only the authorized tables and columns available to the "
        "requesting user, together with the data-quality notes above. Predictive or "
        "prescriptive statements, where present, are labelled as such and are not guarantees.",
        h=4.6, size=9, color=_SLATE,
    )

    evidence = analysis.get("evidence") or []
    if evidence:
        section("Source notes", "Where each figure came from", need=30)
        source_rows = [[
            str(src.get("filename") or src.get("source_id") or ""),
            str(src.get("method", "")).replace("_", " "),
            str(src.get("source_version") or "unavailable"),
        ] for src in evidence]
        table(["Source", "Method", "Version"],
              source_rows, [content_w * 0.52, content_w * 0.26, content_w * 0.22])

    pdf.output(path)
    return path
