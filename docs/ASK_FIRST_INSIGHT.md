# File overview and live Ask evaluation

Uploaded files now have a deterministic overview in the Documents page and in
Ask when a file is selected before a conversation starts. It shows the parsed
row count, fields, missing/non-finite cells and candidate repeated rows, plus
questions based on available columns. Counts cover Ask's selected parsed table,
not every sheet/section. No sample records are exposed and no extra model request
is made for the overview. Text-only files and rejected table layouts have an
explicit fallback; missing original bytes require re-upload.

`GET /documents/{id}/overview` rechecks the tenant, document-retrieval capability
and row restrictions before restoring or parsing bytes. Row-restricted users
cannot inspect tenant-wide file profiles. No inferred cause, business KPI or
aggregate headline is presented as a conclusion from the overview.

“Ask this file” carries its ID to Ask. It is checked against the signed-in
workspace's available files; suggested questions fill the composer and require
submission. They never run analyses automatically.

The explicit operator command below checks actual model tool selection against
synthetic data, without production database access or customer uploads:

```
PYTHONPATH=. python scripts/evaluate_live_ask.py --run-live
```

It makes three questions through the configured provider (normal inference
charges apply). Known answers are a weighted West conversion of 12.5% and an
East sales total of 20. It also prints an answer to an unsupported causal
question for manual review. The numerical checks require real tool evidence;
narrative correctness and citations need manual review. This is a narrow
live evaluation, not evidence of SQL accuracy, follow-up reliability,
long-document accuracy, concurrency or end-to-end browser behavior. It never
runs automatically or as part of offline regression tests.
