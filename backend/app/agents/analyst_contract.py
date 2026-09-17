"""Versioned UI contract. Numbers/provenance are assembled by code, never the LLM.

Legacy snapshots remain available for existing exports and old clients. The new
analysis object is persisted alongside them, so reopening preserves its evidence.
"""
import math
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Confidence(StrictModel):
    level: Literal["high", "medium", "low", "not_assessable"]
    reason: str


class ConfidenceSet(StrictModel):
    measurement: Confidence
    explanation: Confidence


class Column(StrictModel):
    key: str
    label: str
    type: Literal["string", "number"]
    unit: str | None = None


class Table(StrictModel):
    id: str
    title: str
    columns: list[Column]
    rows: list[dict[str, str | float | int | None]]
    evidence_ids: list[str]


class Chart(StrictModel):
    type: Literal["bar", "line"]
    title: str
    table_id: str
    category_key: str
    value_keys: list[str]


class Metric(StrictModel):
    id: str
    label: str
    value: float | None
    unit: str | None = None
    evidence_ids: list[str]


class Finding(StrictModel):
    id: str
    kind: Literal["observation", "anomaly", "hypothesis"]
    text: str
    evidence_ids: list[str]


class Evidence(StrictModel):
    id: str
    source_id: str
    source_version: str | None = None
    filename: str | None = None
    location: str | None = None
    computation_id: str
    method: Literal["computed", "extracted_text"]


class Scope(StrictModel):
    question: str
    source_ids: list[str]
    metric_definition: str | None = None
    period: str | None = None
    comparison: str | None = None
    currency: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class Quality(StrictModel):
    row_count: int | None
    completeness_pct: float | None
    duplicate_pct: float | None
    excluded_rows: int | None
    data_through: str | None
    limitations: list[str]


class FollowUp(StrictModel):
    label: str
    question: str


class Action(StrictModel):
    label: str
    reason: str


class Analysis(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    analysis_id: str
    status: Literal["complete", "partial", "insufficient_data", "error"]
    headline: str
    summary: str
    scope: Scope
    metrics: list[Metric]
    tables: list[Table]
    charts: list[Chart]
    findings: list[Finding]
    quality: Quality
    confidence: ConfidenceSet
    actions: list[Action]
    follow_ups: list[FollowUp]
    evidence: list[Evidence]

    @model_validator(mode="after")
    def check_references(self):
        evidence = {e.id for e in self.evidence}
        tables = {t.id: t for t in self.tables}
        for item in [*self.metrics, *self.tables, *self.findings]:
            if not set(item.evidence_ids) <= evidence:
                raise ValueError("Unknown evidence reference")
        for table in self.tables:
            columns = {c.key: c for c in table.columns}
            for row in table.rows:
                if set(row) != set(columns):
                    raise ValueError("Table row does not match columns")
                for key, value in row.items():
                    if value is None:
                        continue
                    if columns[key].type == "number":
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                            raise ValueError("Invalid numeric cell")
                    elif not isinstance(value, str):
                        raise ValueError("Invalid text cell")
        for chart in self.charts:
            table = tables.get(chart.table_id)
            if not table:
                raise ValueError("Unknown chart table")
            columns = {c.key: c.type for c in table.columns}
            if chart.category_key not in columns or any(columns.get(k) != "number" for k in chart.value_keys):
                raise ValueError("Invalid chart columns")
        return self


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def build_analysis(query_id: str, question: str, snapshot: dict, *, sources: list[dict],
                   profile: dict | None = None, computed: bool = True) -> dict:
    """Adapt verified results. Text-extracted charts are never passed off as computed."""
    insight = snapshot.get("insight") or {}
    quality = snapshot.get("data_quality") or {}
    metrics_data = snapshot.get("metrics") or {}
    evidence = [Evidence(id=f"e{i}", source_id=src["id"], source_version=src.get("version"),
                         filename=src.get("filename"), location=src.get("location"),
                         computation_id=query_id, method="computed" if computed else "extracted_text")
                for i, src in enumerate(sources)]
    refs = [e.id for e in evidence]
    limitations = list(quality.get("notes") or [])
    if snapshot.get("truncated"):
        limitations.append("The returned data is truncated; totals may not represent the full population.")
    if any(src.get("truncated") or src.get("ocr") for src in sources):
        limitations.append("Source text was truncated or OCR-extracted; verify important figures against the original file.")
    if not computed:
        limitations.append("No structured table was verified. Figures in the explanation are extracted claims, not independently computed results.")
    if profile:
        limitations.append("Tables below profile the selected worksheet. They are not automatically filtered to every condition in your question.")
    if quality.get("missing_by_column"):
        limitations.append("Some fields are missing. Missing cells are not evidence of zero activity.")
    if snapshot.get("forced_assumption"):
        limitations.append("Clarification was skipped or already offered; review the stated assumptions before acting.")
    limitations = list(dict.fromkeys(str(v) for v in limitations if v))
    metrics = []
    value_label = (profile or {}).get("primary_value_column") or "returned values"
    if computed:
        for key, label in [("total", f"Sum of {value_label}"), ("mean", f"Average of {value_label}"),
                           ("min", f"Minimum of {value_label}"), ("max", f"Maximum of {value_label}")]:
            if key == "total" and re.search(r"%|\b(rate|ratio|margin|percentage|percent|utilization|conversion)\b", value_label.replace("_", " "), re.I):
                continue
            if _number(metrics_data.get(key)) is not None:
                metrics.append(Metric(id=key, label=label, value=_number(metrics_data[key]), evidence_ids=refs))
    tables, charts = [], []

    def add_table(title, rows, category="group", value="value", value_title="Value", chart_type="bar"):
        tid = f"table_{len(tables)}"
        clean = [{category: str(r.get(category, "")), value: _number(r.get(value))} for r in rows[:60]]
        if not clean:
            return
        tables.append(Table(id=tid, title=title, columns=[Column(key=category, label=category.title(), type="string"),
                            Column(key=value, label=value_title, type="number")], rows=clean, evidence_ids=refs))
        charts.append(Chart(type=chart_type, title=title, table_id=tid, category_key=category, value_keys=[value]))

    if computed and profile:
        for dimension, rows in (profile.get("breakdowns") or {}).items():
            add_table(f"Average {value_label} by {dimension}", rows, value_title=f"Average {value_label}")
        if profile.get("trend"):
            add_table(f"Monthly average {value_label}", profile["trend"], "period", "average", f"Average {value_label}", "line")
    elif computed and snapshot.get("by_group"):
        add_table("Returned values by group", snapshot["by_group"], value="total", value_title="Sum")
    # Always expose a structured result even when the query has no group axis.
    if computed and not tables and metrics:
        tables.append(Table(id="metric_table", title="Computed measures", columns=[
            Column(key="measure", label="Measure", type="string"), Column(key="value", label="Value", type="number")],
            rows=[{"measure": m.label, "value": m.value} for m in metrics], evidence_ids=refs))
    findings = [Finding(id=f"anomaly_{i}", kind="anomaly", text=str(a.get("what", "")), evidence_ids=refs)
                for i, a in enumerate(snapshot.get("anomalies") or []) if a.get("what")]
    # Retain document interpretations, but never label model prose as a
    # verified measurement or causal finding.
    findings.extend(Finding(id=f"interpretation_{i}", kind="hypothesis",
        text=str(f["finding"]), evidence_ids=refs)
        for i, f in enumerate(insight.get("key_findings") or [])
        if isinstance(f, dict) and f.get("finding"))
    completeness = _number(quality.get("completeness_pct")) if computed else None
    duplicate = _number(quality.get("duplicate_pct")) if computed else None
    severe = (completeness is not None and completeness < 80) or (duplicate is not None and duplicate > 20)
    has_rows = computed and snapshot.get("row_count", 0) > 0
    measure_level = "not_assessable" if not has_rows else "low" if severe else "medium"
    reason = "No independently verified numeric result is available." if not has_rows else (
        "Material missingness or duplication limits reliability." if severe else
        "Values were computed from the available records; metric definitions and full-period coverage still require review.")
    explanation_level = "low" if insight.get("confidence") == "low" or severe or not computed else "medium"
    if not insight or "error" in insight:
        explanation_level = "not_assessable"
    status = "insufficient_data" if not computed and not insight.get("what") else "partial"
    if "error" in insight:
        status = "partial" if metrics or tables else "error"
    next_question = insight.get("next_question") or ""
    return Analysis(
        analysis_id=query_id, status=status,
        headline=insight.get("what") or ("Computed results are ready; the explanation is unavailable." if has_rows else "There is not enough verified data to answer."),
        summary=insight.get("body") or insight.get("contributors") or insight.get("data_quality_caveat") or "",
        scope=Scope(question=question, source_ids=[s["id"] for s in sources],
                    metric_definition=(f"Profile of {value_label}; group tables use arithmetic means." if profile else snapshot.get("sql_rationale")),
                    period=metrics_data.get("latest_period"), comparison=metrics_data.get("previous_period"),
                    assumptions=["Currency and full-period completeness were not independently established."]),
        metrics=metrics, tables=tables, charts=charts, findings=findings,
        quality=Quality(row_count=snapshot.get("row_count") if computed else None, completeness_pct=completeness,
                        duplicate_pct=duplicate, excluded_rows=quality.get("excluded_row_count") if computed else None,
                        data_through=None, limitations=limitations),
        confidence=ConfidenceSet(measurement=Confidence(level=measure_level, reason=reason),
                                 explanation=Confidence(level=explanation_level, reason=insight.get("confidence_explanation") or "Causal explanations have not been independently established.")),
        actions=[Action(label="Check the source and metric definition", reason="Confirm scope and quality before using these findings to make a decision.")],
        follow_ups=[FollowUp(label=next_question, question=next_question)] if next_question else [], evidence=evidence,
    ).model_dump(mode="json")
