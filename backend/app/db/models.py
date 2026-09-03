"""
The application's OWN metadata store. This is a completely separate
database from any customer data source — it holds tenants, users,
connection registrations (credentials encrypted), access policy, and the
audit log. Never confuse this with a customer's connected database.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, JSON, Integer, Boolean, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    connections = relationship("DataSourceConnection", back_populates="tenant")


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="analyst")  # admin/analyst/manager/executive/viewer
    # Row-level scope, e.g. {"region": ["South-East"]}. Empty dict = unrestricted (e.g. CEO/admin).
    row_scope = Column(JSON, default=dict)
    # AI capabilities this user is permitted to invoke (BUILD SPEC section 6).
    capabilities = Column(JSON, default=lambda: [
        "querying", "document_retrieval", "statistical_analysis",
        "anomaly_detection", "report_generation", "presentation_generation",
        "email_delivery",
    ])


class DataSourceConnection(Base):
    __tablename__ = "data_source_connections"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # "postgres", "mysql", "mssql", ...
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    database = Column(String, nullable=False)
    username = Column(String, nullable=False)
    encrypted_password = Column(Text, nullable=False)
    # Column allowlist per table: {"sales": ["region","product","revenue","month"]}
    column_policy = Column(JSON, default=dict)
    # Tables the AI is permitted to discover/query at all.
    table_allowlist = Column(JSON, default=list)
    verified_read_only = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="connections")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    action = Column(String, nullable=False)  # e.g. "query_executed", "connection_created"
    connection_id = Column(String, nullable=True)
    query_id = Column(String, nullable=True)
    detail = Column(JSON, default=dict)  # never raw sensitive data, see audit/logger.py
    status = Column(String, default="ok")  # ok / denied / error
    # Hash chain (tamper-evidence, not tamper-proofing — see audit/logger.py):
    # each row's hash covers its own fields plus the previous row's hash, so
    # editing or deleting a row breaks every hash after it in the chain.
    prev_hash = Column(String, nullable=False, default="")
    entry_hash = Column(String, nullable=False, default="")


class QueryRecord(Base):
    __tablename__ = "query_records"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    connection_id = Column(String, nullable=False)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=True)
    question = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=False)
    row_count = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    result_snapshot = Column(JSON, default=dict)  # full result payload (metrics/insight/by_group/anomalies/
                                                    # investigation/preview_rows/data_quality) so Reports,
                                                    # Analyses history, and exports can render without re-querying
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """
    Holds analytical context across follow-up questions (BUILD SPEC section
    18). `context` carries only structural facts the next question might
    reference (table, dimensions, filters, top groups) - never raw row data,
    keeping it safe to replay into a prompt.
    """
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    connection_id = Column(String, nullable=False)
    context = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class GeneratedArtifact(Base):
    """A generated report or presentation, tied back to the query record(s)
    it was built from (BUILD SPEC sections 24, 22)."""
    __tablename__ = "generated_artifacts"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    kind = Column(String, nullable=False)  # "report_pdf" | "presentation_pptx" | "export_csv" | "export_xlsx"
    title = Column(String, nullable=False)
    source_query_id = Column(String, nullable=True)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class UploadedDocument(Base):
    """A user-uploaded PDF/DOCX/XLSX (BUILD SPEC section 19 - document
    intelligence). `extracted_text` is what actually gets referenced by an
    analysis (app/agents/document_intelligence.py) - never the raw file
    bytes, which stay on disk under settings.documents_dir purely so the
    original can be re-downloaded, not because anything re-parses it."""
    __tablename__ = "uploaded_documents"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    filename = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # "pdf" | "docx" | "xlsx"
    file_path = Column(String, nullable=False)
    extracted_text = Column(Text, nullable=False, default="")
    extraction_truncated = Column(Boolean, default=False)
    char_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailDeliveryLog(Base):
    """Every send attempt, approved or blocked (BUILD SPEC section 23) -
    email is a data-exfiltration boundary and gets its own audit trail."""
    __tablename__ = "email_delivery_log"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    recipient = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    artifact_id = Column(String, nullable=True)
    status = Column(String, nullable=False)  # "sent" | "blocked" | "pending_confirmation"
    reason = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
