"""
Calendar-month usage counting for the query/document caps in
app/billing/plans.py. Deliberately NOT a separate running counter that
increments on each action and resets on a schedule - there's no
background scheduler in this app (see app/config.py's audit-anchor
settings for the same constraint elsewhere), and a counter needing a
monthly reset job is exactly the kind of thing that silently drifts if
that job is ever missed. Instead, usage is just a COUNT of the rows
(QueryRecord / GeneratedArtifact) already created since the start of the
current calendar month - always correct by construction, and "this
month" resets itself for free the moment the calendar turns over, no
reset logic to get wrong.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import QueryRecord, GeneratedArtifact


def _month_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def count_queries_this_month(db: Session, tenant_id: str) -> int:
    return (
        db.query(QueryRecord)
        .filter(QueryRecord.tenant_id == tenant_id, QueryRecord.created_at >= _month_start())
        .count()
    )


def count_documents_this_month(db: Session, tenant_id: str) -> int:
    """Every report/presentation/export GENERATED this month - not each
    time an already-generated file is re-downloaded, see plans.py's
    document_limit docstring for why generation is the metered unit."""
    return (
        db.query(GeneratedArtifact)
        .filter(GeneratedArtifact.tenant_id == tenant_id, GeneratedArtifact.created_at >= _month_start())
        .count()
    )
