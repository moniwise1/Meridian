"""General file Ask, multi-turn grounding, bounded parsing and connector transport."""
import base64
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(tempfile.mkdtemp())
os.environ['METADATA_DB_URL'] = f'sqlite:///{root}/meta.db'
os.environ['APP_SECRET_KEY'] = base64.urlsafe_b64encode(b'0' * 32).decode()
os.environ['ARTIFACTS_DIR'] = str(root / 'artifacts')
os.environ['ANTHROPIC_API_KEY'] = ''
from app.agents.document_intelligence import extract
from app.agents.tabular_analysis import extract_tables, build_profile
from app.agents.portable_files import flat_records

for kind, raw in [('json', b'[{"Team":"Support","Wait":20},{"Team":"Support","Wait":10},{"Team":"Retail","Wait":5}]'),
                  ('tsv', b'Team\tWait\nSupport\t20\nSupport\t10\nRetail\t5')]:
    parsed_kind, extraction = extract(f'service.{kind}', raw)
    assert parsed_kind == kind and 'Support' in extraction.text
    path = root / f'service.{kind}'
    path.write_bytes(raw)
    tables, errors = extract_tables(str(path), kind)
    assert tables and not errors, errors
    profile = build_profile(tables[0], 'Wait by Team')
    assert profile.overall['total'] == 35, profile.overall
    assert profile.breakdowns['Team'][0] == {'group': 'Support', 'value': 15.0}
assert extract('notes.md', b'# Queue review\nCustomer wait time increased.')[0] == 'md'
assert extract('notes.txt', 'Research findings'.encode('utf-16'))[1].text == 'Research findings'
for raw in [b'{"count":1,"count":2}', b'{"value":NaN}', b'\x00\x01']:
    try: extract('input.json', raw)
    except (ValueError, UnicodeError): pass
    else: raise AssertionError('Malformed or ambiguous JSON was accepted')
try: flat_records([{'nested': {'count': 10}}])
except ValueError: pass
else: raise AssertionError('Nested JSON must not become a numerical table')
large = json.dumps([{'value': i} for i in range(600)]).encode()
assert extract('records.json', large)[1].truncated

from app.db.session import init_db, SessionLocal
from app.db.models import Tenant, User, UploadedDocument, Conversation, QueryRecord
from app.agents import planner
from app.agents.insight_agent import DocumentInsight
from app.agents.context_resolver import ResolvedQuestion
init_db()
db = SessionLocal()
db.add(Tenant(id='t', name='Service team', subscription_status='active'))
db.add(User(id='u', tenant_id='t', email='analyst@example.com', password_hash='unused'))
db.add(UploadedDocument(id='d', tenant_id='t', user_id='u', filename='service.json', kind='json',
    file_path=str(root/'service.json'), extracted_text='Support waits 20 and 10 minutes. Retail waits 5.',
    char_count=70, content_sha256='version-1'))
db.commit()
calls = []
def explain(question, documents, **kwargs):
    calls.append(kwargs)
    return DocumentInsight(what='Support average wait is 15 minutes.', next_question='What about Retail?', confidence='high', confidence_explanation='Calculated from records.', data_quality_caveat='Snapshot.', extraction_summary={}, key_findings=[], flagged_items=[], structured_data=[]), []
def run(question, conversation=None, user='u', scope=None):
    events = list(planner.run_analysis(db, 't', user, None, question, scope or {},
        conversation_id=conversation, document_ids=['d']))
    return next(event for event in events if isinstance(event, dict) and event.get('final'))
with patch.object(planner, 'explain_document_only_v2', explain), patch.object(planner, 'resolve_followup', lambda q,c: ResolvedQuestion(resolved_question=q)):
    first = run('Wait by Team')
    second = run('What about the other team?', first['conversation_id'])
    assert second['conversation_id'] == first['conversation_id']
    history = calls[1]['conversation_history']
    assert history[0]['question'] == 'Wait by Team' and '15 minutes' in history[0]['answer']
    for i in range(12): run(f'Follow-up {i}', first['conversation_id'])
    conversation = db.query(Conversation).filter_by(id=first['conversation_id']).one()
    assert len(conversation.context['turns']) == 10
    assert conversation.context['primary_value_column'] == 'Wait'
    assert db.query(QueryRecord).filter_by(conversation_id=first['conversation_id']).count() == 14
    for user,scope in [('other', {}), ('u', {'Team': ['Retail']})]:
        try: run('Wait?', first['conversation_id'], user, scope)
        except planner.PolicyViolation: pass
        else: raise AssertionError('Conversation/row permission boundary bypassed')

from app.connectors.postgres import PostgresConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.mssql import MSSQLConnector
from app.security.secrets import RedactedSecret
for module, cls in [('postgres', PostgresConnector), ('mysql', MySQLConnector), ('mssql', MSSQLConnector)]:
    with patch(f'app.connectors.{module}.create_engine') as engine:
        cls('db.example.com', 5432, 'service', 'reader@example.com', RedactedSecret('p@ss:/?#'), extra_config={'transport_tls':'verify'})
        url = engine.call_args.args[0]
        assert url.username == 'reader@example.com' and url.password == 'p@ss:/?#'
        if module == 'postgres': assert engine.call_args.kwargs['connect_args']['sslmode'] == 'verify-full'
        if module == 'mysql':
            context = engine.call_args.kwargs['connect_args']['ssl']
            import ssl
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
print('PASS: portable files, service analysis, grounded conversation history, permissions, URL escaping and TLS')

# Shared definitions deliberately published by business admins; private notes stay private.
from fastapi import HTTPException
from app.security.auth import AuthContext
from app.api.routes_analyst import save_memory, delete_memory, MemoryInput
from app.agents.analyst_workspace import memories_for
admin = AuthContext('u', 't', 'admin')
member = AuthContext('member', 't', 'analyst')
db.add(User(id='member', tenant_id='t', email='member@example.com', password_hash='unused'))
db.commit()
private = save_memory(MemoryInput(source_key='doc:d', content='Personal hypothesis'), db, admin)
shared = save_memory(MemoryInput(source_key='doc:d', content='Wait means elapsed queue minutes.', shared=True), db, admin)
assert private['shared'] is False and shared['shared'] is True
member_notes = memories_for(db, 't', 'member', 'doc:d')
assert [note['id'] for note in member_notes] == [shared['id']]
assert not memories_for(db, 'other-tenant', 'member', 'doc:d')
try: save_memory(MemoryInput(source_key='doc:d', content='Unapproved definition', shared=True), db, member)
except HTTPException as error: assert error.status_code == 403
else: raise AssertionError('Member published company definitions')
try: delete_memory(shared['id'], db, member)
except HTTPException as error: assert error.status_code == 404
else: raise AssertionError('Member removed company definition')
delete_memory(shared['id'], db, admin)
assert not memories_for(db, 't', 'member', 'doc:d')
print('PASS: company definitions, admin publishing, tenant isolation and private-note preservation')

# Privilege discovery must never issue a write probe; ambiguous/errors fail closed.
from contextlib import contextmanager
from unittest.mock import MagicMock
@contextmanager
def connection(conn): yield conn
for cls, values, expected in [(PostgresConnector, ['on', False, False], True),
                               (PostgresConnector, ['on', False, True], False),
                               (PostgresConnector, ['on', True, False], False),
                               (MSSQLConnector, [0], True), (MSSQLConnector, [1], False)]:
    instance = object.__new__(cls)
    conn = MagicMock()
    conn.execute.side_effect = [SimpleNamespace(scalar=lambda value=value: value) for value in values]
    instance._readonly_conn = lambda timeout: connection(conn)
    assert instance.verify_read_only() is expected
    assert all(not any(word in str(call.args[0]).upper() for word in ['CREATE TABLE', 'CREATE TEMP', 'INSERT INTO']) for call in conn.execute.call_args_list)
for grants, expected in [([('GRANT SELECT, SHOW VIEW ON `service`.* TO reader',)], True),
                         ([('GRANT ALL PRIVILEGES ON *.* TO reader',)], False),
                         ([('GRANT SELECT ON service.* TO reader WITH GRANT OPTION',)], False),
                         ([('GRANT `writer_role` TO reader',)], False)]:
    instance = object.__new__(MySQLConnector)
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = grants
    instance._readonly_conn = lambda timeout: connection(conn)
    assert instance.verify_read_only() is expected
print('PASS: read privileges accepted; writes, elevated roles and ambiguous grants rejected without DDL')

# Real schedule metadata, real analysis/PDF, current permissions and at-most-once claims.
from datetime import datetime, timedelta, timezone
from app.api import routes_schedules as schedules
from app.db.models import AnalysisSchedule, Notification, GeneratedArtifact

tenant = db.query(Tenant).filter_by(id='t').one()
tenant.plan = 'premium'
db.commit()
created = schedules.create_schedule(schedules.ScheduleInput(source_key='doc:d', question='Wait by Team',
    first_run_at=datetime.now(timezone.utc)+timedelta(hours=1), generate_pdf=True,
    alert_metric='Average of Wait', alert_above='above', alert_threshold='10'), db, admin)
job = db.query(AnalysisSchedule).filter_by(id=created['id']).one()
job.next_run_at = datetime.utcnow() - timedelta(days=15)
db.commit()
now = datetime.utcnow()
with patch.object(planner, 'explain_document_only_v2', explain):
    assert schedules.run_one(db, job, now)
    db.refresh(job)
    assert job.status == 'complete', job.last_message
    assert job.next_run_at > now
    assert db.query(GeneratedArtifact).filter_by(source_query_id=job.last_query_id).count() == 1
    assert db.query(Notification).filter_by(user_id='u', kind='analysis_alert').count() == 1
    assert not schedules.run_one(db, job, now), 'A job before its due date must not run again'
    job.next_run_at = now - timedelta(seconds=1)
    db.commit()
    assert schedules.run_one(db, job, now)
    assert db.query(Notification).filter_by(user_id='u', kind='analysis_alert').count() == 1, 'Repeated high values must not spam alerts'
    user = db.query(User).filter_by(id='u').one()
    user.capabilities = []
    job.next_run_at = now - timedelta(seconds=1)
    db.commit()
    assert schedules.run_one(db, job, now)
    assert job.status == 'blocked'
    user.capabilities = ['querying', 'document_retrieval', 'report_generation']
    db.commit()
try: schedules.update_schedule(job.id, schedules.ScheduleUpdate(enabled=False), db, member)
except HTTPException as error: assert error.status_code == 404
else: raise AssertionError('Another user controlled this schedule')
assert schedules.list_schedules(db, member) == []
try: schedules.verify_runner('wrong')
except HTTPException as error: assert error.status_code == 503
else: raise AssertionError('Unconfigured global runner allowed')
print('PASS: private recurring analyses, real PDF, threshold crossings, missed-interval skipping and revoked access')

# Company reporting mappings are stored server-side; calculations remain permission-scoped.
from app.api.routes_business import SaveViewRequest, OverviewRequest, save_view, saved_views, remove_view
csv_path = root / 'sales.csv'
csv_path.write_text('date,revenue,expense,region\n2026-10-01,100,20,East\n2026-10-02,200,50,West\n')
db.add(UploadedDocument(id='sales', tenant_id='t', user_id='u', filename='sales.csv', kind='csv',
    file_path=str(csv_path), extracted_text='Sales by region', char_count=15))
db.commit()
view = save_view(SaveViewRequest(name='October branch results', mapping=OverviewRequest(document_id='sales',
    date_column='date', revenue_column='revenue', expense_column='expense', currency='NGN',
    start='2026-10-01', end='2026-10-02')), db, admin)
assert saved_views(db, member)['views'][0]['mapping']['revenue_column'] == 'revenue'
assert saved_views(db, AuthContext('x', 'other-tenant', 'admin'))['views'] == []
try: save_view(SaveViewRequest(name='Unauthorized', mapping=OverviewRequest(document_id='sales',
    date_column='date', currency='NGN', start='2026-10-01', end='2026-10-02')), db, member)
except HTTPException as error: assert error.status_code == 403
else: raise AssertionError('Member saved a company reporting view')
remove_view(view['id'], db, admin)
print('PASS: reusable company mappings, admin management and tenant isolation')

# Real multi-file planner calculations are isolated by source and saved as evidence.
second_path = root / 'october.csv'
second_path.write_text('Team,Wait\nSupport,8\nRetail,12\n')
db.add(UploadedDocument(id='october', tenant_id='t', user_id='u', filename='october.csv', kind='csv',
    file_path=str(second_path), extracted_text='Support wait 8; Retail wait 12.', char_count=34))
db.commit()
def calculate_files(question, documents, **kwargs):
    workspace = kwargs['table_workspace']
    assert len(workspace.catalog()) == 2
    for table in workspace.catalog():
        result = workspace.execute({'table_id':table['table_id'], 'operation':'average', 'value_column':'Wait',
            'filters':[{'column':'Team','operator':'eq','value':'Support'}]})
        assert result['result'] == (15.0 if table['filename'] == 'service.json' else 8.0)
    return explain(question, documents, **kwargs)
with patch.object(planner, 'explain_document_only_v2', calculate_files):
    events = list(planner.run_analysis(db, 't', 'u', None, 'Compare Support waits across files', {},
        document_ids=['d','october']))
    final = next(event for event in events if isinstance(event, dict) and event.get('final'))
    record = db.query(QueryRecord).filter_by(id=final['query_id']).one()
    assert len(record.result_snapshot['table_calculations']) == 2
    assert any('Verified calculation' in note for note in record.result_snapshot['data_quality']['notes'])
print('PASS: real multi-file planner computes per-source figures and persists evidence')
