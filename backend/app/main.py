from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.config import settings
from app.db.session import init_db
from app.api import (
    routes_connections, routes_ask, routes_audit, routes_auth, routes_artifacts,
    routes_history, routes_scan, routes_documents, routes_billing,
)

app = FastAPI(title="Secure AI Enterprise Analytics Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


os.makedirs(settings.artifacts_dir, exist_ok=True)
os.makedirs(settings.documents_dir, exist_ok=True)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(routes_auth.router)
app.include_router(routes_connections.router)
app.include_router(routes_ask.router)
app.include_router(routes_audit.router)
app.include_router(routes_artifacts.router)
app.include_router(routes_history.router)
app.include_router(routes_scan.router)
app.include_router(routes_documents.router)
app.include_router(routes_billing.router)

# Generated reports/presentations/exports. In production these should be
# short-lived signed URLs from object storage (S3/GCS) behind the same
# tenant-authorization check as everything else, not a public static mount -
# this local mount is an MVP stand-in, called out in the README.
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")
