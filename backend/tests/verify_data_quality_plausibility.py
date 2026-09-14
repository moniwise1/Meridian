"""
Regression guard for the plausibility/bounds check in data_quality.py:
assess() now flags a percent/rate/score-named column whose values are wildly
outside a sane range (the exact class of bug behind a real incident where a
shipping company's on-time-delivery report showed "9420.0%" and nothing
deterministic caught it), and scan_text_for_implausible_percentages() does
the same, more shallowly, for document text with no parseable table (e.g. a
PDF). Both are additive: existing outlier_notes/notes behavior for ordinary
data must be unaffected.
Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_data_quality_plausibility.py
"""
import pandas as pd

from app.agents.data_quality import assess, scan_text_for_implausible_percentages

# --- 1. the real incident: an "On-Time Delivery %" column with one absurd value ---
df1 = pd.DataFrame({
    "Region": ["North", "South", "East", "West", "North", "South", "East", "West"],
    "On-Time Delivery %": [92.0, 88.5, 9420.0, 95.1, 91.0, 89.0, 93.5, 90.2],
})
report1 = assess(df1)
assert any("On-Time Delivery %" in n and "9420" in n for n in report1.notes), report1.notes
print("1. OK  a percent-like column with a wildly implausible value (9420.0) is flagged in notes")

# --- 2. an ordinary, plausible percent column raises nothing ---
df2 = pd.DataFrame({
    "Achievement Rate": [92.0, 88.5, 101.0, 95.1, 91.0, 89.0, 93.5, 150.0],
})
report2 = assess(df2)
assert report2.notes == [], report2.notes
print("2. OK  an ordinary percent column (even a >100% quota-achievement figure) is left alone")

# --- 3. a non-percent-named numeric column with a large value is not flagged as implausible
#        (this check is name-scoped, not a blanket magnitude check - that's outlier_notes' job) ---
df3 = pd.DataFrame({"Revenue": [92000.0, 88500.0, 9420000.0, 95100.0, 91000.0, 89000.0, 93500.0, 90200.0]})
report3 = assess(df3)
assert report3.notes == [], report3.notes
print("3. OK  a large value in a non-percent-named column doesn't trigger the plausibility note")

# --- 4. existing outlier_notes / completeness / duplicate behavior is unchanged ---
df4 = pd.DataFrame({"Score": [10, 11, 9, 12, 10, 11, 9, 10, 12, 11, 10, 9, 10, 11, 300]})
report4 = assess(df4)
assert any("outlier" in n for n in report4.outlier_notes), report4.outlier_notes
print("4. OK  the existing z-score outlier_notes check still fires independently")

# --- 5. zero-row input still short-circuits exactly as before ---
report5 = assess(pd.DataFrame({"A": []}))
assert report5.row_count == 0 and report5.notes == ["Query returned zero rows."]
print("5. OK  zero-row input unaffected")

# --- 6. text-scan: catches the same class of value in raw PDF-extracted text ---
notes6 = scan_text_for_implausible_percentages(
    "Regional summary: On-Time Delivery was 9420.0% in Q3, up from 92% in Q2."
)
assert len(notes6) == 1 and "9420" in notes6[0], notes6
print("6. OK  text-scan flags an implausible percentage found in raw document text")

# --- 7. text-scan: an ordinary percentage in text raises nothing ---
notes7 = scan_text_for_implausible_percentages("Growth was 150% year over year, and margin was 42%.")
assert notes7 == [], notes7
print("7. OK  text-scan leaves ordinary (even >100%) percentages alone")

# --- 8. text-scan: empty/None text doesn't raise ---
assert scan_text_for_implausible_percentages("") == []
assert scan_text_for_implausible_percentages(None) == []
print("8. OK  text-scan handles empty/None input without raising")

print("\nall data quality plausibility checks passed")
