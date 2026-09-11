"""
Presentation Generator (BUILD SPEC section 24). Builds a management deck
from the same already-computed result snapshot the report uses - every
chart/number on a slide corresponds to an actual analytical result, never
fabricated to "fill" a slide.
"""
import os
import uuid
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from app.config import settings

# Same palette as the web app (frontend/app/globals.css), the branded HTML
# emails, and the PDF report (report_generator.py's own _TEAL_DEEP etc.) -
# a downloaded deck should look like it came from the same product as
# every other Meridian surface, not python-pptx's default Office theme
# (which is what every slide used before this - no brand color was
# applied anywhere at all). RGBColor.from_string() takes a hex string
# with no leading '#'.
_TEAL_DEEP = RGBColor.from_string("123F3D")
_TEAL = RGBColor.from_string("1C5D5A")
_INK = RGBColor.from_string("171A1C")
_INK_SOFT = RGBColor.from_string("565F66")
_PAPER = RGBColor.from_string("F5F6F4")
_LINE = RGBColor.from_string("DDE0DC")

_FONT = "Arial"  # closest universally-available equivalent to the web app's Helvetica/system-ui stack

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "meridian_mark.png")


def _style_run(run, color, size=None, bold=None):
    run.font.name = _FONT
    run.font.color.rgb = color
    if size is not None:
        run.font.size = size
    if bold is not None:
        run.font.bold = bold


def _style_title(shape, color=_TEAL_DEEP):
    for p in shape.text_frame.paragraphs:
        for r in p.runs:
            _style_run(r, color, bold=True)


def _add_accent_bar(prs, slide, y=Inches(1.35)):
    """A thin teal rule under a content slide's title - the same visual
    role the web app's `border-t border-line` dividers and the PDF
    report's own colored-underline section headings play: a deliberate
    brand accent instead of relying on the title's bold weight alone."""
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.5), y, Inches(9), Pt(2.5))
    bar.fill.solid()
    bar.fill.fore_color.rgb = _TEAL
    bar.line.fill.background()
    bar.shadow.inherit = False


def _add_branding(prs, slide) -> None:
    """A small "Made by Meridian" footer on every slide - python-pptx has
    no per-slide auto-callback the way fpdf2 does, so this is called
    explicitly after each slide is built. Bottom-right, out of the way of
    the actual content (title/bullets/table all sit above this band).
    Purely cosmetic; never touches the slide's real content."""
    box = slide.shapes.add_textbox(
        prs.slide_width - Inches(3.2), prs.slide_height - Inches(0.4), Inches(3.0), Inches(0.3),
    )
    tf = box.text_frame
    tf.margin_top = 0
    tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    run = p.add_run()
    run.text = "Made by Meridian"
    _style_run(run, _INK_SOFT, size=Pt(9))


def _add_title_slide(prs, title, subtitle):
    """The one slide that gets the full teal-deep treatment (a solid
    background fill, white text, the logo mark) - a "cover" look. Every
    other slide stays on a white/paper background with teal accents
    instead: a data-heavy slide (a table, several paragraphs of analysis)
    needs the contrast and scanability a light background gives it far
    more than it needs to look like the cover."""
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _TEAL_DEEP

    if os.path.exists(_LOGO_PATH):
        slide.shapes.add_picture(_LOGO_PATH, Inches(0.6), Inches(0.6), height=Inches(0.6))

    slide.shapes.title.text = title
    for p in slide.shapes.title.text_frame.paragraphs:
        for r in p.runs:
            _style_run(r, _PAPER, bold=True)

    sub = slide.placeholders[1]
    sub.text = subtitle
    for p in sub.text_frame.paragraphs:
        for r in p.runs:
            _style_run(r, _LINE)

    footer_para = slide.shapes.add_textbox(
        prs.slide_width - Inches(3.2), prs.slide_height - Inches(0.4), Inches(3.0), Inches(0.3),
    ).text_frame.paragraphs[0]
    footer_para.alignment = PP_ALIGN.RIGHT
    run = footer_para.add_run()
    run.text = "Made by Meridian"
    # Lighter than _add_branding()'s usual _INK_SOFT - this sits directly
    # on the dark teal-deep cover background, which needs the same lighter
    # tint the subtitle text above it uses for real contrast, not the
    # ink-soft grey every other (white-background) slide's footer uses.
    _style_run(run, _LINE, size=Pt(9))
    return slide


def _add_bullets_slide(prs, title, bullets):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    _style_title(slide.shapes.title)
    _add_accent_bar(prs, slide)
    body = slide.placeholders[1].text_frame
    body.clear()
    for i, b in enumerate(bullets):
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        p.text = b
        _style_run(p.runs[0], _INK, size=Pt(16))
    _add_branding(prs, slide)
    return slide


def _add_text_slide(prs, title, text):
    """Like _add_bullets_slide, but for one long free-form answer (a
    document-only question's "body" - see Insight.body's docstring in
    insight_agent.py) rather than a handful of short bullet points -
    splitting it into paragraphs on blank lines keeps its own
    header/bullet structure readable instead of running it all together
    as one giant unbroken line the way a single bullet would."""
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    _style_title(slide.shapes.title)
    _add_accent_bar(prs, slide)
    body = slide.placeholders[1].text_frame
    body.clear()
    body.word_wrap = True
    paragraphs = [p for p in text.split("\n\n") if p.strip()] or [text]
    for i, para in enumerate(paragraphs):
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        p.text = para.strip()
        _style_run(p.runs[0], _INK, size=Pt(14))
    _add_branding(prs, slide)
    return slide


def _add_table_slide(prs, title, headers, rows):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = title
    _style_title(slide.shapes.title)
    _add_accent_bar(prs, slide)
    rows_n = min(len(rows), 12) + 1
    cols_n = len(headers)
    table_shape = slide.shapes.add_table(rows_n, cols_n, Inches(0.5), Inches(1.6), Inches(9), Inches(0.4 * rows_n))
    table = table_shape.table
    # python-pptx tables come with a built-in banded theme by default,
    # which looks fine but doesn't carry a single brand color anywhere -
    # explicit header/row fills below replace it with one that does.
    for c, h in enumerate(headers):
        cell = table.cell(0, c)
        cell.text = str(h)
        cell.fill.solid()
        cell.fill.fore_color.rgb = _TEAL_DEEP
        para = cell.text_frame.paragraphs[0]
        _style_run(para.runs[0], _PAPER, size=Pt(14), bold=True)
    for r, row in enumerate(rows[:12], start=1):
        for c, val in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(val)
            cell.fill.solid()
            # Alternating row banding on a light paper tint - the same
            # "scan a long table without losing your place" job zebra
            # striping plays in the PDF report's own Breakdown table.
            cell.fill.fore_color.rgb = _PAPER if r % 2 == 0 else RGBColor.from_string("FFFFFF")
            para = cell.text_frame.paragraphs[0]
            _style_run(para.runs[0], _INK, size=Pt(13))
    _add_branding(prs, slide)
    return slide


def generate_presentation_pptx(title: str, question: str, insight: dict, metrics: dict,
                                 by_group: list[dict] | None, data_quality: dict,
                                 anomalies: list[dict], query_id: str,
                                 charts: list[dict] | None = None) -> str:
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, f"presentation-{uuid.uuid4().hex}.pptx")

    prs = Presentation()

    _add_title_slide(prs, title, f"{question}\nQuery ID: {query_id}")

    if "error" not in insight:
        # Three possible shapes, checked in this order - see
        # report_generator.py's identical branch for the full explanation:
        # the current document-only shape (extraction_summary, from
        # explain_document_only_v2), the OLD document-only shape ("body",
        # kept working only so a QueryRecord written before v2 shipped
        # still re-exports correctly), then the database-metric shape
        # every other analysis uses.
        extraction_summary = insight.get("extraction_summary")
        body = insight.get("body")
        if extraction_summary:
            conf = extraction_summary.get("extraction_confidence", "")
            _add_bullets_slide(prs, "Executive summary", [
                insight.get("what", ""),
                f"{extraction_summary.get('total_rows_or_items', 0)} row(s)/item(s) across "
                f"{extraction_summary.get('sheets_or_pages_or_slides', 0)} sheet(s)/page(s)/slide(s) "
                f"— extraction confidence: {conf}",
            ])
            findings = [
                f"{kf.get('finding', '')} [{kf.get('location', '')} — {kf.get('confidence', '')} confidence]"
                for kf in insight.get("key_findings", [])
            ]
            if findings:
                _add_bullets_slide(prs, "Key findings", findings)
            flagged = insight.get("flagged_items") or []
            if flagged:
                _add_bullets_slide(prs, "Flagged items", flagged)
            _add_bullets_slide(prs, "Confidence", [
                f"Confidence: {insight.get('confidence', '')} — {insight.get('confidence_explanation', '')}",
                f"Next question: {insight.get('next_question', '')}",
            ])
        elif body:
            _add_bullets_slide(prs, "Executive summary", [insight.get("what", "")])
            _add_text_slide(prs, "Analysis", body)
            _add_bullets_slide(prs, "Confidence", [
                f"Confidence: {insight.get('confidence', '')} — {insight.get('confidence_explanation', '')}",
                f"Next question: {insight.get('next_question', '')}",
            ])
        else:
            _add_bullets_slide(prs, "Executive summary", [
                insight.get("what", ""),
                f"Where: {insight.get('where', '')}",
                f"When: {insight.get('when', '')}",
            ])
            _add_bullets_slide(prs, "Key findings", [
                insight.get("contributors", ""),
                f"Confidence: {insight.get('confidence', '')} — {insight.get('confidence_explanation', '')}",
                f"Next question: {insight.get('next_question', '')}",
            ])

    if charts:
        # v2 document-only charts (see insight_agent.py's render_chart
        # tool) - one table slide per named chart, rather than the single
        # implicit bar+pie pair `by_group` produces.
        for chart in charts:
            heading = "Breakdown"
            if chart.get("title"):
                heading += f' — {chart["title"]}'
            rows = list(zip(chart.get("labels", []), chart.get("values", [])))
            _add_table_slide(prs, heading, ["Group", "Total"], [[label, f"{value:,.2f}"] for label, value in rows])
    elif by_group:
        _add_table_slide(
            prs, "Breakdown", ["Group", "Total"],
            [[row["group"], f"{row['total']:,.2f}"] for row in by_group],
        )

    if anomalies:
        _add_bullets_slide(prs, "Risks & anomalies", [
            f"{a['what']} — {a['magnitude']} [{a['confidence']} confidence]" for a in anomalies[:5]
        ])

    prs.save(path)
    return path
