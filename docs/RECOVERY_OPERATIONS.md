# Recovery operations

## Live synthetic upload/restart probe

Run inside the backend container through the authorized Railway console. The
probe creates an isolated, disabled-login test account under a unique
`recovery-probe-...` tenant. It uses authenticated loopback API calls to upload
a known CSV and generate/download a real PDF. No model calls, emails, checkout
requests, customer records or external database connections are involved.

```
PYTHONPATH=. python scripts/storage_recovery_probe.py create
```

Keep the printed probe ID. Before restart the command must report two durable
objects and matching original bytes. Then restart only the backend service,
wait for health and console connectivity, and run:

```
PYTHONPATH=. python scripts/storage_recovery_probe.py verify --probe-id PROBE_ID
```

An actual disposable-filesystem recovery test should report that both original
cache paths were missing before restoration and that the original CSV and PDF
bytes match. A verify run with existing caches is a successful read test, but
not proof of restart recovery. It compares the PDF with a checksum persisted
before restart and exercises the existing signed download endpoint.

Clean up only that explicitly identified synthetic tenant:

```
PYTHONPATH=. python scripts/storage_recovery_probe.py cleanup --probe-id PROBE_ID
```

Cleanup verifies the reserved ID pattern, test label, disabled password and
synthetic email before deleting its caches and tenant-scoped records. It refuses
ordinary customer tenant IDs. If create fails after the tenant was created,
use the ID printed at creation to clean up. These commands are operator tools,
not public endpoints and are never executed automatically at application boot.

## Backups

The reviewed Hobby workspace cannot create Railway native backups. A paid plan
decision is required before enabling them. After upgrading to an eligible plan,
create an initial Postgres volume backup and enable a daily backup schedule.
Review retention and incremental backup storage charges in the actual account.
Database backup coverage now includes encrypted stored files, but the encryption
key must be separately recoverable. A volume backup alone cannot recover bytes
if its application key is lost.

Test restoration into an isolated database/environment. Never restore a test
backup over production. Verify schema, tenant/source isolation, a synthetic
document, a synthetic PDF, password decryption and MFA secret decryption. Record
backup timestamps and actual recovery results; a configured schedule alone is
not evidence of a successful restore. An isolated restore adds storage/compute
usage and needs an agreed budget.

## Separately controlled key management

Use the restricted AWS KMS setup and staged migration in CLOUD_KMS.md. The
operator needs an AWS account, a symmetric key and only GenerateDataKey/Decrypt
permission on that specific key. The role should not be able to disable/delete
the key or change its policy. Provisioning IAM access and entering credentials
must be separately authorized. Do not enter AWS secrets into chat.

Deploy dual-format reads before migrating. Take and verify a backup first, then
perform a synthetic KMS roundtrip and migration, and only then migrate production
passwords, MFA secrets and files. AWS activation is not completed by deploying
the reader or by passing stubbed tests. Preserve the old key until legacy counts
are zero and the recovery procedure is proven.
