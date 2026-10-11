"""Explicitly mapped, decimal-based metrics shared by Overview and its Ask panel."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import pandas as pd


class MetricInputError(ValueError):
    pass


def money(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"-?\d+(?:\.\d{1,8})?", text):
        raise MetricInputError("Amount columns must contain plain finite decimal numbers.")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise MetricInputError("Invalid amount.") from exc
    if abs(number) > Decimal("1e15"):
        raise MetricInputError("An amount exceeds the supported range.")
    return number


def display(value):
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if value is not None else None


def compute_overview(frame, mapping, start: date, end: date, detail_date: date | None = None):
    if end < start or (end - start).days > 366:
        raise MetricInputError("Choose an inclusive reporting range of at most 367 days.")
    selected = [mapping[k] for k in ("date_column", "revenue_column", "expense_column") if mapping.get(k)]
    if any(col in {"_row", "_day", "_revenue_column", "_expense_column"} for col in selected):
        raise MetricInputError("Rename reserved internal column names before mapping them.")
    if len(set(selected)) != len(selected):
        raise MetricInputError("Date, revenue and expense mappings must use distinct columns.")
    for col in selected:
        if col not in frame.columns:
            raise MetricInputError("A mapped column is unavailable.")
    currency = mapping["currency"].upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise MetricInputError("Confirm a three-letter currency code.")
    cc = mapping.get("currency_column")
    if cc:
        if cc not in frame.columns or frame[cc].isna().any():
            raise MetricInputError("Currency values are missing.")
        currencies = set(frame[cc].astype(str).str.strip().str.upper())
        if currencies != {currency}:
            raise MetricInputError("This source contains mixed or mismatched currencies. Filter it to one currency before uploading.")
    work = frame.copy()
    # Keep original physical row identities through every period filter.
    work["_row"] = [int(i) + 2 for i in work.index]
    dates = []
    for value in work[mapping["date_column"]]:
        try:
            if pd.isna(value):
                raise ValueError("missing date")
            if isinstance(value, (date, pd.Timestamp)):
                dates.append(value.date() if hasattr(value, "date") else value)
            else:
                dates.append(date.fromisoformat(str(value).strip()))
        except (ValueError, TypeError):
            raise MetricInputError("Dates must be valid spreadsheet dates or ISO YYYY-MM-DD values; ambiguous dates are not guessed.")
    work["_day"] = dates
    duplicate_count = int(frame.duplicated().sum())
    if duplicate_count and not mapping.get("include_duplicates", False):
        raise MetricInputError("Repeated rows were found. Confirm they are legitimate before including them.")
    for key in ("revenue_column", "expense_column"):
        if mapping.get(key):
            work["_" + key] = [money(v) for v in work[mapping[key]]]
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - (end - start)
    current = work[(work._day >= start) & (work._day <= end)]
    previous = work[(work._day >= previous_start) & (work._day <= previous_end)]

    def total(rows, key):
        if not mapping.get(key) or rows.empty:
            return None
        values = list(rows["_" + key])
        return None if any(v is None for v in values) else sum(values, Decimal(0))

    metrics = []
    for key, label in (("revenue_column", "Revenue"), ("expense_column", "Mapped expenses")):
        value, prior = total(current, key), total(previous, key)
        growth = ((value - prior) / abs(prior) * 100) if value is not None and prior not in (None, 0) else None
        metrics.append({"id": key, "label": label, "value": display(value), "previous": display(prior),
                        "change_pct": display(growth), "formula": f"SUM({mapping.get(key) or 'unmapped'})",
                        "unavailable_reason": None if value is not None else "Unmapped, no period records, or missing amounts."})
    revenue, expenses = total(current, "revenue_column"), total(current, "expense_column")
    balance = revenue - expenses if revenue is not None and expenses is not None else None
    metrics.append({"id": "balance", "label": "Revenue less mapped expenses", "value": display(balance),
                    "previous": None, "change_pct": None, "formula": "Revenue − mapped expenses",
                    "unavailable_reason": None if balance is not None else "Requires complete revenue and expense mappings."})
    trend = []
    for day in sorted(set(current._day)):
        rows = current[current._day == day]
        trend.append({"date": day.isoformat(), "revenue": display(total(rows, "revenue_column")),
                      "expenses": display(total(rows, "expense_column"))})
    detail_rows = current if detail_date is None else current[current._day == detail_date]
    if detail_date is not None and not start <= detail_date <= end:
        raise MetricInputError("Drill-down date must be within the reporting period.")
    records = []
    for _, row in detail_rows.head(100).iterrows():
        records.append({"source_row": int(row._row), "date": row._day.isoformat(),
                        "revenue": display(row.get("_revenue_column")), "expenses": display(row.get("_expense_column"))})
    return {"currency": currency, "period": {"start": start.isoformat(), "end": end.isoformat()},
            "previous_period": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
            "metrics": metrics, "trend": trend, "records": records, "record_count": len(current),
            "detail_date": detail_date.isoformat() if detail_date else None, "detail_count": len(detail_rows),
            "records_truncated": len(detail_rows) > 100, "duplicates_included": duplicate_count,
            "limitations": ["Upload snapshot, not a live feed; period completeness is not established.",
                "Negative revenue amounts reduce revenue; negative expenses represent credits.",
                "Revenue less mapped expenses is not certified net profit or cash flow.",
                "Missing amounts make the affected total unavailable; they are never replaced with zero.",
                "All amounts use the confirmed currency; no foreign exchange conversion is applied."]}


def answer_overview(question, overview):
    q = question.lower()
    if any(w in q for w in ("why", "cause", "forecast", "predict", "cash flow", "net profit", "gross")):
        return "The mapped snapshot cannot establish that. Inspect the source records and supply the missing accounting or explanatory data."
    if any(w in q for w in ("expense", "cost", "spend")):
        metric = overview["metrics"][1]
    elif any(w in q for w in ("balance", "difference", "less")):
        metric = overview["metrics"][2]
    elif any(w in q for w in ("revenue", "sales", "income")):
        metric = overview["metrics"][0]
    else:
        return "Ask about revenue, mapped expenses, or revenue less mapped expenses for the selected period."
    if metric["value"] is None:
        return f"{metric['label']} is unavailable: {metric['unavailable_reason']}"
    p = overview["period"]
    answer = f"{metric['label']}: {overview['currency']} {metric['value']} from {p['start']} through {p['end']}. Calculation: {metric['formula']}."
    if metric["previous"] is not None:
        answer += f" Previous equal-length period: {overview['currency']} {metric['previous']}."
    if metric["change_pct"] is not None:
        answer += f" Change: {metric['change_pct']}%."
    return answer
