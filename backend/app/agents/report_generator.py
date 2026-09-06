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
                          anomalies: list[dict], sql: str, query_id: str) -> str:
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

        # "body" (document-only questions only - see Insight.body's
        # docstring in insight_agent.py) is the actual answer, already
        # organized however the question itself called for. The
        # Where/When/Contributors boxes below are a template built for
        # explaining a single computed database metric - forcing an
        # open-ended document answer into them is what produced a real,
        # reported "gibberish" report, so they're skipped here in favor
        # of just printing the real answer.
        body = insight.get("body")
        if body:
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

    if by_group:
        section("Breakdown")
        col1, col2 = 100, 60
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(*_TEAL_DEEP)
        pdf.set_text_color(*_PAPER)
        pdf.cell(col1, 8, "Group", border=0, fill=True)
        pdf.cell(col2, 8, "Total", border=0, fill=True, align="R", ln=1)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_INK)
        for i, row in enumerate(by_group[:15]):
            # Alternating row banding (a very light paper tint on every
            # other row) - the same "scan a long list without losing your
            # place" job zebra-striping does in any real table, purely
            # cosmetic and never touches a value.
            if i % 2 == 1:
                pdf.set_fill_color(*_PAPER)
                fill = True
            else:
                fill = False
            pdf.cell(col1, 7, _safe(str(row["group"])), border=0, fill=fill)
            pdf.cell(col2, 7, f"{row['total']:,.2f}", border=0, fill=fill, align="R", ln=1)
        pdf.set_draw_color(*_LINE)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + col1 + col2, pdf.get_y())
        pdf.ln(4)

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
