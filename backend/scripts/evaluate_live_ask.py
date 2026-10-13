"""Operator-only live synthetic tool-use evaluation; no production DB access.

Uses the configured model and its normal inference billing; never runs at boot.
"""
import argparse
import json
from dataclasses import asdict
import pandas as pd
from app.agents.insight_agent import explain_document_only_v2
from app.agents.table_tools import ParsedTable, TableWorkspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true')
    if not parser.parse_args().run_live:
        parser.error('Explicit --run-live is required; three synthetic questions use model inference.')
    frame = pd.DataFrame([
        {'Region':'West','Footfall':100,'Sales':10,'Wait':20},
        {'Region':'West','Footfall':300,'Sales':40,'Wait':10},
        {'Region':'East','Footfall':100,'Sales':5,'Wait':5},
        {'Region':'East','Footfall':100,'Sales':15,'Wait':15},
    ])
    cases = [
        ('weighted_conversion', 'For West only, compute overall Sales conversion as 100 times sum(Sales) / sum(Footfall). Use analyze_table and give the exact rate, not the average of row rates.', 'rate',12.5),
        ('filtered_total', 'Use analyze_table to calculate total Sales for East only. Give the exact result and the source.', 'sum',20),
        ('missing_cause', 'Why did West customers wait longer? Distinguish observations from possible explanations; do not invent staffing or customer feedback.', None,None),
    ]
    outcomes = []
    for name, question, operation, expected in cases:
        workspace = TableWorkspace([ParsedTable('table-1','synthetic-stores.csv',frame)])
        try:
            insight, charts = explain_document_only_v2(question,
                [{'filename':'synthetic-stores.csv','kind':'csv','text':frame.to_csv(index=False)}],
                force_answer=True, table_workspace=workspace)
            evidence = workspace.evidence
            exact = any(e['operation'] == operation and e['result'] == expected and e['matched_row_count'] == 2 for e in evidence) if operation else None
            outcomes.append({'case':name,'exact_tool_result':exact,'insight':asdict(insight),'table_calculations':evidence,'charts':charts})
            print(json.dumps(outcomes[-1],ensure_ascii=False,allow_nan=False),flush=True)
        except Exception:
            print(json.dumps({'case':name,'error':'Live evaluation failed; check provider health without exposing credentials.'}),flush=True)
            return 1
    print('Narrow tool checks only. Review narrative accuracy, citations and causal restraint manually. SQL, follow-ups, concurrency and long files are not evaluated.')
    return 0 if all(o['exact_tool_result'] is not False for o in outcomes) else 1

if __name__ == '__main__':
    raise SystemExit(main())
