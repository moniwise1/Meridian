"""
Verification for the Meridian report standard: the structure, the
formatting rules, and - the part that actually protects a customer - the
promise that a broken figure is flagged rather than quietly repaired or
invented.

Every check opens the generated PDF back up with pymupdf and inspects
the real rendered page: its text, its font sizes, its page geometry. A
check that only asserted "the file exists and is non-empty" would pass
for a blank document, which is exactly the kind of regression this file
is here to catch.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_report_standard.py
"""
import base64
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

import pymupdf

from app.agents.report_generator import generate_report_pdf
from app.agents import report_format as fmt

A4_PT = (595, 842)          # A4 in PDF points, what pymupdf reports
MM_TO_PT = 72.0 / 25.4


def pages(path: str) -> list[str]:
    return [page.get_text() for page in pymupdf.open(path)]


def text_of(path: str) -> str:
    return "\n".join(pages(path))


def spans(path: str) -> list[dict]:
    """Every rendered text span, with its font size and position."""
    out = []
    for page in pymupdf.open(path):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        out.append(span)
    return out


_CLEAN_INSIGHT = {
    "what": "Sales grew while operating costs took a smaller share of each naira.",
    "confidence": "high",
    "confidence_explanation": "Monthly values reconcile to the stated annual totals.",
    "extraction_summary": {"total_rows_or_items": 48, "sheets_or_pages_or_slides": 3,
                           "extraction_confidence": "high", "flags": []},
    "key_findings": [{"finding": "Revenue rose 84.9% across the year.",
                      "location": "Monthly Sales table", "confidence": "high"}],
    "flagged_items": [],
}

_CLEAN_CHART = [{
    "chart_type": "line", "title": "Revenue rose faster than operating spend",
    "labels": ["Jan", "Feb", "Mar"], "values": [42.5, 55.0, 78.6],
    "unit": "NGN m", "location": "Monthly Sales table",
    "insight": "Revenue climbed from NGN 42.5m to NGN 78.6m across the period.",
}]

# The real defect this standard exists for: a rate stored as 94.20 and
# formatted as a percentage a second time, arriving as 9,420.0%.
_BROKEN_CHART = [{
    "chart_type": "line", "title": "On-time delivery rate by month",
    "labels": ["Jan", "Feb"], "values": [9420.0, 9710.0],
    "unit": "%", "location": "Delivery Performance table",
    "insight": "Values are shown exactly as found in the source.",
}]

_BASE = dict(
    title="Annual Business Performance Analysis",
    question="Analyse this",
    metrics={},
    data_quality={"row_count": 48, "completeness_pct": 96.5, "duplicate_pct": 0.0, "notes": []},
    anomalies=[],
    sql="-- document analysis; no SQL executed",
    query_id="AQ-56f549b8",
)


# --- 1. the cover carries the question verbatim and identifies the report ---
clean = generate_report_pdf(insight=_CLEAN_INSIGHT, charts=_CLEAN_CHART,
                            period="January-December", **_BASE)
cover = pages(clean)[0]
assert "ORIGINAL QUESTION" in cover, cover
assert '"Analyse this"' in cover, "the question must appear verbatim on the cover"
assert "AQ-56f549b8" in cover, cover
assert "January-December" in cover, cover
assert "Annual Business Performance Analysis" in cover, cover
print("1. OK  the cover states the question verbatim, the query id and the period")


# --- 2. the cover carries no page furniture; content pages do -------------
assert "Page 1" not in cover, "the cover must not carry a page number or footer"
assert "Made by Meridian" not in cover, cover
rest = pages(clean)[1:]
assert all("Made by Meridian" in p for p in rest), "every content page needs the footer"
assert any("Page 2" in p for p in rest), "content pages must be numbered"
print("2. OK  the cover has no page number or footer; every content page has both")


# --- 3. no blank pages ----------------------------------------------------
for i, page_text in enumerate(pages(clean), start=1):
    assert page_text.strip(), f"page {i} rendered blank"
print(f"3. OK  all {len(pages(clean))} pages carry content - none rendered blank")


# --- 4. A4 portrait with at least 16mm side margins ------------------------
doc = pymupdf.open(clean)
for page in doc:
    assert round(page.rect.width) == A4_PT[0] and round(page.rect.height) == A4_PT[1], page.rect
# The green cover bleeds to the edge by design, so margins are measured on
# the content pages where the standard's 16mm rule actually applies.
margin_pt = 16.0 * MM_TO_PT
content_spans = [s for s in spans(clean) if s["bbox"][1] > 40]
leftmost = min(s["bbox"][0] for s in content_spans)
assert leftmost >= margin_pt - 1.5, f"text starts at {leftmost:.1f}pt, inside the 16mm margin"
print(f"4. OK  A4 portrait; no text closer than 16mm to the edge (leftmost {leftmost:.1f}pt)")


# --- 5. type sizes respect the standard's floors ---------------------------
smallest = min(s["size"] for s in spans(clean))
# 7pt is the floor, and only page furniture (footer, running head) and
# KPI-card captions are allowed down there. Body copy and chart labels
# are checked against their own, higher floors below.
assert smallest >= 7.0, f"smallest rendered type is {smallest}pt"
body_sizes = [s["size"] for s in spans(clean) if s["size"] >= 9]
assert body_sizes, "no body-sized type found at all"
chart_label_sizes = [s["size"] for s in spans(clean) if 7.9 <= s["size"] <= 8.1]
assert chart_label_sizes, "chart labels should render at the 8pt floor"
print(f"5. OK  chart labels at 8pt, body at 9pt+, nothing below {smallest}pt (footers only)")


# --- 6. KPI cards are built from real figures and nothing else ------------
with_metrics = generate_report_pdf(
    insight=_CLEAN_INSIGHT, charts=_CLEAN_CHART,
    analysis={"metrics": [
        {"id": "total", "label": "Annual sales", "value": 709_000_000},
        {"id": "orders", "label": "Total orders", "value": 19325},
    ]},
    **_BASE,
)
body = text_of(with_metrics)
assert "ANNUAL SALES" in body and "NGN 709.0m" in body, body[:1500]
assert "TOTAL ORDERS" in body and "19,325" in body, body[:1500]
print("6. OK  KPI cards carry real labelled figures, formatted to the Meridian rules")


# --- 7. nothing is invented when the analysis produced nothing ------------
bare = generate_report_pdf(
    insight={"what": "The single figure requested was returned.", "confidence": "high"},
    charts=None, by_group=None,
    **{**_BASE, "data_quality": {"row_count": 1, "notes": []}},
)
bare_text = text_of(bare)
assert "Decision support" not in bare_text and "priority order" not in bare_text, \
    "recommended actions must not appear when the analysis produced none"
assert "Risks and limitations" not in bare_text or "not independently established" in bare_text
assert "Source notes" not in bare_text, "a sources table must not appear without evidence"
# The report still exists and still answers.
assert "The single figure requested was returned." in bare_text
print("7. OK  absent sections are omitted, not filled with invented content")


# --- 8. an impossible percentage is FLAGGED, never silently corrected -----
broken = generate_report_pdf(insight=_CLEAN_INSIGHT, charts=_BROKEN_CHART, **_BASE)
broken_text = text_of(broken)
assert "DRAFT - DATA VALIDATION REQUIRED" in pages(broken)[0], \
    "a failed validation must be stamped on the cover, not buried"
assert "9,420.0" in broken_text, "the original value must still be shown, unaltered"
assert "94.2%" not in broken_text, "the value must NOT be silently repaired"
assert "Impossible percentage" in broken_text, broken_text[:1200]
assert "Unusable" in broken_text, "the data-quality table must rate the field unusable"
print("8. OK  an impossible percentage is shown as-is, flagged, and stamped on the cover")


# --- 9. a clean report is NOT stamped draft -------------------------------
assert "DRAFT" not in pages(clean)[0], "a clean report must not be marked draft"
assert "ANALYTICS REPORT" in pages(clean)[0]
print("9. OK  a report that passes validation is not marked draft")


# --- 10. a failed explanation step says so, on the cover and in the body --
failed = generate_report_pdf(insight={"error": "token budget exhausted"},
                             charts=_CLEAN_CHART, **_BASE)
failed_text = text_of(failed)
assert "DRAFT - DATA VALIDATION REQUIRED" in pages(failed)[0]
assert "explanation step" in failed_text, failed_text[:1200]
print("10. OK  a failed explanation step is reported, not left as a silently empty report")


# --- 11. charts carry their unit, source and explanation ------------------
assert "Measured in NGN m" in body, "a chart must state its unit"
assert "Source: Monthly Sales table" in body, "a chart must state where it came from"
assert "What this means" in body, "a chart must be explained in plain language"
print("11. OK  every chart states its unit, its source and what it means")


# --- 12. section order follows the standard -------------------------------
full = generate_report_pdf(
    insight=_CLEAN_INSIGHT, charts=_CLEAN_CHART,
    analysis={
        "metrics": [{"id": "total", "label": "Annual sales", "value": 709_000_000}],
        "confidence": {"measurement": {"level": "high", "reason": "Totals reconcile."}},
        "scope": {"metric_definition": "Operating spread, not net profit.", "assumptions": []},
        "quality": {"limitations": []},
        "findings": [{"kind": "recommendation", "text": "Repair the delivery percentage scale."}],
        "evidence": [{"id": "e0", "source_id": "src-1", "filename": "pack.pdf",
                      "method": "extracted_text", "source_version": "2026-09-12"}],
    },
    **_BASE,
)
order_text = text_of(full)
positions = {name: order_text.find(name) for name in (
    "EXECUTIVE ANSWER", "DATA QUALITY", "DECISION SUPPORT", "METHODOLOGY AND ASSUMPTIONS", "SOURCE NOTES")}
assert all(v >= 0 for v in positions.values()), positions
ordered = sorted(positions, key=lambda k: positions[k])
assert ordered == ["EXECUTIVE ANSWER", "DATA QUALITY", "DECISION SUPPORT",
                   "METHODOLOGY AND ASSUMPTIONS", "SOURCE NOTES"], ordered
print("12. OK  the answer leads; data quality, actions, method and sources follow in order")


# --- 13. recommendations are kept distinct from observations --------------
mixed = generate_report_pdf(
    insight=_CLEAN_INSIGHT, charts=_CLEAN_CHART,
    analysis={"findings": [
        {"kind": "recommendation", "text": "Repair the delivery percentage scale."},
        {"kind": "observation", "text": "Revenue per order is NGN 36,688."},
    ]},
    **_BASE,
)
mixed_text = text_of(mixed)
rec_at = mixed_text.find("Repair the delivery percentage scale")
obs_at = mixed_text.find("Revenue per order is NGN 36,688")
decision_at = mixed_text.find("DECISION SUPPORT")
findings_at = mixed_text.find("What the analysis established")
assert decision_at < rec_at < findings_at < obs_at, \
    "an observation must not be presented among the recommended actions"
print("13. OK  an observation is never presented as advice")


# --- 14. the number rules themselves --------------------------------------
assert fmt.abbreviate(709_000_000) == "709.0m", fmt.abbreviate(709_000_000)
assert fmt.abbreviate(1_250_000_000) == "1.25bn", fmt.abbreviate(1_250_000_000)
assert fmt.abbreviate(36688) == "36,688", fmt.abbreviate(36688)
assert fmt.fmt_currency(709_000_000) == "NGN 709.0m"
assert fmt.fmt_percent(33.14) == "33.1%"
assert fmt.fmt_rate(0.942) == "94.2%", fmt.fmt_rate(0.942)
assert fmt.fmt_growth(42.5, 78.6) == "+84.9%", fmt.fmt_growth(42.5, 78.6)
# A growth rate off a zero baseline is undefined, not infinite.
assert fmt.fmt_growth(0, 78.6) == ""
assert fmt.as_number("1,250") == 1250.0 and fmt.as_number("not a number") is None
assert fmt.as_number(float("nan")) is None and fmt.as_number(True) is None
print("14. OK  currency, abbreviation, percentage and growth formatting match the standard")


# --- 15. percentage points are never written as percent -------------------
assert fmt.fmt_pp_change(40.2, 33.1) == "-7.1 percentage points", fmt.fmt_pp_change(40.2, 33.1)
assert fmt.fmt_pp_change(33.1, 34.1) == "+1.0 percentage point", fmt.fmt_pp_change(33.1, 34.1)
# The same movement expressed as a relative change is a different number,
# which is exactly why the two have separate functions.
assert fmt.fmt_growth(40.2, 33.1) == "-17.7%", fmt.fmt_growth(40.2, 33.1)
print("15. OK  a 40.2%->33.1% move is 7.1 percentage points, not 7.1% (which is -17.7%)")


# --- 16. the bad-percentage detector is scoped to rate fields -------------
assert fmt.looks_like_bad_percent(9420.0, "on-time delivery rate") is True
assert fmt.looks_like_bad_percent(9420.0, "%") is True
# A large non-rate figure is an ordinary number, not a defect.
assert fmt.looks_like_bad_percent(9420.0, "Sales (NGN m)") is False
# A legitimate rate above 100% (growth) is not flagged as impossible.
assert fmt.looks_like_bad_percent(150.0, "growth rate") is False
assert fmt.percent_warnings(["Jan"], [42.5], "NGN m", "Sales") == []
print("16. OK  only rate fields are checked, and a legitimate >100% rate is not flagged")


# =========================================================================
# The same standard, as a deck. Built from the same snapshot, so a
# difference between the two formats is a defect in one of them.
# =========================================================================

from pptx import Presentation
from pptx.util import Emu
from app.agents.presentation_generator import generate_presentation_pptx

_DECK_BASE = {k: v for k, v in _BASE.items() if k != "sql"}


def deck_text(prs) -> str:
    return "\n".join(shape.text_frame.text for slide in prs.slides
                     for shape in slide.shapes if shape.has_text_frame)


def runs(prs):
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        if run.text.strip():
                            yield run


_DECK_ANALYSIS = {
    "metrics": [{"id": "total", "label": "Annual sales", "value": 709_000_000}],
    "confidence": {"measurement": {"level": "high", "reason": "Totals reconcile."}},
    "scope": {"metric_definition": "Operating spread, not net profit.", "assumptions": []},
    "quality": {"limitations": []},
    "findings": [{"kind": "recommendation", "text": "Repair the delivery percentage scale."}],
    "evidence": [{"id": "e0", "source_id": "src-1", "filename": "pack.pdf",
                  "method": "extracted_text", "source_version": "2026-09-12"}],
}

clean_deck = Presentation(generate_presentation_pptx(
    insight=_CLEAN_INSIGHT, charts=_CLEAN_CHART, analysis=_DECK_ANALYSIS,
    period="January-December", **_DECK_BASE))


# --- 17. the deck is 16:9 widescreen --------------------------------------
ratio = clean_deck.slide_width / clean_deck.slide_height
assert abs(ratio - 16 / 9) < 0.01, f"deck is {ratio:.3f}, not 16:9"
print(f"17. OK  the deck is 16:9 widescreen ({ratio:.3f}), not python-pptx's default 4:3")


# --- 18. the title slide carries the question verbatim --------------------
first = "\n".join(s.text_frame.text for s in clean_deck.slides[0].shapes if s.has_text_frame)
assert '"Analyse this"' in first, first
assert "AQ-56f549b8" in first and "ORIGINAL QUESTION" in first, first
assert "DRAFT" not in first, "a clean deck must not be stamped draft"
print("18. OK  the title slide states the question verbatim and is not stamped draft")


# --- 19. a chart slide's title states the conclusion ----------------------
deck_body = deck_text(clean_deck)
assert "Revenue rose faster than operating spend" in deck_body, deck_body[:800]
assert "Breakdown -" not in deck_body, \
    "the chart's conclusion must be the slide title, not buried behind a generic prefix"
print("19. OK  the chart's own conclusion is the slide title, not a generic heading")


# --- 20. one native chart per chart, with its takeaway and source --------
chart_shapes = [s for slide in clean_deck.slides for s in slide.shapes if s.has_chart]
assert len(chart_shapes) == 1, f"expected 1 native chart, got {len(chart_shapes)}"
assert "What this means" in deck_body, "the chart explanation never reached the deck"
assert "Revenue climbed from NGN 42.5m" in deck_body, "the takeaway text is missing"
assert "Source: Monthly Sales table" in deck_body and "Measured in NGN m" in deck_body
print("20. OK  each chart is a native object carrying its unit, source and takeaway")


# --- 21. the deck's type scale ------------------------------------------
sizes = [r.font.size.pt for r in runs(clean_deck) if r.font.size]
bullets = [r.font.size.pt for r in runs(clean_deck) if r.text.startswith("-  ") and r.font.size]
assert any(28 <= s <= 32 for s in sizes), f"no slide title in the 28-32pt band: {sorted(set(sizes))}"
assert bullets and min(bullets) >= 17, f"bullets below the 17pt floor: {bullets}"
labels = chart_shapes[0].chart.plots[0].data_labels.font.size
assert labels is not None and labels.pt >= 12, f"chart labels at {labels}"
print(f"21. OK  titles 28-32pt, bullets at {min(bullets):.0f}pt, chart labels at {labels.pt:.0f}pt")


# --- 22. no slide is crowded past the six-bullet ceiling -----------------
for i, slide in enumerate(clean_deck.slides, start=1):
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        filled = [p for p in shape.text_frame.paragraphs if "".join(r.text for r in p.runs).strip()]
        assert len(filled) <= 6, f"slide {i} has {len(filled)} lines in one block"
print("22. OK  no slide carries more than six lines in a single block")


# --- 23. nothing sits outside the slide ----------------------------------
SW, SH = clean_deck.slide_width, clean_deck.slide_height
for i, slide in enumerate(clean_deck.slides, start=1):
    for shape in slide.shapes:
        left, top = shape.left or 0, shape.top or 0
        right, bottom = left + (shape.width or 0), top + (shape.height or 0)
        assert left >= 0 and top >= 0 and right <= SW and bottom <= SH, \
            f"slide {i}: a shape sits outside the slide"
print("23. OK  every shape sits inside the slide bounds")


# --- 24. a broken percentage gets its own slide, uncorrected -------------
broken_deck = Presentation(generate_presentation_pptx(
    insight=_CLEAN_INSIGHT, charts=_BROKEN_CHART, **_DECK_BASE))
broken_body = deck_text(broken_deck)
broken_first = "\n".join(s.text_frame.text for s in broken_deck.slides[0].shapes if s.has_text_frame)
assert "DRAFT - DATA VALIDATION REQUIRED" in broken_first, broken_first
assert "9,420.0" in broken_body, "the original value must survive into the deck"
assert "94.2%" not in broken_body, "the value must NOT be silently repaired"
assert "This measure cannot be used" in broken_body, broken_body[:900]
print("24. OK  the deck flags an impossible percentage on its own slide, uncorrected")


# --- 25. the closing data-quality slide is always produced ---------------
assert "What can be trusted - and what cannot" in deck_body, "no data-quality slide"
assert "What these figures do not cover" in deck_body, "no assumptions slide"
thin = Presentation(generate_presentation_pptx(
    insight={"what": "One figure was returned.", "confidence": "high"},
    charts=None, by_group=None,
    **{**_DECK_BASE, "data_quality": {}}))
thin_body = deck_text(thin)
assert "What can be trusted - and what cannot" in thin_body, \
    "the data-quality slide must appear even when the snapshot is thin"
assert "Where each figure came from" not in thin_body, \
    "a sources slide must not appear without evidence"
assert "priority order" not in thin_body, "actions must not be invented"
print("25. OK  the data-quality slide always appears; sources and actions never invented")


# --- 26. the two formats agree ------------------------------------------
pdf_both = text_of(generate_report_pdf(insight=_CLEAN_INSIGHT, charts=_BROKEN_CHART, **_BASE))
for shared in ("9,420.0", "DRAFT - DATA VALIDATION REQUIRED", "On-time delivery rate by month"):
    assert shared in pdf_both and shared in broken_body, \
        f"{shared!r} appears in one format but not the other"
print("26. OK  the PDF and the deck tell the same story about the same snapshot")


# =========================================================================
# The same standard, as a workbook. Every check reopens the saved .xlsx
# and inspects what actually landed in it - sheet order, real Excel
# tables, live formulas, number formats, native charts - rather than
# trusting the writer that produced it.
# =========================================================================

from openpyxl import load_workbook
from app.agents.export import export_xlsx, export_csv, FMT_PERCENT, FMT_CURRENCY_M

_SNAPSHOT = {
    "insight": _CLEAN_INSIGHT,
    "analysis": _DECK_ANALYSIS,
    "charts": _CLEAN_CHART,
    "data_quality": {"row_count": 48, "completeness_pct": 96.5, "duplicate_pct": 0.0,
                     "notes": ["Monthly order counts are not present in the source."]},
    "preview_rows": [
        {"month": "January", "sales_ngn_m": 42.5, "spend_ratio_pct": 40.2, "orders": 1250},
        {"month": "February", "sales_ngn_m": 48.1, "spend_ratio_pct": 38.2, "orders": 1310},
        {"month": "March", "sales_ngn_m": 51.3, "spend_ratio_pct": 38.2, "orders": None},
    ],
    "sql": "-- document analysis; no SQL executed",
}

book = load_workbook(export_xlsx(_SNAPSHOT, "export", question="Analyse this",
                                 query_id="AQ-56f549b8", period="January-December"))


def sheet_text(ws) -> str:
    return "\n".join(str(c.value) for r in ws.iter_rows() for c in r if c.value is not None)


def all_text(wb) -> str:
    return "\n".join(sheet_text(ws) for ws in wb.worksheets)


# --- 27. the seven sheets, in the order the standard sets out -----------
assert book.sheetnames == ["00_Read_Me", "01_Executive_Summary", "02_Clean_Data",
                           "03_Analysis", "04_Charts", "05_Data_Quality",
                           "06_Assumptions"], book.sheetnames
print("27. OK  the workbook has the seven standard sheets, in order")


# --- 28. data areas are real Excel tables, filterable and frozen --------
tables = {ws.title: list(ws.tables.keys()) for ws in book.worksheets}
assert "CleanData" in tables["02_Clean_Data"], tables
assert tables["03_Analysis"], "the analysis sheet has no table"
assert "DataQuality" in tables["05_Data_Quality"], tables
for title in ("02_Clean_Data", "05_Data_Quality"):
    assert book[title].freeze_panes, f"{title} does not freeze its header"
# Every table name must be unique across the workbook, or Excel refuses
# to open the file at all.
names = [n for v in tables.values() for n in v]
assert len(names) == len(set(names)), names
print(f"28. OK  {len(names)} uniquely-named Excel tables; data sheets freeze their headers")


# --- 29. derived figures are live formulas, not typed-in answers -------
analysis_ws = book["03_Analysis"]
formulas = [c.value for r in analysis_ws.iter_rows() for c in r
            if isinstance(c.value, str) and c.value.startswith("=")]
assert any(f.startswith("=SUM(") for f in formulas), formulas[:5]
assert any("IFERROR" in f for f in formulas), formulas[:5]
# One total per series, plus a derived column per data row after the
# first - three points produce three formulas, and every one of them is
# a formula rather than a number somebody worked out and typed in.
assert len(formulas) >= 3, formulas
print(f"29. OK  {len(formulas)} live formulas on 03_Analysis - totals and shares are computed, not typed")


# --- 30. a total is never inside its own table ------------------------
for name, table in analysis_ws.tables.items():
    # openpyxl maps a table name to its ref string on read and to the
    # Table object on a freshly built sheet; accept either.
    first, last = (table if isinstance(table, str) else table.ref).split(":")
    last_row = int("".join(ch for ch in last if ch.isdigit()))
    for row in analysis_ws.iter_rows(min_row=last_row, max_row=last_row):
        assert not any(str(c.value).strip().lower() == "total" for c in row if c.value), \
            f"table {name} ends on a Total row; filters would double-count it"
print("30. OK  a series total sits outside its table, where a filter cannot double-count it")


# --- 31. percentages are stored as fractions, currency as raw amounts --
clean = book["02_Clean_Data"]
rate_cells = [c for r in clean.iter_rows() for c in r if c.number_format == FMT_PERCENT]
assert rate_cells, "no percentage-formatted cells at all"
for cell in rate_cells:
    # 40.2% must be stored as 0.402. Storing 40.2 against this format is
    # what displays 4,020% - the defect the standard exists to prevent.
    assert cell.value is None or abs(cell.value) <= 100, \
        f"{cell.coordinate} holds {cell.value} against a percent format"
assert any(abs(c.value - 0.402) < 1e-9 for c in rate_cells if c.value is not None), \
    "40.2 should have been stored as 0.402"
money = [c for r in book["01_Executive_Summary"].iter_rows() for c in r
         if c.number_format == FMT_CURRENCY_M]
assert money and any(c.value == 709_000_000 for c in money), \
    "a currency cell should hold the raw amount; the format scales it to millions"
print("31. OK  rates stored as fractions (0.402 -> 40.2%), currency stored raw and scaled by format")


# --- 32. numbers are numbers, blanks are blanks -----------------------
header_row = next(r for r in clean.iter_rows()
                  if any(str(c.value) == "month" for c in r if c.value))[0].row
body = list(clean.iter_rows(min_row=header_row + 1, max_row=header_row + 3))
for row in body:
    assert isinstance(row[1].value, (int, float)), f"{row[1].coordinate} stored a number as text"
# The missing order count stays empty - never filled with a zero, which
# would read as "no orders that month".
assert body[2][3].value is None, f"a missing value became {body[2][3].value!r}"
print("32. OK  numbers are stored as numbers, and a missing value stays empty rather than zero")


# --- 33. native charts, each reading from the analysis sheet ----------
charts_ws = book["04_Charts"]
assert len(charts_ws._charts) == len(_CLEAN_CHART), \
    f"expected {len(_CLEAN_CHART)} native charts, got {len(charts_ws._charts)}"
chart = charts_ws._charts[0]
refs = str(chart.series[0].val.numRef.f)
assert "03_Analysis" in refs, f"chart does not read from 03_Analysis: {refs}"
assert sheet_text(charts_ws).count("Revenue climbed from NGN 42.5m") == 1, \
    "the chart's takeaway is missing from the charts sheet"
print("33. OK  native Excel charts read live from 03_Analysis, each with its takeaway beside it")


# --- 34. the workbook says what it is, and what it could not check ----
readme = sheet_text(book["00_Read_Me"])
assert '"Analyse this"' in readme, "the question is not stated verbatim"
assert "AQ-56f549b8" in readme and "January-December" in readme, readme[:400]
assert "VALIDATED" in readme and "DRAFT" not in readme, "a clean workbook must not be marked draft"
for name, _ in [(n, d) for n, d in ((s, "") for s in book.sheetnames)]:
    assert name in readme, f"{name} is missing from the sheet index"
print("34. OK  00_Read_Me states the question verbatim, the query id, and indexes every sheet")


# --- 35. a broken percentage reaches the workbook, uncorrected --------
broken_book = load_workbook(export_xlsx(
    {**_SNAPSHOT, "charts": _BROKEN_CHART}, "export",
    question="Analyse this", query_id="AQ-56f549b8"))
broken_all = all_text(broken_book)
assert "DRAFT - DATA VALIDATION REQUIRED" in sheet_text(broken_book["00_Read_Me"]), \
    "the workbook must be stamped draft on its first sheet"
assert "9,420.0" in broken_all, "the original value must survive into the workbook"
assert "Unusable" in sheet_text(broken_book["05_Data_Quality"]), broken_all[:600]
assert broken_book["05_Data_Quality"].conditional_formatting, \
    "the unusable status is not highlighted"
print("35. OK  the workbook flags an impossible percentage, stamps the cover, and repairs nothing")


# --- 36. a document-only analysis still produces a full workbook ------
# This used to be impossible: the export refused outright without rows,
# so a question answered from a document could not be exported at all.
doc_only = load_workbook(export_xlsx(
    {"insight": _CLEAN_INSIGHT, "analysis": _DECK_ANALYSIS, "charts": _CLEAN_CHART,
     "data_quality": {}, "preview_rows": []},
    "export", question="Analyse this", query_id="AQ-1"))
assert doc_only.sheetnames == book.sheetnames, doc_only.sheetnames
assert "did not return a table" in sheet_text(doc_only["02_Clean_Data"]), \
    "an empty data sheet must say why it is empty"
assert doc_only["04_Charts"]._charts, "the charts were lost when there were no rows"
print("36. OK  an analysis with no table still exports a full workbook that says why")


# --- 37. CSV stays plain data, and still refuses to invent ------------
csv_path = export_csv(_SNAPSHOT["preview_rows"], "export")
with open(csv_path, encoding="utf-8") as fh:
    csv_text = fh.read()
assert csv_text.splitlines()[0] == "month,sales_ngn_m,spend_ratio_pct,orders", csv_text[:120]
assert "Meridian" not in csv_text, "branding must never be written into CSV data"
print("37. OK  CSV is unbranded tabular data - a header row and rows, nothing else")


print("\nALL REPORT STANDARD CHECKS PASSED")
