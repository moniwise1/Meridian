"""
Subdomain generation for tenants (BUILD SPEC: per-enterprise subdomains -
wamco.getmeridiananalytics.com). A tenant's subdomain is a real functional
boundary (see app/api/routes_auth.py's login()), not just decoration, so
it has to be unique and never collide with a real app route.
"""
import re
from sqlalchemy.orm import Session

# Never let a tenant claim a subdomain that collides with a real route or
# a reserved/expected hostname - "www" would be the most confusing
# possible outcome (a tenant named "Www" locking out the marketing site).
RESERVED_SUBDOMAINS = {
    "www", "api", "app", "admin", "platform", "mail", "ftp", "smtp",
    "status", "docs", "support", "billing", "security", "auth", "login",
    "staging", "dev", "test", "assets", "static", "cdn", "blog",
}

DEFAULT_SLUG = "workspace"


def slugify_company_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or DEFAULT_SLUG


def generate_unique_subdomain(db: Session, company_name: str) -> str:
    """Deterministic-first, collision-resolved-after: "Wamco Inc" ->
    "wamco-inc", or "wamco-inc2", "wamco-inc3", ... if already taken.
    Imported lazily to avoid a circular import with app.db.models."""
    from app.db.models import Tenant

    base = slugify_company_name(company_name)
    if base in RESERVED_SUBDOMAINS:
        base = f"{base}-co"

    candidate = base
    n = 2
    while db.query(Tenant).filter_by(subdomain=candidate).first() is not None:
        candidate = f"{base}{n}"
        n += 1
    return candidate
