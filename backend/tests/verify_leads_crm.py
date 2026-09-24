"""
Verification for the public "Register your interest" form, the leads CRM in
the internal console, the restricted sales role, and staff profiles.

Real SQLite + FastAPI TestClient. The only thing stubbed is the HTTP POST
to Google's Apps Script - everything else (throttling, de-duplication,
role enforcement, the comment trail) is the real code path.

Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_leads_crm.py
"""
import base64
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")
os.environ["LEADS_SHEET_WEBHOOK_URL"] = "https://script.google.test/exec"
os.environ["LEADS_SHEET_SHARED_SECRET"] = "sheet-secret"

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, init_db
from app.db.models import Lead, LeadComment, PlatformStaff
from app.security.auth import hash_password
from app.security.platform_auth import create_platform_access_token, path_allowed_for_staff_role
from app.leads import sheets
from app.api.routes_platform import VALID_STAFF_ROLES, STAFF_ROLES

init_db()
client = TestClient(app)
db = SessionLocal()


def staff(role: str, email: str) -> dict:
    s = PlatformStaff(email=email, password_hash=hash_password("supersecret1"), role=role)
    db.add(s)
    db.commit()
    return {"Authorization": f"Bearer {create_platform_access_token(s.id, s.role)}"}


def submit(ip: str, **fields):
    payload = {"full_name": "Ada Obi", "email": "ada@example.com", "phone": "08031234567", **fields}
    return client.post("/leads", json=payload, headers={"x-forwarded-for": ip})


# The sheet is stubbed at the HTTP boundary; everything above it is real.
pushed = []
fail_next = {"count": 0}


def fake_push(lead, client=None):
    if fail_next["count"] > 0:
        fail_next["count"] -= 1
        raise RuntimeError("HTTP 500: script error")
    pushed.append(lead.id)


sheets._push = fake_push

OWNER = staff("owner", "owner@meridian.test")
SALES = staff("sales", "sales@meridian.test")
SUPPORT = staff("support", "support@meridian.test")
SOCIAL = staff("social_media", "smm@meridian.test")


# --- 1. the public form stores a lead, with its campaign --------------------
r = submit("1.1.1.1", full_name="Ada Obi", business_name="Obi Logistics",
           message="Interested in the Pro plan", source="facebook", campaign="lagos-q4", consent=True)
assert r.status_code == 200 and r.json() == {"received": True}, r.text
lead = db.query(Lead).filter_by(email="ada@example.com").one()
assert (lead.full_name, lead.business_name, lead.phone) == ("Ada Obi", "Obi Logistics", "08031234567")
assert (lead.source, lead.campaign, lead.status) == ("facebook", "lagos-q4", "open")
assert lead.consented_at is not None
print("1. OK  a submission is stored with its name, business, phone, email, campaign and consent")


# --- 2. a bot that fills the hidden field is dropped silently ---------------
before = db.query(Lead).count()
r = submit("2.2.2.2", email="bot@example.com", company_website="http://spam.example")
assert r.status_code == 200 and r.json() == {"received": True}, r.text
assert db.query(Lead).count() == before, "a honeypot submission was stored"
print("2. OK  honeypot submission -> same 'thank you', nothing stored")


# --- 3. rubbish in the phone or email is refused ----------------------------
assert submit("3.3.3.3", email="not-an-email").status_code == 422
assert submit("3.3.3.3", email="x@example.com", phone="call me").status_code == 422
assert submit("3.3.3.3", email="y@example.com", phone="123").status_code == 422
print("3. OK  invalid email or phone -> refused")


# --- 4. the same person twice in a day is ONE lead --------------------------
before = db.query(Lead).count()
r = submit("4.4.4.4", business_name="Obi Logistics Ltd", message="Following up")
assert r.status_code == 200, r.text
assert db.query(Lead).count() == before, "a duplicate submission created a second lead"
db.expire_all()
lead = db.query(Lead).filter_by(email="ada@example.com").one()
assert lead.business_name == "Obi Logistics Ltd", "the newer details should win"
assert any("wrote in again" in c.body for c in db.query(LeadComment).filter_by(lead_id=lead.id))
print("4. OK  a repeat submission updates the same lead and records what they wrote")


# --- 5. the lead is stored even when the sheet fails, and retried ----------
db.expire_all()
lead = db.query(Lead).filter_by(email="ada@example.com").one()
lead.sheet_synced_at, lead.sheet_attempts, lead.sheet_sync_error = None, 0, None
db.commit()
fail_next["count"] = 1
sheets.sync_pending()
db.expire_all()
lead = db.query(Lead).filter_by(email="ada@example.com").one()
assert lead.sheet_synced_at is None and lead.sheet_attempts == 1
assert "script error" in (lead.sheet_sync_error or ""), lead.sheet_sync_error
sheets.sync_pending()                      # the retry succeeds
db.expire_all()
lead = db.query(Lead).filter_by(email="ada@example.com").one()
assert lead.sheet_synced_at is not None and lead.sheet_sync_error is None
assert lead.id in pushed
print("5. OK  a failing sheet never loses the lead: error recorded, then delivered on retry")


# --- 6. a permanently broken sheet stops being retried ---------------------
db.expire_all()
lead = db.query(Lead).filter_by(email="ada@example.com").one()
lead.sheet_synced_at, lead.sheet_attempts, lead.sheet_sync_error = None, 0, None
db.commit()
fail_next["count"] = 99
for _ in range(10):
    sheets.sync_pending()
db.expire_all()
lead = db.query(Lead).filter_by(email="ada@example.com").one()
assert lead.sheet_attempts == sheets.MAX_SHEET_ATTEMPTS, lead.sheet_attempts
fail_next["count"] = 0
print(f"6. OK  a sheet that never works is retried {sheets.MAX_SHEET_ATTEMPTS} times, then left alone")


# --- 7. the console lists leads, filters and searches them ------------------
r = client.get("/platform/leads", headers=SALES)
assert r.status_code == 200, r.text
rows = r.json()
assert rows and rows[0]["email"] == "ada@example.com"
assert rows[0]["phone"] == "08031234567" and rows[0]["business_name"] == "Obi Logistics Ltd"
assert client.get("/platform/leads?status=won", headers=SALES).json() == []
assert len(client.get("/platform/leads?search=Obi", headers=SALES).json()) == 1
assert client.get("/platform/leads?status=nonsense", headers=SALES).status_code == 400
print("7. OK  the console lists, filters by status and searches by name/business/email/phone")


# --- 8. status changes and notes are recorded, with who and when -----------
lead_id = rows[0]["id"]
r = client.patch(f"/platform/leads/{lead_id}", headers=SALES,
                 json={"status": "won", "note": "Spoke to Ada, signing next week."})
assert r.status_code == 200, r.text
out = r.json()
assert out["status"] == "won"
bodies = [(c["kind"], c["body"], c["staff_email"]) for c in out["comments"]]
assert any(k == "status" and "open to won" in b and e == "sales@meridian.test" for k, b, e in bodies), bodies
assert any(k == "note" and "Spoke to Ada" in b for k, b, _ in bodies), bodies
r = client.post(f"/platform/leads/{lead_id}/comments", headers=SALES, json={"body": "Called again, no answer."})
assert r.status_code == 200 and any("no answer" in c["body"] for c in r.json()["comments"])
assert client.patch(f"/platform/leads/{lead_id}", headers=SALES, json={"status": "maybe"}).status_code == 400
print("8. OK  status changes and notes are kept with the author, and a bad status is refused")


# --- 9. restricted roles see leads and their own profile, nothing else ---
for headers, who in [(SALES, "sales"), (SOCIAL, "social media manager")]:
    for path in ["/platform/leads", "/platform/tickets", "/platform/me"]:
        assert client.get(path, headers=headers).status_code == 200, (who, path)
    for path in ["/platform/tenants", "/platform/analytics", "/platform/audit",
                 "/platform/staff", "/platform/staff/roles", "/platform/health-snapshot", "/platform/incidents"]:
        assert client.get(path, headers=headers).status_code == 403, f"{who} reached {path}"
        assert client.get(path, headers=SUPPORT).status_code != 403, f"support was blocked from {path}"
print("9. OK  sales and social media see leads, tickets and their profile - and nothing else")


# --- 10. EVERY platform route is default-deny for a restricted role --------
#         Walks what is actually registered, so a route added later that
#         would leak customer data to sales fails this test rather than
#         shipping.
platform_paths = [p for p in app.openapi()["paths"] if p.startswith("/platform")]
for role in ("sales", "social_media"):
    reachable = sorted(p for p in platform_paths if path_allowed_for_staff_role(p, role))
    assert reachable == sorted([
        "/platform/leads", "/platform/leads/{lead_id}", "/platform/leads/{lead_id}/comments",
        "/platform/me", "/platform/me/profile",
        "/platform/tickets", "/platform/tickets/{ticket_id}", "/platform/tickets/{ticket_id}/messages",
    ]), (role, reachable)
assert len(platform_paths) - len(reachable) >= 15, "expected many owner/support-only routes"
print(f"10. OK  of {len(platform_paths)} console routes, a restricted role can reach exactly {len(reachable)}")


# --- 10b. the console's role dropdown is served, not hardcoded -------------
#          "sales" existed on the server for a day while the Staff page's
#          hardcoded <option> list didn't have it, so it couldn't be
#          assigned to anyone. One list now, served to the page.
served = client.get("/platform/staff/roles", headers=OWNER).json()
assert [r["key"] for r in served] == [r["key"] for r in STAFF_ROLES]
assert {r["key"] for r in served} == VALID_STAFF_ROLES, (served, VALID_STAFF_ROLES)
assert all(r["label"] and r["description"] for r in served), served
assert {"sales", "social_media"} <= {r["key"] for r in served}
print("10b. OK  every assignable role is served to the console, including sales and social media")


# --- 11. staff fill in their own profile, and only their own --------------
r = client.get("/platform/me", headers=SALES)
assert r.status_code == 200 and r.json()["complete"] is False, r.text
r = client.patch("/platform/me/profile", headers=SALES, json={
    "full_name": "Chidi Sales", "phone": "08090000000", "job_title": "Sales executive",
    "address": "12 Marina, Lagos", "emergency_contact_name": "Ngozi",
    "emergency_contact_phone": "08095555555",
})
assert r.status_code == 200, r.text
assert r.json()["complete"] is True and r.json()["full_name"] == "Chidi Sales"
assert client.patch("/platform/me/profile", headers=SALES, json={"full_name": "x"}).status_code == 422
db.expire_all()
assert db.query(PlatformStaff).filter_by(email="owner@meridian.test").one().full_name is None, \
    "one staff member's profile edit must not touch another's"
print("11. OK  a staff member fills in their own details; nobody else's row is touched")


# --- 12. the owner can see who is who, and can invite the new roles -------
assert {"sales", "social_media"} <= VALID_STAFF_ROLES
listing = {s["email"]: s for s in client.get("/platform/staff", headers=OWNER).json()}
assert listing["sales@meridian.test"]["full_name"] == "Chidi Sales"
assert listing["sales@meridian.test"]["job_title"] == "Sales executive"
assert listing["owner@meridian.test"]["full_name"] is None
print("12. OK  the owner's staff list shows each person's own details, and 'sales' is an invitable role")


# --- 13. the public form is throttled per IP -------------------------------
codes = [submit("9.9.9.9", email=f"flood{i}@example.com").status_code for i in range(15)]
assert 429 in codes, codes
assert codes.count(200) <= 12, codes
print(f"13. OK  the public form is capped per IP ({codes.count(200)} accepted, then 429)")

# --- 14. closing a lead is final ------------------------------------------
r = client.post("/leads", json={"full_name": "Final Test", "email": "final@example.com",
                                "phone": "08012349999"}, headers={"x-forwarded-for": "14.14.14.14"})
assert r.status_code == 200, r.text
lead_id = [l for l in client.get("/platform/leads", headers=SALES).json()
           if l["email"] == "final@example.com"][0]["id"]
assert client.patch(f"/platform/leads/{lead_id}", headers=SALES, json={"status": "closed"}).status_code == 200
for attempt in ("open", "won", "not_interested"):
    r = client.patch(f"/platform/leads/{lead_id}", headers=SALES, json={"status": attempt})
    assert r.status_code == 400 and "can't be reopened" in r.json()["detail"], (attempt, r.text)
db.expire_all()
assert db.query(Lead).filter_by(id=lead_id).one().status == "closed"
# Re-closing is not an error, and notes can still be added afterwards.
assert client.patch(f"/platform/leads/{lead_id}", headers=SALES, json={"status": "closed"}).status_code == 200
assert client.post(f"/platform/leads/{lead_id}/comments", headers=SALES,
                   json={"body": "Filed away."}).status_code == 200
print("14. OK  a closed lead cannot be reopened, but can still be annotated")


# --- 15. a closed lead who writes in again becomes a NEW lead -------------
before = db.query(Lead).filter_by(email="final@example.com").count()
r = client.post("/leads", json={"full_name": "Final Test", "email": "final@example.com",
                                "phone": "08012349999", "message": "Changed my mind"},
                headers={"x-forwarded-for": "15.15.15.15"})
assert r.status_code == 200, r.text
db.expire_all()
rows = db.query(Lead).filter_by(email="final@example.com").order_by(Lead.created_at).all()
assert len(rows) == before + 1, "a closed lead should not be silently reopened by a new enquiry"
assert rows[0].status == "closed" and rows[-1].status == "open"
print("15. OK  someone who was closed off and writes in again arrives as a new, open lead")

# --- 16. a new enquiry emails the enquiries inbox --------------------------
# The whole point of the feature: Joel finds out someone wrote in without
# having to remember to open the console.
from app.agents import notifications
from app.config import settings

sent = []
notifications._send_best_effort = lambda to, subject, body: sent.append((to, subject, body))
settings.leads_notification_email = "hello@getmeridiananalytics.test"

sent.clear()
r = submit("16.16.16.16", full_name="Chidi Nwosu", email="chidi@example.com",
           business_name="Nwosu Foods", phone="08055512345",
           message="We need weekly sales answers.", source="facebook",
           campaign="lagos-q4", consent=True)
assert r.status_code == 200, r.text
assert len(sent) == 1, f"expected exactly one email, got {len(sent)}"
to, subject, body = sent[0]
assert to == "hello@getmeridiananalytics.test", to
assert subject == "New enquiry: Chidi Nwosu (Nwosu Foods)", subject
for expected in ("Chidi Nwosu", "Nwosu Foods", "08055512345", "chidi@example.com",
                 "facebook / lagos-q4", "We need weekly sales answers.", "/platform/leads"):
    assert expected in body, (expected, body)
print("1" + "6. OK  a new enquiry emails the inbox with the name, number, campaign and a link")


# --- 17. a bot submission emails nobody ------------------------------------
sent.clear()
r = submit("17.17.17.17", email="bot17@example.com", company_website="http://spam.example")
assert r.status_code == 200, r.text
assert sent == [], f"a honeypot submission sent mail: {sent}"
print("17. OK  a honeypot submission emails nobody")


# --- 18. a same-day follow-up is flagged as a follow-up --------------------
sent.clear()
r = submit("18.18.18.18", full_name="Chidi Nwosu", email="chidi@example.com",
           phone="08055512345", message="Following up on this.")
assert r.status_code == 200, r.text
assert len(sent) == 1, sent
assert sent[0][1].startswith("Enquiry follow-up:"), sent[0][1]
assert "wrote in again" in sent[0][2], sent[0][2]
print("18. OK  someone writing in twice the same day is emailed as a follow-up, not a new lead")


# --- 19. a broken mail server never costs a lead ---------------------------
# This is the one that matters. Email is best-effort; lead capture is not.
def explode(*_args, **_kwargs):
    raise RuntimeError("SMTP authentication failed")

notifications._send_best_effort = explode
before = db.query(Lead).count()
r = submit("19.19.19.19", full_name="Amina Bello", email="amina@example.com",
           phone="08066612345")
assert r.status_code == 200, r.text
db.expire_all()
assert db.query(Lead).count() == before + 1, "a failing mail server lost the lead"
assert db.query(Lead).filter_by(email="amina@example.com").one().full_name == "Amina Bello"
print("19. OK  a mail server that refuses to send never stops a lead being captured")


# --- 20. the emails can be switched off entirely ---------------------------
sent.clear()
notifications._send_best_effort = lambda to, subject, body: sent.append((to, subject, body))
settings.leads_notification_email = ""
r = submit("20.20.20.20", full_name="Tunde Ade", email="tunde@example.com", phone="08077712345")
assert r.status_code == 200, r.text
assert sent == [], f"emails were sent with no recipient configured: {sent}"
db.expire_all()
assert db.query(Lead).filter_by(email="tunde@example.com").count() == 1
settings.leads_notification_email = "hello@getmeridiananalytics.test"
print("20. OK  clearing the address switches the emails off without affecting capture")


db.close()
print("\nALL LEADS CRM CHECKS PASSED")
