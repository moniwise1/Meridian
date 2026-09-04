"""
Externally-anchored audit checkpoints - the specific gap
`app/audit/logger.py`'s own docstring calls out as unfixed: the hash
chain there is tamper-*evident*, not tamper-*proof*, precisely because
its hashes live in the same database they protect. Someone with DB write
access and knowledge of that module could delete every row, insert a
brand-new internally-self-consistent fabricated chain from a fresh
genesis, and `verify_chain()` would report `intact: True` - a completely
different, fabricated history that's perfectly consistent *with itself*.

This module is the fix that requires an anchor genuinely outside this
database: periodically compute a single root hash over every tenant's
current chain head and publish it to a GitHub repo via the Contents API -
a system this app has no write access to except through an explicit
token, and whose own commit history is a second, independent hash chain
(git's) that nobody at this company controls unilaterally the way they'd
control this app's own Postgres instance. A checkpoint published last
week can't be un-published; a fabricated chain built today can't
retroactively produce last week's anchored hash.

Verification is the second half: given a previously-published checkpoint,
check whether the hash it anchored for a tenant still appears anywhere in
that tenant's CURRENT chain. `verify_chain()` alone can't distinguish "an
untouched chain" from "a fabricated-but-self-consistent replacement
chain" - both report intact. Checking for the anchored hash's literal
presence is what closes that gap: a replacement chain built from a
different history will never happen to contain the exact same hash at
the exact same point, since the hash covers that entry's full content
including a timestamp with second-level uncertainty across every prior
entry.

Deliberately admin-triggered (`POST /platform/audit/checkpoint`), not an
automatic background timer - this app has no job scheduler. Pair it with
an external cron (a scheduled GitHub Action, a Railway cron service,
anything that can call an HTTP endpoint on a schedule) for genuinely
periodic anchoring; calling it by hand from the platform admin panel
works too, just less regularly.

Writes go to a dedicated branch (`AUDIT_ANCHOR_GITHUB_BRANCH`, default
"audit-checkpoints"), created automatically from the repo's default
branch tip on first publish - deliberately NOT the default branch itself.
Checkpoint commits have nothing to do with code history, and a repo with
PR-required branch protection on its default branch (this one included -
`enforce_admins: true`, discovered live while building this, not assumed)
rejects a direct Contents API write there with a 409 regardless of the
token's own permissions. A dedicated branch sidesteps that cleanly rather
than asking anyone to carve out a branch-protection exception for one
specific file path.

Honesty note, same norm as this codebase's other "no live account here"
integrations: the GitHub Contents API calls are implemented strictly to
GitHub's documented REST API contract and were exercised against this
very repository during development (see the PR that shipped this
feature for a real commit it produced) - not mocked, but also not yet
exercised against a repo other than this one, and the "does the anchored
hash survive a real fabricated-chain rewrite" property has been verified
by deliberately constructing a fabricated replacement chain in a test
database and confirming `verify_checkpoint` correctly flags it, not by
staging a real DB compromise.
"""
import base64
import hashlib
import json
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuditLog
from app.audit.logger import verify_chain

_GITHUB_API = "https://api.github.com"


class AnchorNotConfigured(Exception):
    pass


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_checkpoint(db: Session) -> dict:
    """The current head (latest entry_hash) of every tenant's chain, plus
    a single root hash over all of them - one value to anchor instead of
    one per tenant, same idea as a Merkle root."""
    tenant_ids = sorted({row[0] for row in db.query(AuditLog.tenant_id).distinct().all()})
    heads: dict[str, str] = {}
    for tenant_id in tenant_ids:
        latest = (
            db.query(AuditLog)
            .filter_by(tenant_id=tenant_id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        if latest:
            heads[tenant_id] = latest.entry_hash
    root_hash = hashlib.sha256(_canonical(heads).encode()).hexdigest()
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "root_hash": root_hash,
        "tenant_heads": heads,
    }


def _require_configured() -> None:
    if not (settings.audit_anchor_github_token and settings.audit_anchor_github_repo):
        raise AnchorNotConfigured(
            "External anchoring isn't configured - set AUDIT_ANCHOR_GITHUB_TOKEN and "
            "AUDIT_ANCHOR_GITHUB_REPO to enable it."
        )


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.audit_anchor_github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _contents_url() -> str:
    return f"{_GITHUB_API}/repos/{settings.audit_anchor_github_repo}/contents/{settings.audit_anchor_github_path}"


def _repo_url() -> str:
    return f"{_GITHUB_API}/repos/{settings.audit_anchor_github_repo}"


def _ensure_branch_exists(client: httpx.Client) -> None:
    """Creates the anchor branch from the repo's default branch tip if it
    doesn't exist yet. Needed because the Contents API's `branch` param
    only ever writes to an EXISTING branch - it never creates one, so the
    very first publish against a fresh repo would otherwise 404."""
    branch = settings.audit_anchor_github_branch
    check = client.get(f"{_GITHUB_API}/repos/{settings.audit_anchor_github_repo}/branches/{branch}",
                        headers=_github_headers())
    if check.status_code == 200:
        return
    repo = client.get(_repo_url(), headers=_github_headers())
    repo.raise_for_status()
    default_branch = repo.json()["default_branch"]
    default_ref = client.get(
        f"{_GITHUB_API}/repos/{settings.audit_anchor_github_repo}/git/ref/heads/{default_branch}",
        headers=_github_headers(),
    )
    default_ref.raise_for_status()
    tip_sha = default_ref.json()["object"]["sha"]
    create = client.post(
        f"{_GITHUB_API}/repos/{settings.audit_anchor_github_repo}/git/refs",
        headers=_github_headers(),
        json={"ref": f"refs/heads/{branch}", "sha": tip_sha},
    )
    create.raise_for_status()


def publish_checkpoint(db: Session) -> dict:
    """Appends one JSONL line to the anchor file (creating it, and the
    dedicated anchor branch, on the first call) via GitHub's Contents API
    - a real commit, real history, real external system this app can
    append to but never rewrite the past of."""
    _require_configured()
    checkpoint = compute_checkpoint(db)
    branch = settings.audit_anchor_github_branch

    with httpx.Client(timeout=15) as client:
        _ensure_branch_exists(client)

        existing = client.get(_contents_url(), headers=_github_headers(), params={"ref": branch})
        if existing.status_code == 200:
            existing_body = existing.json()
            existing_content = base64.b64decode(existing_body["content"]).decode()
            sha = existing_body["sha"]
        elif existing.status_code == 404:
            existing_content = ""
            sha = None
        else:
            existing.raise_for_status()
            existing_content, sha = "", None  # unreachable, satisfies type checkers

        new_content = existing_content
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"
        new_content += _canonical(checkpoint) + "\n"

        payload = {
            "message": f"Audit checkpoint {checkpoint['generated_at']} (root {checkpoint['root_hash'][:12]}…)",
            "content": base64.b64encode(new_content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        resp = client.put(_contents_url(), headers=_github_headers(), json=payload)
        resp.raise_for_status()
        commit = resp.json().get("commit", {})

    return {
        "checkpoint": checkpoint,
        "commit_sha": commit.get("sha"),
        "commit_url": commit.get("html_url"),
    }


def fetch_latest_checkpoint() -> dict | None:
    """Reads the anchor file back from GitHub and returns the most recent
    checkpoint line - lets /platform/audit/checkpoint/verify work off
    "whatever was last published" without the caller needing to paste a
    checkpoint payload in by hand. Returns None if nothing's been
    published yet (or anchoring isn't configured)."""
    _require_configured()
    with httpx.Client(timeout=15) as client:
        resp = client.get(_contents_url(), headers=_github_headers(),
                           params={"ref": settings.audit_anchor_github_branch})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    content = base64.b64decode(resp.json()["content"]).decode()
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


def verify_checkpoint(db: Session, checkpoint: dict) -> dict:
    """For each tenant anchored in `checkpoint`: is that exact head hash
    still present in the tenant's CURRENT chain, and is that current
    chain still internally self-consistent? Both together prove the
    history up to the anchored point hasn't been rewritten - see the
    module docstring for why checking hash presence (not just
    verify_chain's own intact/broken result) is the part that actually
    catches a full fabricated-chain replacement."""
    results = {}
    all_verified = True
    for tenant_id, anchored_hash in checkpoint.get("tenant_heads", {}).items():
        chain_state = verify_chain(db, tenant_id)
        hash_present = (
            db.query(AuditLog).filter_by(tenant_id=tenant_id, entry_hash=anchored_hash).first()
            is not None
        )
        tenant_ok = chain_state["intact"] and hash_present
        all_verified = all_verified and tenant_ok
        results[tenant_id] = {
            "anchored_hash_still_present": hash_present,
            "current_chain_intact": chain_state["intact"],
            "verified": tenant_ok,
        }
    return {"verified": all_verified, "checkpoint": checkpoint, "tenants": results}
