"""Bounded, non-executable parsing for text and portable data exports."""
import io
import json
import csv

MAX_DATA_ROWS = 50_000
MAX_DATA_COLUMNS = 120


def decode_text(raw: bytes) -> str:
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = raw.decode('utf-16')
    else:
        text = raw.decode('utf-8-sig')
    if '\x00' in text:
        raise ValueError('Binary content is not a text document.')
    return text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON keys are ambiguous; export unique field names.')
        result[key] = value
    return result


def parse_json(text: str):
    def reject_constant(value):
        raise ValueError('JSON amounts must be finite numbers.')
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=reject_constant)


def flat_records(value):
    if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
        raise ValueError('Structured JSON analysis requires an array of flat records.')
    if len(value) > MAX_DATA_ROWS:
        raise ValueError('Use at most 50,000 records for structured JSON analysis.')
    columns = set()
    for row in value:
        columns.update(row)
        if any(isinstance(cell, (dict, list)) for cell in row.values()):
            raise ValueError('Nested JSON is read as text; flatten records for numerical analysis.')
    if not columns or len(columns) > MAX_DATA_COLUMNS:
        raise ValueError('Use between 1 and 120 fields per JSON record.')
    return value


def read_portable_table(raw: bytes, kind: str):
    """Return rows without interpreting or executing file contents."""
    text = decode_text(raw)
    if kind == 'json':
        return flat_records(parse_json(text))
    if kind == 'tsv':
        rows = list(csv.reader(io.StringIO(text), delimiter='\t'))
        if not rows or not rows[0] or len(set(rows[0])) != len(rows[0]):
            raise ValueError('TSV requires a unique header row.')
        header = rows[0]
        if len(header) > MAX_DATA_COLUMNS or len(rows) - 1 > MAX_DATA_ROWS:
            raise ValueError('Use at most 50,000 rows and 120 columns.')
        if any(len(row) != len(header) for row in rows[1:]):
            raise ValueError('TSV rows must match the header column count.')
        return [dict(zip(header, row)) for row in rows[1:]]
    raise ValueError('Unsupported structured export.')
