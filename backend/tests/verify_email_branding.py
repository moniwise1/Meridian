"""
Throwaway verification for the real-logo-image header in outbound HTML
emails (backend/app/agents/email_delivery.py's _render_html_email),
replacing the earlier CSS text badge. Checks both the template function
in isolation and the real SmtpEmailBackend send path (smtplib.SMTP
monkeypatched, same convention verify_billing_binding.py uses for
Paystack - no live SMTP credentials in this environment).
Run from backend/:  PYTHONPATH=$(pwd) python tests/verify_email_branding.py
"""
import base64, os, tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("APP_SECRET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ["METADATA_DB_URL"] = f"sqlite:///{os.path.join(_tmp, 'meta.db')}"
os.environ["ARTIFACTS_DIR"] = os.path.join(_tmp, "artifacts")
os.environ["DOCUMENTS_DIR"] = os.path.join(_tmp, "documents")

from app.agents import email_delivery
from app.agents.email_delivery import _render_html_email, SmtpEmailBackend, _BRAND_LOGO_URL

# --- 1. the rendered HTML shell carries the real logo image, not the old
#        text badge ---
html = _render_html_email("Hello there.\n\nSecond paragraph.")
assert _BRAND_LOGO_URL in html, html
assert 'alt="Meridian"' in html, html
assert "MERIDIAN</span>" not in html  # the old CSS badge is gone
print("1. OK  rendered email shell embeds the real logo <img>, not the old text badge")

# --- 2. width/height are set explicitly (reserves layout space when the
#        image is blocked, rather than collapsing to nothing) ---
assert 'width="170"' in html and 'height="41"' in html, html
print("2. OK  logo <img> carries explicit width/height")

# --- 3. the real SmtpEmailBackend send path embeds it too - not just the
#        template function in isolation ---
sent = {}


class _FakeSmtp:
    def __init__(self, host, port, timeout=10):
        sent["connected"] = (host, port)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        sent["starttls"] = True

    def login(self, user, pw):
        sent["login"] = (user, pw)

    def send_message(self, message):
        sent["message"] = message


email_delivery.smtplib.SMTP = _FakeSmtp
backend = SmtpEmailBackend(
    host="smtp.example.com", port=587, username="hello@example.com",
    password="app-password", from_address="hello@getmeridiananalytics.example.com", use_tls=True,
)
backend.send("someone@example.com", "Welcome", "Hi there,\n\nWelcome aboard.", None)
msg = sent["message"]
html_part = next(p for p in msg.walk() if p.get_content_type() == "text/html")
html_body = html_part.get_content()
assert _BRAND_LOGO_URL in html_body, html_body
plain_part = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
assert "<img" not in plain_part.get_content()  # plain-text part stays plain
print("3. OK  real SmtpEmailBackend send embeds the logo in the HTML alternative, plain part untouched")

print("\nALL CHECKS PASSED")
