"""Versioned known-answer benchmark. Offline checks measure the computation layer.

The request is supplied explicitly: passing this benchmark does NOT establish
natural-language planning accuracy, citation quality, or live model reliability.
"""
import json
import tempfile
from pathlib import Path
import pandas as pd
from app.agents.table_tools import ParsedTable, TableWorkspace
from app.agents import tabular_analysis

cases = json.loads((Path(__file__).parent / 'fixtures/ask_benchmark.json').read_text())
with tempfile.TemporaryDirectory() as directory:
    for case in cases:
        path = Path(directory) / (case['id'] + '.json')
        path.write_text(json.dumps(case['rows']))
        tables, diagnostics = tabular_analysis.extract_tables(str(path), 'json')
        frame = tabular_analysis.pick_best_table(tables)
        # The normal parser deliberately rejects some tiny/all-null tables.
        # Preserve those cases to test explicit null/empty computation semantics,
        # but report whether the file could actually be used as a parsed table.
        parsed = frame is not None
        if frame is None:
            frame = pd.DataFrame(case['rows'])
            for column in frame:
                if frame[column].isna().all():
                    frame[column] = pd.to_numeric(frame[column], errors='coerce')
        workspace = TableWorkspace([ParsedTable('table-1', path.name, frame)])
        result = workspace.execute({'table_id':'table-1', **case['request']})
        assert 'error' not in result, (case['id'], result)
        assert result['result'] == case['expected'], (case['id'], result)
        if 'excluded' in case:
            assert result['excluded_numeric_values'] == case['excluded']
        if 'matched' in case:
            assert result['matched_row_count'] == case['matched']
        if 'top_group' in case:
            assert result['groups'][0]['group'] == case['top_group']
            assert 'no join, implicit period or causal inference' in result['scope']
        assert result['evidence_id'] and len(workspace.evidence) == 1
        json.dumps(result, allow_nan=False)
        print(f"PASS {case['id']} | parsed_file={parsed} | expected={case['expected']}")
print(f"{len(cases)} known-answer computation cases passed; live language planning is not evaluated")
