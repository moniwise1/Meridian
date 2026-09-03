"""
Export (BUILD SPEC section 22). Exports operate on the already-aggregated
result (by_group / preview_rows), never on a fresh unrestricted query - an
export cannot pull more than what the original authorized analysis already
retrieved and passed its output check.
"""
import os
import uuid
import pandas as pd
from app.config import settings


def export_csv(rows: list[dict], base_name: str) -> str:
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, f"{base_name}-{uuid.uuid4().hex[:8]}.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def export_xlsx(rows: list[dict], base_name: str) -> str:
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, f"{base_name}-{uuid.uuid4().hex[:8]}.xlsx")
    pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")
    return path
