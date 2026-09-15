"""
Report Generator (BUILD SPEC sections 24, 25). Builds a management-ready
PDF from a query's already-computed, already-validated result snapshot -
it never re-derives numbers, only lays out what the pipeline already
produced with its evidence and data-quality caveats attached.
"""
import os
import uuid
from fpdf import FPDF
from app.config import settings

# Same palette as the web app (frontend/app/globals.css) and the branded
# HTML emails (app/agents/email_delivery.py's _BRAND_* constants) - a
# downloaded report should look like it came from the same product as the
# screen it was generated from, not a generic default-styled PDF. fpdf2
# wants plain (r, g, b) int tuples, not hex strings.
_TEAL_DEEP = (18, 63, 61)      # #123f3d
_TEAL = (28, 93, 90)           # #1c5d5a
_INK = (23, 26, 28)            # #171a1c
_INK_SOFT = (86, 95, 102)      # #565f66
_LINE = (221, 224, 220)        # #dde0dc
_AMBER = (165, 105, 31)        # #a5691f
_PAPER = (245, 246, 244)       # #f5f6f4

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "meridian_mark.png")

_UNICODE_TO_LATIN1 = str.maketrans({
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...",
})

_CONFIDENCE_COLOR = {"high": _TEAL_DEEP, "moderate": _AMBER, "low": _INK_SOFT}


class MeridianPDF(FPDF):
    """A slim teal-deep header band with the wordmark on every page (fpdf2
    calls header() automatically, same guarantee footer() below already
    relies on for its own branding), plus the existing "Made by Meridian"
    footer - together these are what make a multi-page report read as one
    consistently-designed document rather than the first page being
    branded and the rest reverting to a blank default."""

    def header(self):
        self.set_fill_color(*_TEAL_DEEP)
        self.rect(0, 0, self.w, 16, style="F")
        if os.path.exists(_LOGO_PATH):
            self.image(_LOGO_PATH, x=self.l_margin, y=3, h=10)
            text_x = self.l_margin + 12
        else:
            text_x = self.l_margin
        self.set_xy(text_x, 3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*_PAPER)
        self.cell(0, 10, "MERIDIAN", align="L")
        self.set_y(20)
        self.set_text_color(*_INK)

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(*_LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_INK_SOFT)
        self.cell(0, 8, "Made by Meridian - getmeridiananalytics.com", align="L")
        self.set_y(-12)
        self.cell(0, 8, f"Page {self.page_no()}", align="R")


def _safe(text: str) -> str:
    # fpdf2's core fonts are Latin-1; translate common smart punctuation
    # (em dashes, curly quotes) to ASCII equivalents first, then fall back
    # to '?' only for anything genuinely unrepresentable, rather than
    # silently mangling ordinary LLM/UI punctuation.
    return (text or "").translate(_UNICODE_TO_LATIN1).encode("latin-1", "replace").decode("latin-1")


def _mc(pdf: FPDF, h: float, text: str) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, h, text)


def generate_report_pdf(title: str, question: str, insight: dict, metrics: dict,
                          by_group: list[dict] | None, data_quality: dict,
                          anomalies: list[dict], sql: str, query_id: str,
                          charts: list[dict] | None = None) -> str:
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, f"report-{uuid.uuid4().hex}.pdf")

    pdf = MeridianPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_text_color(*_TEAL_DEEP)
    pdf.set_font("Helvetica", "B", 18)
    _mc(pdf, 10, _safe(title))
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_INK_SOFT)
    _mc(pdf, 6, _safe(f"Question: {question}"))
    _mc(pdf, 6, _safe(f"Query ID: {query_id}"))
    pdf.ln(4)
    pdf.set_text_color(*_INK)

    def section(heading: str):
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*_TEAL_DEEP)
        _mc(pdf, 8, _safe(heading))
        # A short colored rule under the heading rather than relying on
        # bold weight alone to separate sections - the same visual role
        # the web app's `border-t border-line` dividers play between
        # ResultView.tsx's panels.
        pdf.set_draw_color(*_TEAL)
        pdf.set_line_width(0.6)
        y = pdf.get_y() + 1
        pdf.line(pdf.l_margin, y, pdf.l_margin + 24, y)
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(*_INK)

    if "error" not in insight:
        section("Executive summary")
        _mc(pdf, 6, _safe(insight.get("what", "")))
        pdf.ln(1)

        # Three possible shapes for the rest of the answer, checked in this
        # order: the current document-only shape (extraction_summary is
        # only ever set by explain_document_only_v2 - see
        # insight_agent.py), then the OLD document-only shape ("body",
        # from the now-superseded explain_document_only - kept working
        # here purely so a QueryRecord written before v2 shipped can still
        # be re-exported correctly), then the database-metric shape
        # (where/when/contributors) every other analysis uses.
        extraction_summary = insight.get("extraction_summary")
        body = insight.get("body")
        if extraction_summary:
            section("Extraction summary")
            conf = extraction_summary.get("extraction_confidence", "")
            _mc(pdf, 6, _safe(
                f"{extraction_summary.get('total_rows_or_items', 0)} row(s)/item(s) across "
                f"{extraction_summary.get('sheets_or_pages_or_slides', 0)} sheet(s)/page(s)/"
                f"slide(s) - extraction confidence: {conf}."
            ))
            for flag in extraction_summary.get("flags", []):
                _mc(pdf, 6, _safe(f"- {flag}"))

            section("Key findings")
            for kf in insight.get("key_findings", []):
                _mc(pdf, 6, _safe(
                    f"- {kf.get('finding', '')} [{kf.get('location', '')} - "
                    f"{kf.get('confidence', '')} confidence]"
                ))

            flagged = insight.get("flagged_items") or []
            if flagged:
                section("Flagged items")
                for item in flagged:
                    _mc(pdf, 6, _safe(f"- {item}"))
        elif body:
            # "body" (the old document-only shape - see the comment above)
            # is the actual answer, already organized however the
            # question itself called for. The Where/When/Contributors
            # boxes below are a template built for explaining a single
            # computed database metric - forcing an open-ended document
            # answer into them is what produced a real, reported
            # "gibberish" report, so they're skipped here in favor of just
            # printing the real answer.
            section("Analysis")
            _mc(pdf, 6, _safe(body))
        else:
            section("Where / When")
            _mc(pdf, 6, _safe(f"Where: {insight.get('where', '')}"))
            _mc(pdf, 6, _safe(f"When: {insight.get('when', '')}"))

            section("What contributed")
            _mc(pdf, 6, _safe(insight.get("contributors", "")))

        section("Confidence")
        level = (insight.get("confidence") or "").lower()
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_CONFIDENCE_COLOR.get(level, _INK_SOFT))
        pdf.write(6, _safe(insight.get("confidence", "")))
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(*_INK)
        pdf.write(6, _safe(f" — {insight.get('confidence_explanation', '')}"))
        pdf.ln(8)
    else:
        # Previously silent - a failed insight-generation step (e.g. the
        # model ran out of its response budget on an unusually large
        # question) produced a PDF with nothing between the question and
        # the Data Quality footer, no indication anything had gone wrong
        # at all. ResultView.tsx already shows a real message for this
        # exact case ("The analysis ran, but the explanation step is
        # unavailable.") - this brings the exported PDF in line with it
        # rather than leaving a downloaded report look like a hung/broken
        # analysis with no explanation.
        section("Analysis unavailable")
        _mc(pdf, 6, _safe(
            "The explanation step for this analysis failed and no summary could be generated. "
            "The data quality and methodology details below still reflect the real underlying data."
        ))
        pdf.ln(4)

    def _chart_labels(labels: list, max_chars: int) -> list[str]:
        out = []
        for label in labels:
            s = str(label)
            out.append(s if len(s) <= max_chars else s[: max(1, max_chars - 1)] + "…")
        return out

    def _ensure_room(height: float) -> float:
        # fpdf2's auto_page_break only fires on cell()/multi_cell() text
        # writes, not on raw rect()/line()/ellipse() calls - a chart drawn
        # with those primitives too close to the bottom margin would
        # otherwise silently spill past the page edge, uncaught. Forces the
        # same new-page behavior a text cell of this height would have
        # gotten for free, then returns the y to actually draw at.
        y = pdf.get_y()
        if y + height > pdf.page_break_trigger:
            pdf.add_page()
            y = pdf.get_y()
        return y

    def _draw_bar_chart(labels: list, values: list) -> None:
        # A real drawn chart (rects for bars) rather than a data table -
        # this is what makes the exported PDF actually match what
        # ResultView.tsx's GroupBars/ChartPanel show on screen, instead of
        # requiring the reader to read a number and mentally picture the
        # bar it represents.
        if not labels or not values:
            return
        n = len(labels)
        width = pdf.w - pdf.l_margin - pdf.r_margin
        chart_h = 55.0
        x0 = pdf.l_margin
        y0 = _ensure_room(chart_h + 14)
        baseline_y = y0 + chart_h
        gap = 3.0
        bar_w = max((width - gap * (n - 1)) / n, 3.0) if n else width
        max_val = max((v for v in values if isinstance(v, (int, float))), default=0)
        max_val = max_val if max_val > 0 else 1  # an all-zero/negative series still draws (flat bars), never divides by zero

        pdf.set_draw_color(*_LINE)
        pdf.set_line_width(0.2)
        pdf.line(x0, baseline_y, x0 + width, baseline_y)

        chart_labels = _chart_labels(labels, max(3, int(bar_w / 1.6)))
        for i, (label, value) in enumerate(zip(chart_labels, values)):
            v = value if isinstance(value, (int, float)) else 0
            bar_h = max((v / max_val) * (chart_h - 10), 0.0)
            bx = x0 + i * (bar_w + gap)
            by = baseline_y - bar_h
            pdf.set_fill_color(*_TEAL_DEEP)
            pdf.rect(bx, by, bar_w, bar_h, style="F")
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*_INK_SOFT)
            pdf.set_xy(bx - gap, max(by - 5, y0), )
            pdf.cell(bar_w + gap * 2, 4, _safe(f"{v:,.1f}"), align="C")
            pdf.set_xy(bx - gap, baseline_y + 1.5)
            pdf.cell(bar_w + gap * 2, 4, _safe(label), align="C")
        pdf.set_text_color(*_INK)
        pdf.set_y(baseline_y + 7)

    def _draw_line_chart(labels: list, values: list) -> None:
        if not labels or not values:
            return
        n = len(labels)
        width = pdf.w - pdf.l_margin - pdf.r_margin
        chart_h = 55.0
        x0 = pdf.l_margin
        y0 = _ensure_room(chart_h + 14)
        baseline_y = y0 + chart_h
        plot_h = chart_h - 10

        numeric = [v if isinstance(v, (int, float)) else 0 for v in values]
        max_val, min_val = max(numeric), min(numeric)
        if max_val == min_val:
            max_val = min_val + 1  # a flat series still draws a straight line, never divides by zero

        pdf.set_draw_color(*_LINE)
        pdf.set_line_width(0.2)
        pdf.line(x0, baseline_y, x0 + width, baseline_y)

        step_x = width / (n - 1) if n > 1 else 0
        points = [
            (x0 + i * step_x, baseline_y - ((v - min_val) / (max_val - min_val)) * plot_h)
            for i, v in enumerate(numeric)
        ]
        pdf.set_draw_color(*_TEAL_DEEP)
        pdf.set_line_width(0.6)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            pdf.line(x1, y1, x2, y2)

        chart_labels = _chart_labels(labels, 6)
        pdf.set_fill_color(*_TEAL_DEEP)
        for (px, py), label, v in zip(points, chart_labels, numeric):
            r = 1.0
            pdf.ellipse(px - r, py - r, r * 2, r * 2, style="F")
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*_INK_SOFT)
            pdf.set_xy(px - 9, max(py - 6, y0))
            pdf.cell(18, 4, _safe(f"{v:,.1f}"), align="C")
            pdf.set_xy(px - 9, baseline_y + 1.5)
            pdf.cell(18, 4, _safe(label), align="C")
        pdf.set_text_color(*_INK)
        pdf.set_line_width(0.2)
        pdf.set_y(baseline_y + 7)

    if charts:
        # v2 document-only charts (see insight_agent.py's render_chart
        # tool) - a list of named charts rather than one implicit
        # bar+pie pair, so each gets its own "Breakdown" section with its
        # title, falling back to "Breakdown" alone when the chart has none
        # (the deterministic computed_profile chart planner.py builds
        # doesn't set a title beyond the column name already in it).
        for chart in charts:
            heading = "Breakdown"
            if chart.get("title"):
                heading += f' — {chart["title"]}'
            section(heading)
            labels, values = chart.get("labels", []), chart.get("values", [])
            if chart.get("chart_type") == "line":
                _draw_line_chart(labels, values)
            else:
                # "pie" draws as a bar too - an accurate, honest read of
                # the same proportions without fpdf2's more involved
                # arc/sector-fill drawing, matching ChartPanel's own
                # fallback to GroupBars when a pie can't be shown.
                _draw_bar_chart(labels, values)
            if chart.get("insight"):
                _mc(pdf, 6, _safe(chart["insight"]))
                pdf.ln(2)
    elif by_group:
        section("Breakdown")
        _draw_bar_chart([row["group"] for row in by_group], [row["total"] for row in by_group])

    if anomalies:
        section("Notable findings")
        for a in anomalies[:5]:
            _mc(pdf, 6, _safe(f"- {a['what']} ({a['magnitude']}) [{a['confidence']} confidence]"))

    section("Data quality")
    _mc(pdf, 6, _safe(f"Rows analysed: {data_quality.get('row_count', 0)}"))
    _mc(pdf, 6, _safe(f"Completeness: {data_quality.get('completeness_pct', 100)}%"))
    for note in data_quality.get("notes", []):
        _mc(pdf, 6, _safe(f"- {note}"))

    section("Methodology")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_INK_SOFT)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, _safe(
        "Generated by an AI analytics agent restricted to read-only, authorized queries. "
        "All figures were computed deterministically (not by the language model); the "
        "model was used only to translate the question into SQL and to interpret the "
        "already-computed results."
    ))
    _mc(pdf, 5, _safe(f"Query: {sql}"))
    pdf.set_text_color(*_INK)

    section("Data limitations")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_INK_SOFT)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, _safe(
        "This report reflects only the authorized tables/columns available to the "
        "requesting user and the data quality notes above. Predictive or prescriptive "
        "claims, if any, are explicitly labelled as such and are not guarantees."
    ))

    pdf.output(path)
    return path
