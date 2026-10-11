"""Live cutover, validation, persistent duplicate protection and expiry."""
import os, tempfile, base64, json, hashlib, hmac
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
p=tempfile.mkdtemp()
os.environ.update(APP_SECRET_KEY=base64.urlsafe_b64encode(b'0'*32).decode(), METADATA_DB_URL=f'sqlite:///{p}/meta.db', PAYSTACK_SECRET_KEY='sk_live_fake', PAYSTACK_PUBLIC_KEY='pk_live_fake', PAYSTACK_PLAN_CODE_BASIC='PLN_basic', BILLING_MODE='live', ARTIFACTS_DIR=f'{p}/artifacts', DOCUMENTS_DIR=f'{p}/docs')
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import text, inspect
from app.main import app
from app.db.session import init_db, SessionLocal, engine
from app.db.models import Tenant, User, BillingPayment
from app.config import settings
from app.billing.mode import validate_billing_config
from app.billing import paystack
from app.security.auth import create_access_token, require_active_subscription, AuthContext
init_db()
with engine.begin() as c: c.execute(text('ALTER TABLE tenants DROP COLUMN payment_mode'))
init_db()
assert 'payment_mode' in {c['name'] for c in inspect(engine).get_columns('tenants')}
client=TestClient(app); db=SessionLocal(); count=[0]
def initialize(*a,**k):
 count[0]+=1
 return {'reference':f'live-{count[0]}','authorization_url':'https://checkout.paystack.com/mock'}
paystack.initialize_subscription_transaction=initialize

def account():
 t=Tenant(name='Live');db.add(t);db.flush()
 u=User(tenant_id=t.id,email=f'{t.id}@example.com',role='admin',password_hash='unused');db.add(u);db.commit()
 h={'Authorization':f'Bearer {create_access_token(u.id,t.id,u.role)}'}
 result=client.post('/billing/subscribe',headers=h,json={'plan':'basic','callback_url':'https://app.test/billing/callback'})
 assert result.status_code==200,result.text
 d={'reference':result.json()['reference'],'domain':'live','status':'success','currency':'NGN','amount':750000,'paid_at':datetime.now(timezone.utc).isoformat(),'plan':{'plan_code':'PLN_basic'},'customer':{'customer_code':f'CUS_{t.id}'},'metadata':{'tenant_id':t.id}}
 return t,u,h,d

def verify(h,d):
 paystack.verify_transaction=lambda *a,**k:dict(d)
 return client.get('/billing/verify',params={'reference':d['reference']},headers=h)
def webhook(d):
 body=json.dumps({'event':'charge.success','data':d}).encode()
 signature=hmac.new(settings.paystack_secret_key.encode(),body,hashlib.sha512).hexdigest()
 return client.post('/billing/webhook',content=body,headers={'x-paystack-signature':signature,'content-type':'application/json'})
for k,v in [('domain','test'),('amount',749999),('currency','USD'),('status','failed'),('paid_at',None),('plan',{'plan_code':'PLN_wrong'})]:
 t,u,h,d=account();bad={**d,k:v}
 assert verify(h,bad).status_code==400,k
 assert webhook(bad).status_code==400,k
 db.expire_all();assert db.get(Tenant,t.id).subscription_status=='pending'
 assert db.get(BillingPayment,d['reference']).applied_at is None
print('PASS mode, amount, currency, status, date and plan rejected on verify and webhook')
t,u,h,d=account();assert verify(h,d).status_code==200
with SessionLocal() as check:
 expiry=check.get(Tenant,t.id).subscription_expires_at
 assert check.get(Tenant,t.id).payment_mode=='live'
 assert check.get(BillingPayment,d['reference']).applied_at
assert webhook(d).status_code==200
assert verify(h,d).status_code==200
db.expire_all();assert t.subscription_expires_at==expiry
t.subscription_status='cancelled';t.subscription_expires_at=None;db.commit()
assert webhook(d).status_code==200
db.expire_all();assert t.subscription_status=='cancelled' and t.subscription_expires_at is None
print('PASS persisted duplicate detection and replay after cancellation')
t.subscription_status='active';t.subscription_expires_at=expiry;db.commit()
old=settings.paystack_plan_amount_basic;settings.paystack_plan_amount_basic=900000
renewal={**d,'reference':'renewal','paid_at':(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()}
assert webhook(renewal).status_code==200
settings.paystack_plan_amount_basic=old
db.expire_all();renewal_expiry=t.subscription_expires_at
assert webhook(d).status_code==200
db.expire_all();assert t.subscription_expires_at==renewal_expiry
print('PASS renewal retains original price and replay leaves renewal unchanged')
ctx=AuthContext(user_id=u.id,tenant_id=t.id,role='admin')
for mode,expiry_date in [('live',datetime.utcnow()-timedelta(seconds=1)),('test',datetime.utcnow()+timedelta(days=10))]:
 db.expire_all()
 t.subscription_status='active';t.payment_mode=mode;t.subscription_expires_at=expiry_date;db.commit()
 try: require_active_subscription(ctx=ctx,db=db);raise AssertionError('access allowed')
 except HTTPException as e: assert e.status_code==402
 assert client.get('/billing/status',headers=h).json()['subscription_status']==('expired' if mode=='live' else 'payment_required')
 result=client.post('/billing/subscribe',headers=h,json={'plan':'basic','callback_url':'https://app.test'})
 assert result.status_code==200,result.text
print('PASS expired and test-mode access refused; fresh checkout allowed')
s=SimpleNamespace(environment='development',kms_provider='local',billing_mode='live',paystack_secret_key='sk_test_fake',paystack_public_key='pk_live_fake',billing_currency='NGN')
assert validate_billing_config(s)
s.paystack_secret_key='sk_live_fake';assert not validate_billing_config(s)
s.environment='production';s.billing_mode='test';assert validate_billing_config(s)
assert client.get('/billing/config').json()=={'mode':'live','currency':'NGN','configured':True}
print('PASS config and public mode diagnostics; no credentials exposed')
import httpx
requests=[]
def transport(req):
 requests.append(req)
 return httpx.Response(200,json={'status':True,'data':{'reference':'mock'}})
with httpx.Client(transport=httpx.MockTransport(transport)) as c:
 paystack.initialize_transfer_transaction('a@example.com',750000,'https://app.test',client=c)
assert requests[0].headers['authorization']=='Bearer sk_live_fake'
assert json.loads(requests[0].content)['currency']=='NGN'
print('PASS live credential and explicit currency sent without real payment')
# Cutover: a long test subscription must not suppress a shorter live period.
t,u,h,d=account();t.payment_mode='test';t.subscription_expires_at=datetime.utcnow()+timedelta(days=365);db.commit()
assert verify(h,d).status_code==200
db.expire_all();assert t.payment_mode=='live' and t.subscription_status=='active'
assert 29 <= (t.subscription_expires_at-datetime.utcnow()).days <= 30
# A server error or a malformed body is a payment error, not a successful checkout.
for response in [httpx.Response(502,text='bad gateway'), httpx.Response(200,json=[]), httpx.Response(200,json={'status':True})]:
 with httpx.Client(transport=httpx.MockTransport(lambda req:response)) as c:
  try:
   paystack.initialize_transfer_transaction('a@example.com',750000,'https://app.test',client=c)
   raise AssertionError('malformed response accepted')
  except paystack.PaystackError: pass
print('PASS test-to-live cutover and malformed provider responses')
