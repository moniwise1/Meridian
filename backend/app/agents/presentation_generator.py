"""
Presentation Generator (BUILD SPEC section 24) - the Meridian report
standard, as a deck.

Built from the same already-computed result snapshot the PDF report uses,
under the same rule: every number on a slide corresponds to a real
analytical result, and a slide whose content does not exist is not
produced rather than padded out.

What the standard asks of a deck, and where it is honoured here:

- 16:9 widescreen. python-pptx's default template is 4:3, and simply
  resizing it leaves every built-in placeholder positioned for the old
  aspect - so every slide here is built on the BLANK layout with its
  shapes placed explicitly. Nothing inherits a mispositioned placeholder.
- One message per slide, and the title states the conclusion rather than
  the topic. A chart's own title ("Revenue rose faster than operating
  spend") becomes the slide title verbatim; it is not buried behind a
  generic "Breakdown -" prefix the way it used to be.
- One chart per slide with a takeaway beneath it. The chart's plain-
  language explanation was previously dropped from the deck entirely -
  it existed in the PDF and simply never reached PowerPoint.
- Native, editable chart objects, never a picture of a chart.
- A closing Data quality and assumptions slide.

Validation matches the PDF exactly: a percentage field carrying values
that cannot be percentages is shown with its real value, called out on
its own slide, and stamped DRAFT - DATA VALIDATION REQUIRED on the
title slide. It is never silently repaired.
"""
import os
import uuid

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION

from app.config import settings
from app.agents.report_format import (
    as_number, fmt_number, fmt_percent, format_metric, percent_warnings,
)

# The Meridian visual system, shared with report_generator.py.
# RGBColor.from_string() takes a hex string with no leading '#'.
_DEEP_GREEN = RGBColor.from_string("123F3B")
_MINT = RGBColor.from_string("22B99A")
_GOLD = RGBColor.from_string("C58A34")
_NAVY = RGBColor.from_string("102633")
_SLATE = RGBColor.from_string("52616B")
_PALE_GREEN = RGBColor.from_string("E9F2F0")
_DIVIDER = RGBColor.from_string("D8E1DF")
_RED = RGBColor.from_string("B84B45")
_WHITE = RGBColor.from_string("FFFFFF")
_WARN_BG = RGBColor.from_string("FAEBEA")

_FONT = "Arial"  # the most broadly available stand-in for the web app's system-ui stack

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "meridian_mark.png")

# 16:9 widescreen, and the margins every slide is composed within.
_SLIDE_W = Inches(13.333)
_SLIDE_H = Inches(7.5)
_MARGIN = Inches(0.7)
_CONTENT_W = _SLIDE_W - _MARGIN * 2

# The standard's type scale: titles 28-32pt, body 17-20pt, chart labels
# no smaller than 12pt.
_TITLE_PT = Pt(30)
_BODY_PT = Pt(18)
_TAKEAWAY_PT = Pt(17)
_CHART_LABEL_PT = Pt(12)
_CAPTION_PT = Pt(12)

# Above this many characters a takeaway is stepped down a size rather
# than being allowed to overflow its panel. Content is never truncated -
# an explanation that gets cut in half is worse than one set smaller.
_TAKEAWAY_LONG = 380

_MAX_BULLETS = 6          # the standard's ceiling for one slide


def _style(run, color=_NAVY, size=_BODY_PT, bold=False) -> None:
    run.font.name = _FONT
    run.font.color.rgb = color
    run.font.size = size
    run.font.bold = bold


def _textbox(slide, left, top, width, height, *, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    return tf


def _write(tf, lines, *, color=_NAVY, size=_BODY_PT, bold=False, bullet_char="") -> None:
    """Writes one paragraph per line. `bullet_char` prefixes each line;
    python-pptx has no first-class bullet API on a plain textbox, and a
    literal prefix keeps the deck's bullets identical to the report's."""
    items = [str(line).strip() for line in lines if str(line).strip()]
    # Space BETWEEN paragraphs only. Applying it to a single-line label
    # silently added 8pt to every box's real height, which is what made
    # the takeaway panels overflow while looking correctly sized.
    for i, text in enumerate(items):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if len(items) > 1 and i < len(items) - 1:
            para.space_after = Pt(8)
        run = para.add_run()
        run.text = f"{bullet_char}{text}" if bullet_char else text
        _style(run, color=color, size=size, bold=bold)


def _rect(slide, left, top, width, height, color, *, shape=MSO_SHAPE.RECTANGLE):
    box = slide.shapes.add_shape(shape, left, top, width, height)
    box.fill.solid()
    box.fill.fore_color.rgb = color
    box.line.fill.background()
    box.shadow.inherit = False
    return box


def _blank(prs):
    # Layout 6 is Blank in python-pptx's default template. Every other
    # layout carries placeholders positioned for the 4:3 template this
    # deck is no longer using.
    return prs.slides.add_slide(prs.slide_layouts[6])


def _footer(slide, number: int) -> None:
    tf = _textbox(slide, _MARGIN, Inches(6.98), _CONTENT_W, Inches(0.3))
    para = tf.paragraphs[0]
    run = para.add_run()
    run.text = "Made by Meridian - getmeridiananalytics.com"
    _style(run, color=_SLATE, size=Pt(10))
    right = _textbox(slide, _MARGIN, Inches(6.98), _CONTENT_W, Inches(0.3))
    p2 = right.paragraphs[0]
    p2.alignment = PP_ALIGN.RIGHT
    r2 = p2.add_run()
    r2.text = str(number)
    _style(r2, color=_SLATE, size=Pt(10))


def _content_slide(prs, title: str, kicker: str = ""):
    """A titled slide with the mint-and-gold rule beneath the title.
    Returns (slide, top) where `top` is the y the content starts at."""
    slide = _blank(prs)
    if kicker:
        tf = _textbox(slide, _MARGIN, Inches(0.38), _CONTENT_W, Inches(0.3))
        _write(tf, [kicker.upper()], color=_MINT, size=Pt(11), bold=True)
    tf = _textbox(slide, _MARGIN, Inches(0.66), _CONTENT_W, Inches(0.85))
    _write(tf, [title], color=_DEEP_GREEN, size=_TITLE_PT, bold=True)
    rule_y = Inches(1.5)
    _rect(slide, _MARGIN, rule_y, Inches(2.6), Pt(3), _MINT)
    _rect(slide, _MARGIN + Inches(2.6), rule_y, Inches(0.7), Pt(3), _GOLD)
    _rect(slide, _MARGIN + Inches(3.3), rule_y, _CONTENT_W - Inches(3.3), Pt(3), _DIVIDER)
    _footer(slide, len(prs.slides))
    return slide, Inches(1.8)


def _title_slide(prs, title: str, question: str, query_id: str,
                 period: str | None, draft: bool) -> None:
    slide = _blank(prs)
    _rect(slide, 0, 0, _SLIDE_W, _SLIDE_H, _DEEP_GREEN)

    if os.path.exists(_LOGO_PATH):
        slide.shapes.add_picture(_LOGO_PATH, _MARGIN, Inches(0.55), height=Inches(0.6))
        mark_w = Inches(0.78)
    else:
        _rect(slide, _MARGIN, Inches(0.55), Inches(0.55), Inches(0.55), _MINT)
        tf = _textbox(slide, _MARGIN, Inches(0.62), Inches(0.55), Inches(0.45))
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        _write(tf, ["M"], color=_WHITE, size=Pt(22), bold=True)
        mark_w = Inches(0.78)
    tf = _textbox(slide, _MARGIN + mark_w, Inches(0.66), Inches(5), Inches(0.4))
    _write(tf, ["M E R I D I A N"], color=_WHITE, size=Pt(15), bold=True)

    tf = _textbox(slide, _MARGIN, Inches(2.45), _CONTENT_W, Inches(1.5))
    _write(tf, [title], color=_WHITE, size=Pt(40), bold=True)

    if draft:
        _rect(slide, _MARGIN, Inches(4.15), Inches(4.4), Inches(0.42), _RED)
        tf = _textbox(slide, _MARGIN + Inches(0.15), Inches(4.23), Inches(4.2), Inches(0.3))
        _write(tf, ["DRAFT - DATA VALIDATION REQUIRED"], color=_WHITE, size=Pt(13), bold=True)

    _rect(slide, _MARGIN, Inches(5.15), Inches(1.4), Pt(3), _MINT)
    tf = _textbox(slide, _MARGIN, Inches(5.35), _CONTENT_W, Inches(0.3))
    _write(tf, ["ORIGINAL QUESTION"], color=_MINT, size=Pt(11), bold=True)
    # Verbatim, per the standard - never paraphrased or tidied up.
    tf = _textbox(slide, _MARGIN, Inches(5.68), _CONTENT_W, Inches(0.6))
    _write(tf, [f'"{question}"'], color=_WHITE, size=Pt(20))

    reference = f"Query ID  {query_id}"
    if period:
        reference += f"  |  Source period  {period}"
    tf = _textbox(slide, _MARGIN, Inches(6.35), _CONTENT_W, Inches(0.35))
    _write(tf, [reference], color=_PALE_GREEN, size=Pt(13))

    tf = _textbox(slide, _MARGIN, Inches(6.92), _CONTENT_W, Inches(0.3))
    _write(tf, ["getmeridiananalytics.com"], color=_MINT, size=Pt(11))


def _kpi_row(slide, top, cards: list[tuple[str, str, str]]) -> None:
    """Up to four figures across the executive slide, as shapes rather
    than a chart - the deck's one native chart per chart-slide is what
    the regression test counts, and a KPI row is not a chart."""
    if not cards:
        return
    cards = cards[:4]
    gap = Inches(0.25)
    card_w = int((_CONTENT_W - gap * (len(cards) - 1)) / len(cards))
    card_h = Inches(1.45)
    for i, (label, value, note) in enumerate(cards):
        left = _MARGIN + i * (card_w + gap)
        _rect(slide, left, top, card_w, card_h, _PALE_GREEN)
        _rect(slide, left, top, card_w, Pt(4), _MINT)
        tf = _textbox(slide, left + Inches(0.18), top + Inches(0.2),
                      card_w - Inches(0.36), Inches(0.4))
        _write(tf, [label.upper()], color=_SLATE, size=Pt(11), bold=True)
        tf = _textbox(slide, left + Inches(0.18), top + Inches(0.62),
                      card_w - Inches(0.36), Inches(0.5))
        _write(tf, [value], color=_DEEP_GREEN, size=Pt(22), bold=True)
        if note:
            tf = _textbox(slide, left + Inches(0.18), top + Inches(1.12),
                          card_w - Inches(0.36), Inches(0.3))
            _write(tf, [note], color=_SLATE, size=Pt(10))


# Arial's average advance is about 0.52em for mixed-case prose. python-pptx
# cannot measure text, so a panel is sized from an estimate rather than
# being given a fixed height that a longer explanation then spills out of -
# which is exactly what the first version of this file did.
_AVG_CHAR_EM = 0.52
_LINE_SPACING = 1.25
_PANEL_LABEL_H = Inches(0.46)     # label plus the gap beneath it
_PANEL_PAD_H = Inches(0.18)       # breathing room at the foot of the panel


def _panel_metrics(text: str) -> tuple[Pt, int, Inches]:
    """Returns the type size, the line count and the panel height a piece
    of takeaway text actually needs."""
    size = _TAKEAWAY_PT if len(text) <= _TAKEAWAY_LONG else Pt(13)
    body_w_pt = (_CONTENT_W - Inches(0.5)) / 12700
    per_line = max(1, int(body_w_pt / (_AVG_CHAR_EM * size.pt)))
    lines = max(1, -(-len(text) // per_line))
    body_h = Inches(lines * size.pt * _LINE_SPACING / 72)
    return size, lines, _PANEL_LABEL_H + body_h + _PANEL_PAD_H


def _panel(slide, top, text: str, *, warn: bool = False,
           label: str = "What this means", height=None):
    """The takeaway beneath a visual, or a warning about it. Sized to its
    own content unless a caller pins the height."""
    size, _, needed = _panel_metrics(text)
    height = height or needed
    _rect(slide, _MARGIN, top, _CONTENT_W, height, _WARN_BG if warn else _PALE_GREEN)
    _rect(slide, _MARGIN, top, Pt(4), height, _RED if warn else _MINT)
    tf = _textbox(slide, _MARGIN + Inches(0.25), top + Inches(0.13),
                  _CONTENT_W - Inches(0.5), Inches(0.3))
    _write(tf, [label], color=_RED if warn else _DEEP_GREEN, size=Pt(12), bold=True)
    tf = _textbox(slide, _MARGIN + Inches(0.25), top + _PANEL_LABEL_H,
                  _CONTENT_W - Inches(0.5), height - _PANEL_LABEL_H - _PANEL_PAD_H)
    _write(tf, [text], color=_NAVY, size=size)
    return height


def _chart_slide(prs, chart: dict, period: str | None) -> None:
    labels = [str(l) for l in (chart.get("labels") or [])]
    values = [as_number(v) or 0.0 for v in (chart.get("values") or [])]
    if not labels or not values:
        return
    # The chart's own title IS the conclusion; it becomes the slide title
    # unchanged rather than being prefixed with a generic heading.
    slide, top = _content_slide(prs, chart.get("title") or "Breakdown", kicker="Chart")

    meta = []
    if chart.get("unit"):
        meta.append(f"Measured in {chart['unit']}")
    if period:
        meta.append(period)
    if chart.get("location"):
        meta.append(f"Source: {chart['location']}")
    if meta:
        tf = _textbox(slide, _MARGIN, top - Inches(0.08), _CONTENT_W, Inches(0.34))
        _write(tf, ["   |   ".join(meta)], color=_SLATE, size=_CAPTION_PT)

    chart_data = CategoryChartData()
    chart_data.categories = labels
    chart_data.add_series("Value", values)

    kind = (chart.get("chart_type") or "bar").lower()
    xl_type = XL_CHART_TYPE.LINE_MARKERS if kind == "line" else (
        XL_CHART_TYPE.PIE if kind == "pie" else XL_CHART_TYPE.COLUMN_CLUSTERED
    )
    warnings = percent_warnings(labels, values, chart.get("unit"), chart.get("title"))
    takeaway = str(chart.get("insight") or "").strip()
    # The chart takes whatever height is left once its takeaway has the
    # room it needs. A warning does NOT share this slide - it gets its
    # own, both because two stacked panels leave no usable chart and
    # because "this measure cannot be used" is its own message.
    chart_top = top + Inches(0.3)
    floor = Inches(6.9)
    panel_h = _panel_metrics(takeaway)[2] if takeaway else Inches(0)
    gap = Inches(0.18) if takeaway else Inches(0)
    chart_h = floor - chart_top - gap - panel_h
    chart_h = max(Inches(2.2), min(chart_h, Inches(4.55)))

    frame = slide.shapes.add_chart(xl_type, _MARGIN, chart_top,
                                   _CONTENT_W, chart_h, chart_data)
    native = frame.chart
    native.font.name = _FONT
    native.font.size = _CHART_LABEL_PT
    native.font.color.rgb = _SLATE

    plot = native.plots[0]
    plot.has_data_labels = True
    plot.data_labels.number_format = "#,##0.0"
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.font.size = _CHART_LABEL_PT
    plot.data_labels.font.name = _FONT
    plot.data_labels.font.color.rgb = _SLATE

    if kind == "pie":
        # One series, but each slice needs its own fill - a series-level
        # colour would tint every slice identically.
        native.has_legend = True
        native.legend.position = XL_LEGEND_POSITION.RIGHT
        native.legend.include_in_layout = False
        native.legend.font.size = _CHART_LABEL_PT
        palette = [_DEEP_GREEN, _MINT, _GOLD, _SLATE, _NAVY, _RED]
        for i, point in enumerate(plot.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = palette[i % len(palette)]
    else:
        native.has_legend = False
        series = plot.series[0]
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = _DEEP_GREEN
        if kind == "line":
            series.format.line.color.rgb = _DEEP_GREEN
            series.smooth = False
        native.category_axis.tick_labels.font.size = _CHART_LABEL_PT
        native.category_axis.tick_labels.font.name = _FONT
        native.value_axis.tick_labels.font.size = _CHART_LABEL_PT
        native.value_axis.tick_labels.font.name = _FONT
        native.value_axis.has_major_gridlines = True

    if takeaway:
        _panel(slide, chart_top + chart_h + Inches(0.18), takeaway)

    # The defect gets a slide of its own, immediately after the chart it
    # belongs to, so the reader meets it while the chart is still in mind.
    for warning in warnings[:1]:
        warn_slide, warn_top = _content_slide(
            prs, "This measure cannot be used", kicker="Data quality")
        _panel(warn_slide, warn_top + Inches(0.2), warning, warn=True,
               label=f"{chart.get('title') or 'This chart'}")


def _bullet_slides(prs, kicker: str, title: str, bullets: list[str]) -> None:
    """Splits past the standard's six-bullet ceiling onto further slides
    rather than crowding one."""
    items = [str(b).strip() for b in bullets if b and str(b).strip()]
    if not items:
        return
    for offset in range(0, len(items), _MAX_BULLETS):
        chunk = items[offset:offset + _MAX_BULLETS]
        heading = title if offset == 0 else f"{title} (continued)"
        slide, top = _content_slide(prs, heading, kicker=kicker)
        tf = _textbox(slide, _MARGIN, top, _CONTENT_W, Inches(4.9))
        _write(tf, chunk, bullet_char="-  ")


def generate_presentation_pptx(title: str, question: str, insight: dict, metrics: dict = None,
                               by_group: list[dict] | None = None, data_quality: dict = None,
                               anomalies: list[dict] = None, query_id: str = "",
                               charts: list[dict] | None = None, analysis: dict | None = None,
                               period: str | None = None, currency: str = "NGN") -> str:
    metrics = metrics or {}
    data_quality = data_quality or {}
    anomalies = anomalies or []
    analysis = analysis or {}
    charts = charts or []

    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, f"presentation-{uuid.uuid4().hex}.pptx")

    # Validation first: its outcome decides what the title slide says.
    warnings: list[str] = []
    for chart in charts:
        warnings.extend(percent_warnings(
            chart.get("labels") or [], chart.get("values") or [],
            chart.get("unit"), chart.get("title"),
        ))
    insight_failed = "error" in (insight or {})
    draft = bool(warnings) or insight_failed

    prs = Presentation()
    prs.slide_width = _SLIDE_W
    prs.slide_height = _SLIDE_H

    _title_slide(prs, title, question, query_id, period, draft)

    if insight_failed:
        slide, top = _content_slide(prs, "The explanation step did not complete",
                                    kicker="Executive answer")
        _panel(slide, top + Inches(0.2),
               "The analysis ran and the figures are real, but the step that writes the "
               "explanation failed, so this deck has no narrative summary. The data quality "
               "and assumptions slide still describes the underlying data accurately.",
               warn=True, label="Analysis unavailable")
    else:
        slide, top = _content_slide(prs, "What the numbers say", kicker="Executive answer")
        cards: list[tuple[str, str, str]] = []
        for metric in (analysis.get("metrics") or [])[:3]:
            formatted = format_metric(metric.get("label"), metric.get("value"), currency)
            if formatted:
                cards.append((str(metric.get("label") or "Metric"), formatted, ""))
        if len(cards) < 4:
            rows = as_number(data_quality.get("row_count"))
            if rows is not None:
                cards.append(("Rows analysed", fmt_number(rows), "In the verified result"))
        if len(cards) < 4:
            completeness = as_number(data_quality.get("completeness_pct"))
            if completeness is not None:
                cards.append(("Completeness", fmt_percent(completeness), "Of required fields"))
        if len(cards) < 4 and insight.get("confidence"):
            cards.append(("Confidence", str(insight["confidence"]).title(), "Stated by the analysis"))
        _kpi_row(slide, top, cards)

        if insight.get("what"):
            tf = _textbox(slide, _MARGIN, top + Inches(1.8), _CONTENT_W, Inches(1.5))
            _write(tf, [insight["what"]], size=_BODY_PT)

        if insight.get("confidence"):
            _panel(slide, Inches(5.05),
                   f"Confidence: {insight['confidence']}. "
                   f"{insight.get('confidence_explanation', '')}".strip(),
                   label="How much to trust this")

        # Three shapes of answer, checked in this order - see
        # report_generator.py's matching branch for the full explanation.
        extraction_summary = insight.get("extraction_summary")
        legacy_body = insight.get("body")
        if extraction_summary:
            _bullet_slides(prs, "The plain-language read", "What was found in the source", [
                f"{f.get('finding', '')} [{f.get('location', '')} - {f.get('confidence', '')} confidence]"
                if f.get("location") or f.get("confidence") else f.get("finding", "")
                for f in (insight.get("key_findings") or [])
            ])
            _bullet_slides(prs, "Flagged", "Items the analysis could not stand behind",
                           insight.get("flagged_items") or [])
            _bullet_slides(prs, "Extraction", "What was read out of the source", [
                f"{extraction_summary.get('total_rows_or_items', 0)} row(s)/item(s) across "
                f"{extraction_summary.get('sheets_or_pages_or_slides', 0)} sheet(s)/page(s)/slide(s)",
                f"Extraction confidence: {extraction_summary.get('extraction_confidence', 'not stated')}",
                *(extraction_summary.get("flags") or []),
            ])
        elif legacy_body:
            # Split on blank lines so the answer keeps its own structure
            # instead of running together as one unbroken block.
            _bullet_slides(prs, "Analysis", "The answer in full",
                           [p.strip() for p in legacy_body.split("\n\n") if p.strip()])
        else:
            _bullet_slides(prs, "Scope", "Where and when these figures apply", [
                f"Where: {insight['where']}" if insight.get("where") else "",
                f"When: {insight['when']}" if insight.get("when") else "",
                insight.get("contributors", ""),
            ])

    if charts:
        for chart in charts:
            _chart_slide(prs, chart, period)
    elif by_group:
        _chart_slide(prs, {
            "chart_type": "bar", "title": "Breakdown by group",
            "labels": [row.get("group") for row in by_group],
            "values": [row.get("total") for row in by_group],
        }, period)

    if anomalies:
        _bullet_slides(prs, "Notable findings", "What stands out in the data", [
            f"{a.get('what', '')} ({a.get('magnitude', '')}) [{a.get('confidence', '')} confidence]"
            for a in anomalies[:5]
        ])

    findings = analysis.get("findings") or []
    actions = [f.get("text", "") for f in findings
               if str(f.get("kind", "")).lower() in ("recommendation", "action", "next_step")]
    if not actions and insight.get("next_question"):
        actions = [f"Next question to ask: {insight['next_question']}"]
    if actions:
        _bullet_slides(prs, "Decision support", "What to do next, in priority order",
                       [f"{i:02d}   {text}" for i, text in enumerate(actions[:5], start=1)])

    observations = [f for f in findings
                    if str(f.get("kind", "")).lower() not in ("recommendation", "action", "next_step")]
    if observations:
        _bullet_slides(prs, "Findings", "What the analysis established",
                       [f"[{f.get('kind', '')}] {f.get('text', '')}" for f in observations])

    # The standard's closing slide. Always produced, even when the
    # snapshot is thin - "what we could not check" is itself the answer
    # a reader needs before acting on anything above.
    quality_lines: list[str] = []
    rows = as_number(data_quality.get("row_count"))
    if rows is not None:
        quality_lines.append(f"Rows analysed: {fmt_number(rows)}")
    completeness = as_number(data_quality.get("completeness_pct"))
    if completeness is not None:
        quality_lines.append(f"Field completeness: {fmt_percent(completeness)}")
    for name, confidence in (analysis.get("confidence") or {}).items():
        quality_lines.append(
            f"{str(name).title()} confidence: {str(confidence.get('level', '')).replace('_', ' ')} "
            f"- {confidence.get('reason', '')}"
        )
    if warnings:
        quality_lines.append("Percentage fields are unusable: values outside 0-100% are present "
                             "and have not been altered. See the chart slide.")
    quality_lines.extend(str(n) for n in (data_quality.get("notes") or []))

    scope = analysis.get("scope") or {}
    assumptions = [
        scope.get("metric_definition") or "The metric definition was not independently established.",
        *(scope.get("assumptions") or []),
        *((analysis.get("quality") or {}).get("limitations") or []),
    ]
    _bullet_slides(prs, "Data quality and assumptions", "What can be trusted - and what cannot",
                   quality_lines or ["No data-quality measures were recorded for this analysis."])
    _bullet_slides(prs, "Assumptions", "What these figures do not cover",
                   [str(a) for a in assumptions if a])

    sources = [
        f"{e.get('filename') or e.get('source_id', '')} - {str(e.get('method', '')).replace('_', ' ')}, "
        f"version {e.get('source_version') or 'unavailable'}"
        for e in (analysis.get("evidence") or [])
    ]
    _bullet_slides(prs, "Source notes", "Where each figure came from", sources)

    prs.save(path)
    return path
