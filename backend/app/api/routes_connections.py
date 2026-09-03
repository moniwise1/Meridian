"""
Data source connection management (BUILD SPEC sections 4, 6, 8).

Registering a connection immediately runs verify_read_only() and refuses to
save the connection if the credential can mutate data. tenant_id/user_id
are taken from the verified auth token, never from the request body.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import DataSourceConnection
from app.security.secrets import encrypt, RedactedSecret
from app.security.auth import get_current_user, require_role, require_active_subscription, AuthContext
from app.connectors.postgres import PostgresConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.mssql import MSSQLConnector
from app.audit import logger as audit

router = APIRouter(prefix="/connections", tags=["connections"])

_CONNECTOR_CLASSES = {"postgres": PostgresConnector, "mysql": MySQLConnector, "mssql": MSSQLConnector}


class ConnectionCreate(BaseModel):
    name: str
    kind: str = Field(default="postgres")
    host: str
    port: int = 5432
    database: str
    username: str
    password: str
    table_allowlist: list[str] = []
    column_policy: dict[str, list[str]] = {}


class ConnectionOut(BaseModel):
    id: str
    name: str
    kind: str
    host: str
    database: str
    verified_read_only: bool
    table_allowlist: list[str]
    column_policy: dict[str, list[str]]

    class Config:
        from_attributes = True


@router.post("", response_model=ConnectionOut)
def create_connection(body: ConnectionCreate, db: Session = Depends(get_db),
                       ctx: AuthContext = Depends(require_role("admin")),
                       _billing: AuthContext = Depends(require_active_subscription)):
    connector_cls = _CONNECTOR_CLASSES.get(body.kind)
    if connector_cls is None:
        raise HTTPException(400, f"Unsupported connector kind '{body.kind}'. "
                                  f"Supported: {', '.join(_CONNECTOR_CLASSES)}.")

    connector = connector_cls(
        host=body.host, port=body.port, database=body.database,
        username=body.username, password=RedactedSecret(body.password),
    )
    if not connector.test_connection():
        raise HTTPException(400, "Could not connect with the supplied credentials.")

    if not connector.verify_read_only():
        audit.log(db, ctx.tenant_id, "connection_rejected_not_readonly", ctx.user_id,
                   detail={"host": body.host, "database": body.database}, status="denied")
        raise HTTPException(
            400,
            "This credential can mutate data. Create a SELECT-only database role "
            "and connect with that instead (see README for the recommended GRANT statements).",
        )

    row = DataSourceConnection(
        tenant_id=ctx.tenant_id, name=body.name, kind=body.kind, host=body.host,
        port=body.port, database=body.database, username=body.username,
        encrypted_password=encrypt(body.password),
        table_allowlist=body.table_allowlist, column_policy=body.column_policy,
        verified_read_only=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    audit.log(db, ctx.tenant_id, "connection_created", ctx.user_id, connection_id=row.id,
               detail={"host": body.host, "database": body.database, "kind": body.kind})
    return row


@router.get("", response_model=list[ConnectionOut])
def list_connections(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return db.query(DataSourceConnection).filter_by(tenant_id=ctx.tenant_id).all()


class PolicyUpdate(BaseModel):
    table_allowlist: list[str] | None = None
    column_policy: dict[str, list[str]] | None = None


@router.patch("/{connection_id}/policy", response_model=ConnectionOut)
def update_policy(connection_id: str, body: PolicyUpdate, db: Session = Depends(get_db),
                   ctx: AuthContext = Depends(require_role("admin"))):
    row = db.query(DataSourceConnection).filter_by(id=connection_id, tenant_id=ctx.tenant_id).first()
    if not row:
        raise HTTPException(404, "Connection not found.")
    if body.table_allowlist is not None:
        row.table_allowlist = body.table_allowlist
    if body.column_policy is not None:
        row.column_policy = body.column_policy
    db.commit()
    db.refresh(row)
    audit.log(db, ctx.tenant_id, "connection_policy_updated", ctx.user_id, connection_id=row.id)
    return row
