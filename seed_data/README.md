# Demo seed data

Two tables shaped specifically to exercise every deterministic agent in the
app. Every finding below was verified against the actual `detect()` /
`forecast_by_group()` code in `backend/app/agents/`, not just eyeballed —
see the totals and confidence levels are real output, not predictions.

## Load it

```bash
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=demo postgres:16
psql -h localhost -U postgres -d demo -f seed.sql
```

This also creates a read-only role: `analytics_readonly` / `devpass_readonly`.
Connect it in Meridian's **Data sources** screen with those credentials,
database `demo`, port `5432`.

## What to expect

**`sales`** (region, product, branch, month, revenue) — 5 regions, 3
products, 3 branches, Jan–Jun 2026:

- Ask *"How did South-East revenue change last month?"* → a sharp real
  anomaly: South-East jumps from 56,200 to 155,000 in June (+176%,
  moderate confidence). The investigation cascade should drill it to
  **Widget A** (120,000 of the 155,000), then to **Branch-2** within
  Widget A (95,000 of the 120,000) — the branch→product cascade the
  original spec's example describes.
- West has **no June rows at all** — a missing-period anomaly ("No data
  recorded for West in the most recent period").
- North grows cleanly +4,000/month — forecasting should project it
  **up** for July/August. Central and Northeast are flat/noisy — forecast
  **flat**.
- Try a **Risk scan** on this connection: it should surface the South-East
  spike and the West gap without you asking about either by name.

**`marketing_spend`** (category, month, amount) — 4 channels, same months:

- Events spends 8,000/month flat, then spikes to 40,000 in June (a second,
  independent anomaly in a second table) — this is what demonstrates the
  risk scan finding something across *multiple* tables, not just the one
  you happened to ask about.

## Why 5 regions in `sales`, not 4

The anomaly detector is a z-score across peer groups in the same
comparison period. West has no June row, so it's excluded from the
May→June comparison — with only 3 remaining groups, South-East's own
extremity distorted its own z-score below the detection threshold in
testing. Northeast exists purely as a stable fourth comparison point so
the z-score has a proper baseline. Found and fixed by actually running the
detector against the data, not assumed.
