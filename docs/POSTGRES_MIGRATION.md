# Moving the metadata DB from SQLite to Postgres (Railway)

The Docker image defaults `METADATA_DB_URL` to a SQLite file on a Railway
volume. That file holds every tenant's encrypted DB credentials, MFA
secrets, Paystack tokens, and the whole audit log — with no point-in-time
recovery and backups that depend entirely on the volume. This moves it to
managed Postgres.

**This is the "Postgres now, KMS later" path.** `KMS_PROVIDER` stays
`local` and `ENVIRONMENT` stays unset, so:

- **Do not change `APP_SECRET_KEY`.** Stored connection credentials are
  encrypted with it; a changed key can't decrypt them. Copy it across
  unchanged (it already is — you're not touching it).
- `/docs` stays open until you do the `ENVIRONMENT=production` step later
  (`docs/BILLING_GO_LIVE.md`-style, plus AWS KMS — `docs/CLOUD_KMS.md`).

Pick a quiet window. The migration copies a snapshot; anything written to
SQLite between the copy and the cutover is lost. For a handful of tenants
with nobody mid-session that's a non-issue, but don't do it during a demo.

---

## 1. Create the Postgres database

Railway → your project → **New → Database → PostgreSQL**. Railway
provisions it and exposes a `DATABASE_URL` on that new service.

## 2. Give the backend the target URL (temporarily)

Railway → **backend** service → Variables → add:

```
TARGET_DB_URL=${{Postgres.DATABASE_URL}}
```

(Use the variable-reference syntax so it resolves to the private-network
URL. If your Postgres service isn't named exactly `Postgres`, use its
actual name.)

Don't touch `METADATA_DB_URL` yet — the app is still on SQLite, which is
what the migration reads *from*.

## 3. Run the migration

**Preferred — `railway ssh`** (runs inside the live container, so it has
both the SQLite volume and the private-network path to Postgres):

```bash
railway ssh --service backend
# then, inside:
python scripts/migrate_metadata_db.py
```

**Fallback — one-off start command.** If `railway ssh` isn't available:
backend service → Settings → **Start Command** → temporarily set it to

```
python scripts/migrate_metadata_db.py && sleep 300
```

Redeploy, watch the deploy logs, then **restore the original start
command** (`uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` — or
whatever it was; the Dockerfile's default is used if it's blank).

Either way you're looking for this at the end of the output:

```
verifying audit hash chains on target:
  tenant xxxxxxxx...     N rows  intact
  ...
OK - all tables copied, counts match, audit chains intact.
```

If it says **MIGRATION HAS PROBLEMS** or any chain is **BROKEN**, stop —
don't cut over. The SQLite DB is untouched (the script only reads it), so
you've lost nothing; send me the output.

## 4. Cut over

Once step 3 reports OK:

1. Backend service → Variables:
   - Set `METADATA_DB_URL` to the same value as `TARGET_DB_URL`
     (`${{Postgres.DATABASE_URL}}`).
   - Delete `TARGET_DB_URL`.
2. Redeploy. On boot, `init_db()` runs its light migrations against
   Postgres (adds the JSON columns as native `json`, not `text` — this is
   why the app must create them, per the comment in
   `app/db/session.py`).

## 5. Verify the live app

- `curl -s https://<backend>/health` → `{"status":"ok"}`
- Log in as an existing tenant admin. Open **Analyses** history and the
  **Audit log** — the rows are there.
- Backend `GET /audit/verify` (with that admin's token) → `"intact": true`.
- If a tenant has a connected data source: open it and run one question —
  confirms the encrypted credential still decrypts (it will, because
  `APP_SECRET_KEY` is unchanged).

## 6. Backups

Railway Postgres has automated daily backups — confirm they're enabled in
the **Postgres service → Settings**, and do one test restore into a
throwaway database so you know the restore path works before you need it.

## 7. Clean up

Leave the old backend **volume** in place for a week as a fallback (it
still has the pre-migration SQLite file). Once you're confident, detach
and delete it.

---

## If step 3 reports problems

The script is read-only on SQLite, so a failed run costs nothing. Re-run
it with `--force` (it wipes the Postgres side and reloads) after fixing
whatever it flagged. Common causes: a row count mismatch usually means the
app wrote to SQLite mid-migration (re-run in a quieter window); a broken
chain would point at a specific audit row.
