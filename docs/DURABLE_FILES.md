# Durable uploads and generated artifacts

Original uploads and generated reports/exports are encrypted and stored in
`stored_files` in Meridian's metadata database, in the same transaction as their
document/artifact records. The existing metadata database must be persistent;
production uses Postgres. Local document and artifact paths are disposable
caches, restored from the database on authorized access.

This introduces no external storage service or public file endpoint. It does
increase database disk use. Default budgets are 50 MiB plaintext per stored
file, 100 MiB encrypted bytes per tenant, and 256 MiB encrypted bytes globally.
The existing upload limit remains 20 MiB. Operators can adjust
`MAX_STORED_FILE_BYTES`, `MAX_TENANT_STORED_FILES_BYTES`, and
`MAX_STORED_FILES_BYTES` after checking database capacity. Ciphertext includes
base64/encryption overhead; budgets count the actual stored ciphertext size.
Postgres quota checks use a transaction advisory lock across backend replicas;
SQLite is a development/test option, not the production storage configuration.

The existing encryption backend wraps file bytes; current local encryption uses
the application environment key, and an AWS KMS deployment uses its configured
envelope encryption. Do not rotate or lose that key without a tested migration:
restoring the database without the encryption key does not restore usable files.
This encrypts file bytes; it does not encrypt all existing extracted text or
analysis metadata columns. Separate key management remains a security task.

## Existing files and scope

On authorized access, a legacy file still present on disk is copied into durable
storage. A missing legacy file without stored bytes remains unavailable. Stored
extracted text is not an original-file backup. Ask reports that limitation;
business views require re-uploading the original when it cannot be restored.
No original is deleted as part of backfill. Failed new uploads/artifact writes
roll back their records and remove the newly written cache file.

Document deletion also removes its encrypted bytes. Existing owner-confirmed
tenant deletion removes that tenant's stored bytes. Cached files follow the
existing local lifecycle; database deletion does not erase historical backups.
Retention and backup deletion policies need their own operational rules.

## Verification and rollout

Tests use real SQLite, encryption, upload and signed-download endpoints. They
delete disposable caches and verify the original CSV/PDF bytes return unchanged,
including business-view reads. They verify tenant scoping, checksums, immutable
object identity, deletion and storage limits. Postgres advisory locking still
needs a real concurrent production-like database test.

After deploy, verify a synthetic upload and generated report survive a backend
restart. Do not use customer data for that check or restart before verifying new
objects have durable records. Separately verify database backups and restore into
an isolated environment. Durable database storage is not a backup: loss of the
database volume or encryption key can still lose the files.

Rolling back this code leaves the additive table intact, but old versions cannot
restore missing cache files from it. Materialize needed files before rollback;
never drop `stored_files` to roll back.
