from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.config import settings
from app.db.session import init_db
from app.api import (
    routes_connections, routes_ask, routes_audit, routes_auth, routes_artifacts,
    routes_history, routes_scan, routes_documents, routes_billing,
    routes_platform, routes_support, routes_status, routes_mfa,
)

app = FastAPI(title="Secure AI Enterprise Analytics Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    # Matches any per-tenant subdomain (settings.frontend_origins alone
    # can't, since those are created dynamically - see the setting's own
    # docstring). None when unset rather than "" - Starlette's
    # CORSMiddleware only skips regex matching entirely when this is
    # exactly None (checked via `is not None`); an empty string would
    # still get compiled and checked via fullmatch(), which happens to be
    # harmless (an empty pattern only fullmatches an empty origin, never
    # a real one - verified, not assumed) but there's no reason to compile
    # and check a regex on every request when the feature is simply unused.
    allow_origin_regex=settings.frontend_origin_regex or None,
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
app.include_router(routes_mfa.router)
app.include_router(routes_connections.router)
app.include_router(routes_ask.router)
app.include_router(routes_audit.router)
app.include_router(routes_artifacts.router)
app.include_router(routes_history.router)
app.include_router(routes_scan.router)
app.include_router(routes_documents.router)
app.include_router(routes_billing.router)
app.include_router(routes_platform.router)
app.include_router(routes_support.router)
app.include_router(routes_status.router)

# Generated reports/presentations/exports. In production these should be
# short-lived signed URLs from object storage (S3/GCS) behind the same
# tenant-authorization check as everything else, not a public static mount -
# this local mount is an MVP stand-in, called out in the README.
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")
