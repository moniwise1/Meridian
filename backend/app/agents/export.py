"""
Export (BUILD SPEC section 22) - CSV, and the Meridian workbook standard.

Exports operate on the already-aggregated result (by_group / preview_rows
/ the analysis contract), never on a fresh unrestricted query: an export
cannot pull more than the original authorized analysis already retrieved
and passed its output check.

CSV is pure tabular data with no metadata capability at all - a
downstream script doing pd.read_csv() on it expects exactly the columns
it asked for, nothing else. Injecting a "Made by Meridian" row or comment
would silently corrupt that for anyone piping the export into another
tool, so CSV carries branding only in its filename, never in its data.

XLSX is the opposite case: a workbook is something a person opens, reads
and audits, so it carries the full Meridian structure - seven sheets, in
the order the standard sets out:

    00_Read_Me           what this is, and what each sheet holds
    01_Executive_Summary the answer, with its KPI figures
    02_Clean_Data        the rows the analysis returned
    03_Analysis          those rows worked, with live formulas
    04_Charts            native Excel charts, each with its takeaway
    05_Data_Quality      what can be trusted, rated per area
    06_Assumptions       scope, limitations, method and sources

Two things this file is careful about, because both produce a confidently
wrong workbook rather than an obviously broken one:

- **Percentages are stored as fractions.** Excel's "0.0%" format
  multiplies by 100 on display, so a cell holding 33.1 formatted that way
  reads 3,310.0%. Rates are divided by 100 on the way in and formatted
  "0.0%", which is what makes the stored value and the displayed value
  the same quantity. It is the same double-formatting mistake that turns
  94.2% into 9,420% - see report_format.py.

- **The millions currency format is only applied to raw amounts.** The
  standard's format string ends in ",," which divides by a million, so
  applying it to a figure already expressed in millions (a chart whose
  unit is "NGN m" carries 42.5, not 42,500,000) would display 0.0m.
  Series carry their unit in the column header and a plain number format
  instead.
"""
import os
import re
import uuid
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.chart.axis import ChartLines
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.config import settings
from app.agents.report_format import (
    as_number, is_rate_label, percent_warnings,
)

# The Meridian palette, as openpyxl wants it: 6 hex digits, no leading '#'.
_DEEP_GREEN = "123F3B"
_MINT = "22B99A"
_GOLD = "C58A34"
_NAVY = "102633"
_SLATE = "52616B"
_PALE_GREEN = "E9F2F0"
_NEUTRAL = "F5F7F7"
_RED = "B84B45"
_WARN_BG = "FAEBEA"
_WHITE = "FFFFFF"

_FONT = "Calibri"

# The standard's number formats.
FMT_CURRENCY_M = '[$₦-en-NG]#,##0.0,,"m";[Red]-[$₦-en-NG]#,##0.0,,"m"'
FMT_PERCENT = "0.0%"
FMT_INT = "#,##0"
FMT_DECIMAL = "#,##0.00"
FMT_DATE = "yyyy-mm-dd"

_SHEETS = [
    ("00_Read_Me", "What this workbook is, and what each sheet holds"),
    ("01_Executive_Summary", "The answer to the question, with its headline figures"),
    ("02_Clean_Data", "The rows the analysis returned, as a filterable table"),
    ("03_Analysis", "Those rows worked - every derived figure is a live formula"),
    ("04_Charts", "Native Excel charts, each with what it means"),
    ("05_Data_Quality", "What can be trusted, and what cannot"),
    ("06_Assumptions", "Scope, limitations, method and sources"),
]

_COUNT_WORDS = ("count", "rows", "orders", "items", "units", "number of", "quantity")


def export_csv(rows: list[dict], base_name: str) -> str:
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    # Full uuid4 hex, not a truncated slice: the download route authorizes
    # by signed token now, but an unguessable on-disk name is still worth
    # keeping as defence in depth (a path disclosure, a future static
    # mount added by mistake).
    path = os.path.join(settings.artifacts_dir, f"meridian-{base_name}-{uuid.uuid4().hex}.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# ------------------------------------------------------------------ styling

def _title(ws, row: int, text: str, *, col: int = 1) -> int:
    cell = ws.cell(row=row, column=col, value=text)
    cell.font = Font(name=_FONT, bold=True, size=14, color=_DEEP_GREEN)
    return row + 1


def _kicker(ws, row: int, text: str, *, col: int = 1) -> int:
    cell = ws.cell(row=row, column=col, value=text.upper())
    cell.font = Font(name=_FONT, bold=True, size=8, color=_MINT)
    return row + 1


def _note(ws, row: int, text: str, *, col: int = 1, width: int = 4, italic: bool = False) -> int:
    """A wrapped paragraph. Never merges cells - the standard forbids
    merged cells in data areas, and a merged block here would break the
    same copy/filter behaviour everywhere else in the workbook relies on."""
    cell = ws.cell(row=row, column=col, value=text)
    cell.font = Font(name=_FONT, size=10, color=_NAVY, italic=italic)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[row].height = max(15, 13 * (1 + len(text) // (22 * max(width, 1))))
    return row + 1


def _header_row(ws, row: int, headers: list[str], *, col: int = 1) -> int:
    for i, text in enumerate(headers):
        cell = ws.cell(row=row, column=col + i, value=text)
        cell.font = Font(name=_FONT, bold=True, color=_WHITE)
        cell.fill = PatternFill(fill_type="solid", fgColor=_DEEP_GREEN)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    return row + 1


def _autosize(ws, *, minimum: int = 10, maximum: int = 62) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            longest = max(len(part) for part in str(cell.value).split("\n"))
            widths[cell.column] = max(widths.get(cell.column, 0), longest)
    for column, width in widths.items():
        ws.column_dimensions[get_column_letter(column)].width = min(max(width + 2, minimum), maximum)


def _table_name(raw: str, used: set[str]) -> str:
    """Excel table names: letters/digits/underscore, must start with a
    letter, and unique within the workbook. A duplicate or an illegal
    character makes the file unopenable, so this is not cosmetic."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", raw) or "Table"
    if not name[0].isalpha():
        name = f"T_{name}"
    candidate, n = name[:28], 2
    while candidate in used:
        candidate = f"{name[:26]}_{n}"
        n += 1
    used.add(candidate)
    return candidate


def _add_table(ws, name: str, first_row: int, first_col: int, last_row: int, last_col: int) -> None:
    """A real Excel table: banded, filterable, and referenceable by name.
    Needs at least one data row - openpyxl writes a header-only table
    happily and Excel then refuses to open the file."""
    if last_row <= first_row:
        return
    ref = f"{get_column_letter(first_col)}{first_row}:{get_column_letter(last_col)}{last_row}"
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleLight8", showRowStripes=True, showColumnStripes=False,
        showFirstColumn=False, showLastColumn=False,
    )
    ws.add_table(table)


def _unique_headers(rows: list[dict]) -> list[str]:
    """Column names as they will be written. Blank and duplicate headers
    both make an Excel table invalid, so they are resolved here rather
    than producing a workbook that will not open."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, key in enumerate(rows[0].keys() if rows else []):
        name = str(key).strip() or f"Column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        out.append(name)
    return out


def _write_value(cell, value, *, rate: bool = False) -> None:
    """Writes a value as its real type, with the format its own kind
    calls for. Text stays text; a number never arrives as a string."""
    if value is None or value == "":
        cell.value = None
        return
    if isinstance(value, (datetime, date)):
        cell.value = value
        cell.number_format = FMT_DATE
        return
    number = as_number(value)
    if number is None:
        cell.value = str(value)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        return
    if rate:
        # Stored as a fraction so Excel's own percent format is correct.
        cell.value = number / 100.0
        cell.number_format = FMT_PERCENT
    else:
        cell.value = number
        cell.number_format = FMT_INT if float(number).is_integer() else FMT_DECIMAL


# ------------------------------------------------------------------- sheets

def _sheet_read_me(wb, question: str, query_id: str, period: str | None,
                   draft: bool, warnings: list[str]) -> None:
    ws = wb.create_sheet("00_Read_Me")
    row = _kicker(ws, 1, "Meridian analytics")
    row = _title(ws, row, "About this workbook")
    row += 1

    row = _kicker(ws, row, "Original question")
    row = _note(ws, row, f'"{question}"')
    row += 1

    for label, value in (("Query ID", query_id), ("Source period", period or "Not stated"),
                         ("Prepared", date.today().strftime("%d %B %Y"))):
        ws.cell(row=row, column=1, value=label).font = Font(name=_FONT, bold=True, size=10, color=_SLATE)
        ws.cell(row=row, column=2, value=value).font = Font(name=_FONT, size=10, color=_NAVY)
        row += 1
    row += 1

    status = ws.cell(row=row, column=1,
                     value="DRAFT - DATA VALIDATION REQUIRED" if draft else "VALIDATED")
    status.font = Font(name=_FONT, bold=True, size=11, color=_WHITE)
    status.fill = PatternFill(fill_type="solid", fgColor=_RED if draft else _MINT)
    row += 1
    if draft:
        for warning in warnings:
            row = _note(ws, row, warning)
        row = _note(ws, row, "See 05_Data_Quality before using any figure in this workbook "
                             "for a decision.", italic=True)
    row += 1

    row = _kicker(ws, row, "What each sheet holds")
    row = _header_row(ws, row, ["Sheet", "Contents"])
    first = row
    for name, description in _SHEETS:
        ws.cell(row=row, column=1, value=name).font = Font(name=_FONT, size=10, color=_NAVY)
        ws.cell(row=row, column=2, value=description).font = Font(name=_FONT, size=10, color=_NAVY)
        row += 1
    _add_table(ws, "SheetIndex", first - 1, 1, row - 1, 2)
    row += 1

    row = _kicker(ws, row, "How figures are written")
    for line in (
        "Currency is stored in naira and displayed in millions, for example NGN 709.0m.",
        "Percentages are stored as fractions (0.331) and displayed as percentages (33.1%).",
        "A change in a percentage is stated in percentage points, never as a percentage.",
        "Derived figures on 03_Analysis are live formulas, so you can check every one.",
        "Nothing in this workbook has been corrected. A defect is reported, not repaired.",
    ):
        row = _note(ws, row, line)
    _autosize(ws)
    ws.column_dimensions["B"].width = 62


def _sheet_executive(wb, insight: dict, analysis: dict, data_quality: dict, currency: str) -> None:
    ws = wb.create_sheet("01_Executive_Summary")
    row = _kicker(ws, 1, "Executive answer")
    row = _title(ws, row, "What the numbers say")
    row += 1

    if insight.get("what"):
        row = _note(ws, row, insight["what"])
        row += 1

    metrics = analysis.get("metrics") or []
    if metrics:
        row = _kicker(ws, row, "Headline figures")
        row = _header_row(ws, row, ["Measure", "Value"])
        first = row
        for metric in metrics:
            label = str(metric.get("label") or "Metric")
            value = as_number(metric.get("value"))
            if value is None:
                continue
            ws.cell(row=row, column=1, value=label).font = Font(name=_FONT, size=10, color=_NAVY)
            cell = ws.cell(row=row, column=2, value=value)
            cell.font = Font(name=_FONT, bold=True, size=10, color=_DEEP_GREEN)
            if is_rate_label(label):
                cell.value = value / 100.0
                cell.number_format = FMT_PERCENT
            elif any(word in label.lower() for word in _COUNT_WORDS):
                cell.number_format = FMT_INT
            else:
                # A raw amount, so the millions format is correct here.
                cell.number_format = FMT_CURRENCY_M
            row += 1
        _add_table(ws, "HeadlineFigures", first - 1, 1, row - 1, 2)
        row += 1

    findings = insight.get("key_findings") or []
    if findings:
        row = _kicker(ws, row, "What was found")
        row = _header_row(ws, row, ["Finding", "Where", "Confidence"])
        first = row
        for finding in findings:
            ws.cell(row=row, column=1, value=str(finding.get("finding", ""))).alignment = Alignment(
                wrap_text=True, vertical="top")
            ws.cell(row=row, column=2, value=str(finding.get("location", "")))
            ws.cell(row=row, column=3, value=str(finding.get("confidence", "")))
            row += 1
        _add_table(ws, "KeyFindings", first - 1, 1, row - 1, 3)
        row += 1

    flagged = insight.get("flagged_items") or []
    if flagged:
        row = _kicker(ws, row, "Flagged")
        for item in flagged:
            cell = ws.cell(row=row, column=1, value=str(item))
            cell.font = Font(name=_FONT, size=10, color=_RED)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            row += 1
        row += 1

    if insight.get("confidence"):
        row = _kicker(ws, row, "How much to trust this")
        row = _note(ws, row, f"Confidence: {insight['confidence']}. "
                             f"{insight.get('confidence_explanation', '')}".strip())
    _autosize(ws)
    ws.column_dimensions["A"].width = 58


def _sheet_clean_data(wb, rows: list[dict], truncated: bool) -> None:
    ws = wb.create_sheet("02_Clean_Data")
    row = _kicker(ws, 1, "Clean data")
    row = _title(ws, row, "The rows the analysis returned")
    if truncated:
        row = _note(ws, row, "These are the first rows of the result, not the whole dataset. "
                             "Totals on 03_Analysis are computed from the full result by the "
                             "analysis pipeline, so they will not always be reproducible by "
                             "summing this sheet.", italic=True)
    row += 1

    if not rows:
        _note(ws, row, "This analysis did not return a table. It answered from documents, so "
                       "there are no rows to list here - see 01_Executive_Summary and 03_Analysis.")
        _autosize(ws)
        return

    headers = _unique_headers(rows)
    keys = list(rows[0].keys())
    header_at = row
    row = _header_row(ws, row, headers)
    rate_columns = {i for i, name in enumerate(headers) if is_rate_label(name)}
    first_data = row
    for record in rows:
        for i, key in enumerate(keys):
            _write_value(ws.cell(row=row, column=1 + i), record.get(key), rate=i in rate_columns)
        row += 1
    _add_table(ws, "CleanData", header_at, 1, row - 1, len(headers))
    ws.freeze_panes = ws.cell(row=first_data, column=1)
    # A missing cell is highlighted rather than left to be noticed: an
    # empty cell in a sea of numbers is exactly what gets read as zero.
    last = f"{get_column_letter(len(headers))}{row - 1}"
    ws.conditional_formatting.add(
        f"A{first_data}:{last}",
        CellIsRule(operator="equal", formula=['""'],
                   fill=PatternFill(fill_type="solid", fgColor=_WARN_BG)),
    )
    _autosize(ws)


def _series_from(charts: list[dict], by_group: list[dict] | None) -> list[dict]:
    """Whatever the analysis produced, as a uniform list of named series."""
    if charts:
        return charts
    if by_group:
        return [{
            "chart_type": "bar", "title": "Breakdown by group",
            "labels": [r.get("group") for r in by_group],
            "values": [r.get("total") for r in by_group],
        }]
    return []


def _sheet_analysis(wb, series: list[dict], used_names: set[str]) -> list[dict]:
    """Writes each series as a table with live formulas, and returns where
    each one landed so 04_Charts can point native charts at it."""
    ws = wb.create_sheet("03_Analysis")
    row = _kicker(ws, 1, "Analysis")
    row = _title(ws, row, "The figures, with every derived value as a formula")
    row = _note(ws, row, "Nothing in the Share, Total or Change columns is typed in. Each is an "
                         "Excel formula over the cells beside it, so any figure can be checked by "
                         "clicking it.", italic=True)
    row += 1

    placements: list[dict] = []
    if not series:
        _note(ws, row, "This analysis produced no chartable series.")
        _autosize(ws)
        return placements

    for index, chart in enumerate(series):
        labels = chart.get("labels") or []
        values = [as_number(v) for v in (chart.get("values") or [])]
        pairs = [(str(l), v) for l, v in zip(labels, values) if v is not None]
        if not pairs:
            continue

        unit = str(chart.get("unit") or "").strip()
        rate = is_rate_label(unit) or is_rate_label(chart.get("title"))
        kind = (chart.get("chart_type") or "bar").lower()
        value_header = f"Value ({unit})" if unit else "Value"

        row = _kicker(ws, row, f"Series {index + 1}")
        title_at = row
        row = _title(ws, row, str(chart.get("title") or "Breakdown"))
        if chart.get("location"):
            row = _note(ws, row, f"Source: {chart['location']}", italic=True)

        # A share-of-total only means something for a composition; over a
        # time series it would be a number with no interpretation. A time
        # series gets period-on-period change instead.
        extra = "Share of total" if kind in ("bar", "pie") else "Change vs previous"
        header_at = row
        row = _header_row(ws, row, ["Category", value_header, extra])
        first_data = row
        for label, value in pairs:
            ws.cell(row=row, column=1, value=label).font = Font(name=_FONT, size=10, color=_NAVY)
            _write_value(ws.cell(row=row, column=2), value, rate=rate)
            row += 1
        last_data = row - 1
        # One blank row between the table and its total. Excel expands a
        # table into the row directly beneath it when someone types
        # there, which would pull the total inside the table and start
        # double-counting it in every filter and chart that reads it.
        total_at = row + 1

        if extra == "Share of total":
            for r in range(first_data, last_data + 1):
                cell = ws.cell(row=r, column=3,
                               value=f"=IFERROR(B{r}/SUM($B${first_data}:$B${last_data}),\"\")")
                cell.number_format = FMT_PERCENT
        else:
            for r in range(first_data + 1, last_data + 1):
                cell = ws.cell(row=r, column=3,
                               value=f"=IFERROR((B{r}-B{r - 1})/ABS(B{r - 1}),\"\")")
                cell.number_format = FMT_PERCENT
        _add_table(ws, _table_name(f"Series_{index + 1}", used_names),
                   header_at, 1, last_data, 3)

        # The total sits OUTSIDE the table: a total row inside an Excel
        # table is picked up by filters and by anything reading the table
        # as data, and starts being double-counted.
        total_label = ws.cell(row=total_at, column=1, value="Total")
        total_label.font = Font(name=_FONT, bold=True, size=10, color=_DEEP_GREEN)
        total_cell = ws.cell(row=total_at, column=2,
                             value=f"=SUM(B{first_data}:B{last_data})")
        total_cell.font = Font(name=_FONT, bold=True, size=10, color=_DEEP_GREEN)
        total_cell.number_format = FMT_PERCENT if rate else FMT_DECIMAL
        if rate:
            ws.cell(row=total_at, column=3,
                    value="A total of percentages is rarely meaningful - shown for completeness."
                    ).font = Font(name=_FONT, size=9, italic=True, color=_SLATE)
        row = total_at + 2

        placements.append({
            "chart": chart, "title": str(chart.get("title") or "Breakdown"),
            "kind": kind, "rate": rate, "unit": unit,
            "header_row": header_at, "first": first_data, "last": last_data,
        })

    _autosize(ws)
    ws.column_dimensions["A"].width = 34
    return placements


def _sheet_charts(wb, placements: list[dict]) -> None:
    ws = wb.create_sheet("04_Charts")
    row = _kicker(ws, 1, "Charts")
    row = _title(ws, row, "What the figures look like")
    row = _note(ws, row, "Every chart is a native Excel chart reading from 03_Analysis. Change a "
                         "value there and the chart follows.", italic=True)
    row += 1

    if not placements:
        _note(ws, row, "This analysis produced no chartable series.")
        _autosize(ws)
        return

    source = wb["03_Analysis"]
    for place in placements:
        anchor_row = row
        heading = ws.cell(row=row, column=1, value=place["title"])
        heading.font = Font(name=_FONT, bold=True, size=12, color=_DEEP_GREEN)
        row += 1

        takeaway = str(place["chart"].get("insight") or "").strip()
        if takeaway:
            cell = ws.cell(row=row, column=1, value=takeaway)
            cell.font = Font(name=_FONT, size=10, color=_NAVY)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row].height = max(15, 13 * (1 + len(takeaway) // 70))
        row += 2

        kind = place["kind"]
        chart = LineChart() if kind == "line" else (PieChart() if kind == "pie" else BarChart())
        chart.title = place["title"]
        if not isinstance(chart, PieChart):
            chart.y_axis.title = place["unit"] or "Value"
            # A line chart's categories are periods, not categories - an
            # axis labelled "Category" over Jan..Dec tells a reader less
            # than no label at all.
            chart.x_axis.title = "Period" if kind == "line" else "Category"
            chart.y_axis.majorGridlines = ChartLines()
        data = Reference(source, min_col=2, min_row=place["header_row"], max_row=place["last"])
        cats = Reference(source, min_col=1, min_row=place["first"], max_row=place["last"])
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.height = 8
        chart.width = 18
        ws.add_chart(chart, f"E{anchor_row}")
        row = max(row + 16, anchor_row + 18)

    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 12


def _sheet_data_quality(wb, data_quality: dict, analysis: dict, warnings: list[str]) -> None:
    ws = wb.create_sheet("05_Data_Quality")
    row = _kicker(ws, 1, "Data quality")
    row = _title(ws, row, "What can be trusted - and what cannot")
    row = _note(ws, row, "Nothing here has been corrected. A defect is reported so it can be "
                         "repaired at source, not hidden to make the workbook look clean.",
                italic=True)
    row += 1

    header_at = row
    row = _header_row(ws, row, ["Area", "Status", "Assessment"])
    first_data = row

    rows_analysed = as_number(data_quality.get("row_count"))
    if rows_analysed is not None:
        ws.cell(row=row, column=1, value="Rows analysed")
        ws.cell(row=row, column=2, value="Reported")
        cell = ws.cell(row=row, column=3, value=rows_analysed)
        cell.number_format = FMT_INT
        row += 1
    completeness = as_number(data_quality.get("completeness_pct"))
    if completeness is not None:
        level = "High" if completeness >= 98 else "Moderate" if completeness >= 90 else "Low"
        ws.cell(row=row, column=1, value="Field completeness")
        ws.cell(row=row, column=2, value=level)
        cell = ws.cell(row=row, column=3, value=completeness / 100.0)
        cell.number_format = FMT_PERCENT
        row += 1
    duplicates = as_number(data_quality.get("duplicate_pct"))
    if duplicates is not None:
        level = "High" if duplicates == 0 else "Moderate" if duplicates < 5 else "Low"
        ws.cell(row=row, column=1, value="Duplicate rows")
        ws.cell(row=row, column=2, value=level)
        cell = ws.cell(row=row, column=3, value=duplicates / 100.0)
        cell.number_format = FMT_PERCENT
        row += 1
    for name, confidence in (analysis.get("confidence") or {}).items():
        ws.cell(row=row, column=1, value=str(name).title())
        ws.cell(row=row, column=2, value=str(confidence.get("level", "")).replace("_", " ").title())
        ws.cell(row=row, column=3, value=str(confidence.get("reason", ""))).alignment = Alignment(
            wrap_text=True, vertical="top")
        row += 1
    if warnings:
        ws.cell(row=row, column=1, value="Percentage fields")
        ws.cell(row=row, column=2, value="Unusable")
        ws.cell(row=row, column=3, value=warnings[0]).alignment = Alignment(
            wrap_text=True, vertical="top")
        row += 1
    for note in (data_quality.get("notes") or []):
        ws.cell(row=row, column=1, value="Note")
        ws.cell(row=row, column=2, value="Moderate")
        ws.cell(row=row, column=3, value=str(note)).alignment = Alignment(
            wrap_text=True, vertical="top")
        row += 1

    if row > first_data:
        _add_table(ws, "DataQuality", header_at, 1, row - 1, 3)
        ws.freeze_panes = ws.cell(row=first_data, column=1)
        # The only conditional formatting in the workbook, and it marks
        # the one thing a reader must not miss.
        status_range = f"B{first_data}:B{row - 1}"
        ws.conditional_formatting.add(status_range, CellIsRule(
            operator="equal", formula=['"Unusable"'],
            fill=PatternFill(fill_type="solid", fgColor=_WARN_BG),
            font=Font(name=_FONT, bold=True, color=_RED)))
        ws.conditional_formatting.add(status_range, CellIsRule(
            operator="equal", formula=['"Low"'],
            font=Font(name=_FONT, bold=True, color=_GOLD)))
    else:
        _note(ws, row, "No data-quality measures were recorded for this analysis.")
    _autosize(ws)
    ws.column_dimensions["C"].width = 70


def _sheet_assumptions(wb, insight: dict, analysis: dict, sql: str) -> None:
    ws = wb.create_sheet("06_Assumptions")
    row = _kicker(ws, 1, "Assumptions")
    row = _title(ws, row, "What these figures do not cover")
    row += 1

    scope = analysis.get("scope") or {}
    quality = analysis.get("quality") or {}
    limitations = [
        scope.get("metric_definition") or "The metric definition was not independently established.",
        *(scope.get("assumptions") or []),
        *(quality.get("limitations") or []),
    ]
    for item in (str(i) for i in limitations if i):
        row = _note(ws, row, item)
    row += 1

    row = _kicker(ws, row, "Formulas used in this workbook")
    row = _header_row(ws, row, ["Sheet", "Column", "Formula", "What it does"])
    first = row
    for sheet, column, formula, meaning in (
        ("03_Analysis", "Share of total", "=IFERROR(B/SUM(B:B),\"\")",
         "Each category as a share of that series' own total."),
        ("03_Analysis", "Change vs previous", "=IFERROR((B-B_prev)/ABS(B_prev),\"\")",
         "Period-on-period change, as a relative percentage."),
        ("03_Analysis", "Total", "=SUM(B:B)",
         "The series total, held outside the table so filters cannot double-count it."),
    ):
        ws.cell(row=row, column=1, value=sheet)
        ws.cell(row=row, column=2, value=column)
        ws.cell(row=row, column=3, value=formula).font = Font(name="Consolas", size=10, color=_NAVY)
        ws.cell(row=row, column=4, value=meaning).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    _add_table(ws, "Formulas", first - 1, 1, row - 1, 4)
    row += 1

    row = _kicker(ws, row, "Method")
    row = _note(ws, row,
                "Generated by an AI analytics agent restricted to read-only, authorized queries. "
                "All figures were computed deterministically, not by the language model; the model "
                "was used only to translate the question into a query and to interpret results that "
                "had already been computed.")
    if sql:
        row = _note(ws, row, f"Query: {sql}")
    row += 1

    evidence = analysis.get("evidence") or []
    if evidence:
        row = _kicker(ws, row, "Sources")
        row = _header_row(ws, row, ["Source", "Method", "Version"])
        first = row
        for source in evidence:
            ws.cell(row=row, column=1, value=str(source.get("filename") or source.get("source_id", "")))
            ws.cell(row=row, column=2, value=str(source.get("method", "")).replace("_", " "))
            ws.cell(row=row, column=3, value=str(source.get("source_version") or "unavailable"))
            row += 1
        _add_table(ws, "Sources", first - 1, 1, row - 1, 3)
    _autosize(ws)
    ws.column_dimensions["A"].width = 64


# ------------------------------------------------------------------- public

def export_xlsx(snapshot: dict, base_name: str, *, question: str = "", query_id: str = "",
                period: str | None = None, currency: str = "NGN", sql: str = "") -> str:
    """Builds the Meridian workbook from a query's result snapshot.

    Takes the whole snapshot rather than a list of rows: the six sheets
    beyond 02_Clean_Data are the analysis, its quality and its
    assumptions, none of which exist in a bare table. A document-only
    analysis with no table at all still produces a full, useful workbook.
    """
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, f"meridian-{base_name}-{uuid.uuid4().hex}.xlsx")

    snapshot = snapshot or {}
    insight = snapshot.get("insight") or {}
    analysis = snapshot.get("analysis") or {}
    data_quality = snapshot.get("data_quality") or {}
    charts = snapshot.get("charts") or []
    rows = snapshot.get("preview_rows") or []

    warnings: list[str] = []
    for chart in charts:
        warnings.extend(percent_warnings(
            chart.get("labels") or [], chart.get("values") or [],
            chart.get("unit"), chart.get("title"),
        ))
    draft = bool(warnings) or "error" in insight

    wb = Workbook()
    wb.remove(wb.active)          # drop openpyxl's default "Sheet"
    used_names: set[str] = set()

    _sheet_read_me(wb, question, query_id, period, draft, warnings)
    _sheet_executive(wb, insight, analysis, data_quality, currency)
    _sheet_clean_data(wb, rows, truncated=bool(rows))
    placements = _sheet_analysis(wb, _series_from(charts, snapshot.get("by_group")), used_names)
    _sheet_charts(wb, placements)
    _sheet_data_quality(wb, data_quality, analysis, warnings)
    _sheet_assumptions(wb, insight, analysis, sql or snapshot.get("sql", ""))

    wb.properties.creator = "Meridian"
    wb.properties.last_modified_by = "Meridian"
    wb.properties.title = base_name
    wb.properties.description = "Generated by Meridian - getmeridiananalytics.com"
    for ws in wb.worksheets:
        # Print-only; never touches a cell, so a script reading this file
        # back with pandas/openpyxl sees exactly the same data.
        ws.oddFooter.center.text = "Made by Meridian"
        ws.oddFooter.right.text = "Page &P of &N"

    wb.save(path)
    return path
