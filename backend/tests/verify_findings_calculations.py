"""The answer brief and PDF retain real tool scope, units and source identity."""
import os
import json
from pathlib import Path
import tempfile
os.environ.setdefault('APP_SECRET_KEY','dGVzdC1vbmx5LWZlcm5ldC1rZXktMzJieXRlcy0wMDA=')
root = Path(tempfile.mkdtemp())
os.environ['ARTIFACTS_DIR'] = str(root)
import pandas as pd
import pymupdf
from app.agents.table_tools import TableWorkspace, ParsedTable
from app.agents.analyst_contract import Analysis, build_analysis
from app.agents.report_generator import generate_report_pdf
frame = pd.DataFrame({'Region':['West','West','East','East'], 'Sales':[10,40,5,15], 'Footfall':[100,300,100,100]})
workspace = TableWorkspace([ParsedTable('table-2','stores.csv',frame)])
calc = workspace.execute({'table_id':'table-2','operation':'rate','value_column':'Sales','denominator_column':'Footfall','filters':[{'column':'Region','operator':'eq','value':'West'}]})
assert calc['result'] == 12.5
sources = [{'id':'a','filename':'stores.csv','version':'version-a'}, {'id':'b','filename':'stores.csv','version':'version-b'}]
insight = {'what':'West sales conversion is 12.5%.','confidence':'moderate','confidence_explanation':'Observed conversion only.','data_quality_caveat':'Two matched rows; no causes established.','next_question':'Compare conversion by Region.'}
snapshot = {'table_calculations':workspace.evidence,'insight':insight,'row_count':0,'metrics':{'total':99999},'data_quality':{'completeness_pct':100,'row_count':0}}
analysis = build_analysis('AQ-check','West conversion?',snapshot,sources=sources,computed=False)
Analysis.model_validate(analysis)
assert len(analysis['metrics']) == 1 and analysis['metrics'][0]['value'] == 12.5 and analysis['metrics'][0]['unit'] == '%'
ref = analysis['metrics'][0]['evidence_ids'][0]
evidence = next(e for e in analysis['evidence'] if e['id'] == ref)
assert evidence['source_id'] == 'b' and evidence['source_version'] == 'version-b'
assert 'West' in evidence['location'] and '2 matched / 4 parsed' in evidence['location']
assert analysis['quality']['row_count'] is None and analysis['confidence']['measurement']['level'] == 'medium'
assert not any('No structured table was verified' in n for n in analysis['quality']['limitations'])
# Groups retain exact numerical values and record counts, including null rates.
workspace.execute({'table_id':'table-2','operation':'rate','value_column':'Sales','denominator_column':'Footfall','group_column':'Region'})
snapshot['table_calculations'] = workspace.evidence
analysis = build_analysis('AQ-check','Conversion by region?',snapshot,sources=sources,computed=False)
assert analysis['tables'][0]['rows'][0]['records'] == 2
path = generate_report_pdf('Conversion investigation','West conversion?',insight,analysis=analysis,data_quality=snapshot['data_quality'],query_id='AQ-check')
pdf = pymupdf.open(path)
text = '\n'.join(p.get_text() for p in pdf)
assert '12.5%' in text and 'West' in text and '2 matched / 4 parsed' in text
assert 'Reproduce the question-specific figures' in text and 'version-b' in text
compact = ' '.join(text.split()).lower()
assert 'matched records' in compact and 'region = west' in compact and 'all parsed rows' in compact, compact
assert 'All figures were computed deterministically' not in text
assert 'Rows analysed\n0' not in text
for page in pdf:
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                x0,y0,x1,y1 = span['bbox']
                assert x0 >= 0 and x1 <= page.rect.width + 1 and y0 >= 0 and y1 <= page.rect.height + 1
# Only a test fixture outside the repository; not a production artifact.
Path('/tmp/meridian-findings-pdf-path').write_text(path)
Path('/tmp/meridian-findings-analysis.json').write_text(json.dumps(analysis))
print('Scoped tool figures, duplicate filenames, grouped counts, exact PDF units and calculation audit passed')
