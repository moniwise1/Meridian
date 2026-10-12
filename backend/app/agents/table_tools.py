"""Bounded analysis of already-authorized, parsed files. No code execution or IO."""
import math
from dataclasses import dataclass
import pandas as pd


TABLE_ANALYSIS_TOOL = {
    "name": "analyze_table",
    "description": "Calculate directly from a listed parsed table. Use for filtering, ranking groups, comparing segments, totals, averages, counts and weighted rates. For conversion rates use rate with numerator value_column and denominator_column; this computes 100 * sum(numerator) / sum(denominator) over rows with both values present. Prefer this to transcribing values from text. Tables are independent: this tool never joins files. Results cover the listed parsed rows only. Report operation, filters, missing values and any truncated groups as limitations; evidence supports differences, not causal claims.",
    "input_schema": {"type": "object", "properties": {
        "table_id": {"type": "string"},
        "operation": {"type": "string", "enum": ["sum", "average", "median", "min", "max", "count", "rate"]},
        "value_column": {"type": "string"},
        "denominator_column": {"type": "string"},
        "group_column": {"type": "string"},
        "order": {"type": "string", "enum": ["descending", "ascending"]},
        "filters": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {
            "column": {"type": "string"}, "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte"]},
            "value": {"type": ["string", "number", "boolean"]}}, "required": ["column", "operator", "value"], "additionalProperties": False}},
    }, "required": ["table_id", "operation"], "additionalProperties": False},
}


@dataclass
class ParsedTable:
    table_id: str
    filename: str
    dataframe: pd.DataFrame


class TableWorkspace:
    def __init__(self, tables):
        self.tables = {t.table_id: t for t in tables}
        self.evidence = []

    def catalog(self):
        return [{"table_id": t.table_id, "filename": t.filename, "parsed_row_count": len(t.dataframe),
                 "columns": [{"name": str(c), "numeric": pd.api.types.is_numeric_dtype(t.dataframe[c])}
                             for c in t.dataframe.columns],
                 "scope": "Independently parsed table; no cross-file join or automatic date filter."}
                for t in self.tables.values()]

    def execute(self, raw):
        if len(self.evidence) >= 12:
            return {"error": "Calculation budget reached. Finish using the available evidence."}
        result = self._execute(raw)
        if "error" not in result:
            result["evidence_id"] = f"table-calculation-{len(self.evidence) + 1}"
            self.evidence.append(result)
        return result

    def _execute(self, raw):
        if not isinstance(raw, dict) or set(raw) - {"table_id", "operation", "value_column", "group_column", "order", "filters", "denominator_column"}:
            return {"error": "Invalid table calculation arguments."}
        table = self.tables.get(raw.get("table_id")) if isinstance(raw.get("table_id"), str) else None
        if table is None:
            return {"error": "Choose a table_id from the authorized parsed-table catalog."}
        operation = raw.get("operation")
        if not isinstance(operation, str) or operation not in {"sum", "average", "median", "min", "max", "count", "rate"}:
            return {"error": "Unsupported calculation."}
        value, group = raw.get("value_column"), raw.get("group_column")
        df = table.dataframe
        if group is not None and (not isinstance(group, str) or group not in df.columns):
            return {"error": "Unknown group column."}
        if operation != "count" and (not isinstance(value, str) or value not in df.columns or not pd.api.types.is_numeric_dtype(df[value])):
            return {"error": "Choose a numeric value_column from the catalog."}
        if operation == "count" and value is not None:
            return {"error": "Count counts rows; omit value_column."}
        denominator = raw.get("denominator_column")
        if operation == "rate":
            if not isinstance(denominator, str) or denominator not in df.columns or not pd.api.types.is_numeric_dtype(df[denominator]):
                return {"error": "Rate requires a numeric denominator_column."}
            if denominator == value:
                return {"error": "Choose distinct numerator and denominator columns."}
        elif denominator is not None:
            return {"error": "denominator_column applies only to rate."}
        order = raw.get("order", "descending")
        if not isinstance(order, str) or order not in {"ascending", "descending"}:
            return {"error": "Invalid ordering."}
        filters = raw.get("filters", [])
        if not isinstance(filters, list) or len(filters) > 4:
            return {"error": "Use at most four filters."}
        for f in filters:
            if not isinstance(f, dict) or set(f) != {"column", "operator", "value"}:
                return {"error": "Invalid filter."}
            col, op, val = f["column"], f["operator"], f["value"]
            if not isinstance(col, str) or col not in df.columns or not isinstance(op, str) or op not in {"eq", "ne", "gt", "gte", "lt", "lte"}:
                return {"error": "Unknown filter column or operator."}
            series = df[col]
            if pd.api.types.is_numeric_dtype(series):
                if isinstance(val, bool):
                    return {"error": "Numeric filters require a finite number."}
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    return {"error": "Numeric filters require a finite number."}
                if not math.isfinite(val):
                    return {"error": "Numeric filters require a finite number."}
            else:
                if not isinstance(val, str) or len(val) > 500:
                    return {"error": "Text filters require a string up to 500 characters."}
                if op not in {"eq", "ne"}:
                    return {"error": "Text supports exact eq/ne only; date ranges require a parsed numeric date representation."}
                series = series.astype("string")
            mask = {"eq": series.eq, "ne": series.ne, "gt": series.gt, "gte": series.ge,
                    "lt": series.lt, "lte": series.le}[op](val)
            df = df.loc[mask.fillna(False) & series.notna()]
        def calculate(frame):
            if operation == "count":
                return int(len(frame))
            if operation == "rate":
                pairs = frame[[value, denominator]].dropna()
                pairs = pairs.loc[pairs.apply(lambda row: all(math.isfinite(float(v)) for v in row), axis=1)]
                if pairs.empty or (pairs < 0).any().any():
                    return None
                try:
                    numerator_total = math.fsum(float(v) for v in pairs[value])
                    denominator_total = math.fsum(float(v) for v in pairs[denominator])
                except OverflowError:
                    return None
                rate = 100 * numerator_total / denominator_total if denominator_total > 0 else None
                return float(rate) if rate is not None and math.isfinite(float(rate)) else None
            numbers = frame[value].dropna()
            numbers = numbers.loc[numbers.map(lambda v: math.isfinite(float(v)))]
            if numbers.empty:
                return None
            if operation in {"sum", "average"}:
                try:
                    result = math.fsum(float(v) for v in numbers)
                except OverflowError:
                    return None
                if operation == "average":
                    result /= len(numbers)
            else:
                result = getattr(numbers, operation)()
            return float(result) if math.isfinite(float(result)) else None
        missing = 0 if operation == "count" else int(df[value].isna().sum() + df[value].dropna().map(lambda v: not math.isfinite(float(v))).sum())
        if operation == "rate":
            pairs = df[[value, denominator]]
            missing = int((~pairs.apply(lambda row: all(pd.notna(v) and math.isfinite(float(v)) for v in row), axis=1)).sum())
        rows = []
        if group:
            if df[group].nunique(dropna=False) > 1000:
                return {"error": "Too many groups. Apply narrower filters or select a lower-cardinality group column."}
            for key, frame in df.groupby(group, dropna=False, observed=True):
                rows.append({"group": None if pd.isna(key) else str(key)[:500],
                             "value": calculate(frame), "row_count": len(frame)})
            rows.sort(key=lambda row: (row["value"] is None, -(row["value"] or 0) if order == "descending" else (row["value"] or 0)))
        return {"table_id": table.table_id, "filename": table.filename, "operation": operation,
                "value_column": value, "group_column": group, "filters": filters,
                "denominator_column": denominator, "unit": "%" if operation == "rate" else None,
                "parsed_row_count": len(table.dataframe), "matched_row_count": len(df),
                "excluded_numeric_values": missing, "result": calculate(df),
                "groups": rows[:50], "total_groups": len(rows), "groups_truncated": len(rows) > 50,
                "scope": "Parsed rows only; exact filters; no join, implicit period or causal inference. Rates use paired valid rows; negative operands or a zero denominator return null."}
