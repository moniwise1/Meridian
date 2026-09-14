"""
Regression guard for gap #3 of the Ask-engine audit: a document analysis
with no database involved got no investigation/drill-down cascade at all,
even when its parsed table has more than one usable dimension column.
tabular_analysis.py's investigate_document_anomalies() is the in-memory
analog of investigation.py's investigate_cascade() - same "decline -> by
next dimension -> its top contributor" idea, but by filtering the table
already parsed into memory instead of running new SQL queries (there is no
live connector for a document, so there is nothing further to query).
Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_document_investigation_cascade.py
"""
import pandas as pd

from app.agents import tabular_analysis
from app.agents.tabular_analysis import build_profile, compute_data_quality_and_anomalies, investigate_document_anomalies

# --- 1. a table with two group columns (Region, Product): West collapses
#        sharply between the two months while North/South/East grow
#        normally - a real period-over-period growth-rate anomaly for
#        West. Within West, Product A accounts for most of the collapse
#        (60->2) while Product B holds up better (40->8) - the cascade
#        should drill into West and report Product as the next dimension,
#        with A as its top contributor. ---
rows = []
for region, m1, m2 in [("North", 100, 105), ("South", 100, 106), ("East", 100, 104)]:
    rows.append({"Region": region, "Product": "A", "Month": "2026-01-01", "Sales": m1})
    rows.append({"Region": region, "Product": "A", "Month": "2026-02-01", "Sales": m2})
rows += [
    {"Region": "West", "Product": "A", "Month": "2026-01-01", "Sales": 60},
    {"Region": "West", "Product": "B", "Month": "2026-01-01", "Sales": 40},
    {"Region": "West", "Product": "A", "Month": "2026-02-01", "Sales": 2},
    {"Region": "West", "Product": "B", "Month": "2026-02-01", "Sales": 8},
]
df = pd.DataFrame(rows)

profile = build_profile(df, "How did sales change by region?")
assert profile.primary_group_column == "Region", profile.primary_group_column
quality, anomalies = compute_data_quality_and_anomalies(df, profile)
assert len(anomalies) == 1 and anomalies[0].segment == "West", anomalies
print("1. OK  a sharp period-over-period decline in one region is still detected exactly as before "
      "(no regression from adding a second group column)")

results = investigate_document_anomalies(df, profile, anomalies)
assert len(results) == 1, results
assert results[0]["dimension"] == "Product", results[0]
assert results[0]["breakdown"][0]["group"] == "A", results[0]["breakdown"]
assert results[0]["breakdown"][0]["total"] == 62.0, results[0]["breakdown"]
print("2. OK  the anomalous region (West) gets drilled down by the other real dimension (Product), "
      "correctly identifying A (60+2=62) as the top contributor to the collapse")

# --- 3. no anomalies at all -> no investigation, exactly like the DB path
#        skips investigate_cascade entirely when nothing was detected ---
assert investigate_document_anomalies(df, profile, []) == []
print("3. OK  no anomalies means no investigation results (mirrors the DB path's own behavior)")

# --- 4. a single-group-column table (no second dimension to drill into)
#        returns [] rather than erroring - most real documents only have
#        one usable group column, and this must be a silent no-op for them ---
single_group_df = df.drop(columns=["Product"])
single_profile = build_profile(single_group_df, "How did sales change by region?")
_, single_anomalies = compute_data_quality_and_anomalies(single_group_df, single_profile)
assert investigate_document_anomalies(single_group_df, single_profile, single_anomalies) == []
print("4. OK  a table with only one usable group column returns [] instead of erroring")

print("\nall document investigation cascade checks passed")
