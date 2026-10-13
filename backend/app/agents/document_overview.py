"""Deterministic upload overview; no model calls or record samples."""
import numpy as np
from app.agents import tabular_analysis


def overview(doc):
    result = {
        "mode": "text", "row_count": None, "column_count": 0,
        "fields": [], "missing_cells": 0, "duplicate_rows": 0,
        "notes": [], "suggested_questions": [
            "Summarise this file's key points and cite the supporting passages.",
            "Which inconsistencies or gaps should I verify in this file?",
            "What questions can this file answer, and what information is missing?",
        ],
    }
    if doc.extraction_truncated:
        result["notes"].append("Extracted text is limited to the first 50,000 characters.")
    tables, diagnostics = tabular_analysis.extract_tables(doc.file_path, doc.kind)
    table = tabular_analysis.pick_best_table(tables)
    if table is None:
        result["notes"].extend(diagnostics[:3])
        return result
    result.update(mode="table", row_count=len(table), column_count=len(table.columns))
    # Match the numerical workspace's finite-value treatment. Duplicate rows
    # are candidates for review, never automatically removed.
    clean = table.replace([np.inf, -np.inf], np.nan)
    missing = clean.isna()
    for column in clean.select_dtypes(include="object").columns:
        missing[column] = missing[column] | clean[column].map(lambda v: isinstance(v, str) and not v.strip())
    result["missing_cells"] = int(missing.to_numpy().sum())
    try:
        result["duplicate_rows"] = int(clean.duplicated().sum())
    except TypeError:
        result["notes"].append("Duplicate-row checks are unavailable for nested values.")
    result["fields"] = [{"name":str(c), "type":"number" if c in clean.select_dtypes(include="number").columns else "text",
                         "missing":int(missing[c].sum())} for c in clean.columns[:24]]
    if len(clean.columns) > 24:
        result["notes"].append("Showing the first 24 fields; quality counts cover the selected table.")
    if len(tables) > 1:
        result["notes"].append(f"Detected {len(tables)} usable tables. This overview covers the table selected by Ask, not the entire file.")
    else:
        result["notes"].append("Counts cover the parsed table selected by Ask; check the original file for omitted headers or sections.")
    if result["duplicate_rows"]:
        result["notes"].append("Repeated rows may be legitimate records. Review them before removing anything.")
    metrics = tabular_analysis.pick_value_columns(clean)
    groups = tabular_analysis.pick_group_columns(clean)
    questions = ["Which missing values or repeated rows could affect conclusions from this file?"]
    if metrics:
        metric = metrics[0]
        questions.insert(0, f'What is the average of "{metric}", excluding missing or invalid values?')
        if groups:
            questions.insert(1, f'Compare the average of "{metric}" by "{groups[0]}" and show each group\'s record count.')
    questions.append("What stands out in this file? Separate observed patterns from possible explanations.")
    result["suggested_questions"] = questions[:3]
    return result
