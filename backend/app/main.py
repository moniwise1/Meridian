from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from app.config import settings
from app.db.session import init_db
from app.api import (
    routes_connections, routes_ask, routes_audit, routes_auth, routes_artifacts,
    routes_history, routes_scan, routes_documents, routes_billing,
    routes_platform, routes_support, routes_status, routes_mfa, routes_monitor,
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
app.include_router(routes_monitor.router)

# Generated reports/presentations/exports are served ONLY through the
# authenticated GET /artifacts/file/{id} route in routes_artifacts.py
# (signed short-lived token, one artifact per token, minted after a
# tenant-ownership check). There is deliberately no StaticFiles mount:
# the old one had no auth at all, so any generated report was readable by
# anyone who guessed its 8-hex-char filename. Object storage + signed URLs
# is still the right production end state; this closes the hole without
# it. The files themselves live under settings.artifacts_dir on the
# server's own disk and are never in the web root.
