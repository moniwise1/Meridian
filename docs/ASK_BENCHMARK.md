# Ask quality benchmark

`backend/tests/fixtures/ask_benchmark.json` contains 12 synthetic, known-answer
questions and explicit calculation requests. Run:

```
cd backend
APP_SECRET_KEY=test-benchmark PYTHONPATH=. python tests/verify_ask_benchmark.py
```

The initial computation score is 12/12. Five fixtures pass the current structured
file parser; seven tiny/all-null fixtures use an explicitly reported DataFrame
fallback to exercise computation edge cases. These fallback cases must not be
counted as successful end-to-end uploaded-file analyses. The parser's usability
heuristics need separate evaluation against small but legitimate files.

This is a baseline for source arithmetic and evidence recording. Requests are
preselected; it does not score the model's natural-language planning. Existing
permission regression suites remain necessary and are not replaced by it.

## Live-model evaluation still required

Replay each question through Ask with the actual synthetic file and record:

* Correct source, metric, operation, denominator and filters selected.
* Exact answer or an appropriate precise clarification.
* Correct evidence references and disclosure of missing/truncated records.
* No invented causes, joins, missing periods or unsupported conclusions.
* Follow-up consistency, latency, token usage and tool-call count.

Then extend with PDFs, malformed sheets, ambiguous dates, repeated headers,
duplicate records, multiple workbooks and an authorized test database. Include
negative tests for narrowed permissions, unrelated tenant IDs and instructions
embedded in files. Use only synthetic data for this benchmark. Do not report a
live model score until calls have actually been run and independently checked.

## Storage gate before production changes

Confirm uploads and artifacts are on persistent storage before redeploying the
backend. The Dockerfile writes files to `/app/documents` and `/app/artifacts`;
creating those directories does not make them persistent. A database volume
does not persist the backend service's filesystem.

Inventory current files and their database references before a migration. Copy
available bytes to the chosen durable destination, verify sizes/hashes, and
verify authorized download and file analysis against that destination. Account
for database rows whose original files are already missing. Do not overwrite
those records or claim their original bytes can be recovered from extracted
text. Keep the old path readable during cutover where possible.

Also verify a real backup policy and restore into an isolated environment;
never restore a test backup over production. Select backup retention and storage
costs explicitly. Credential encryption needs its own review: encrypted values
and encryption keys in the same infrastructure boundary provide less isolation
than separately controlled KMS keys. Changing encryption backends requires a
tested migration of existing encrypted credentials, not a variable switch alone.
