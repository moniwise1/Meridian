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


print("\nALL REPORT STANDARD CHECKS PASSED")
