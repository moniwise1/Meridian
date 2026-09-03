# Cloud KMS setup (production credential encryption)

By default (`KMS_PROVIDER=local`), the key that encrypts every connected
database's stored password is a single static value sitting in your
`APP_SECRET_KEY` env var. That's fine for development, but it means a leak
of your metadata database *plus* that one env var is enough to decrypt
every customer credential you're holding. This switches to real envelope
encryption via AWS KMS: every credential gets its own random data key, and
only that data key — never the credential itself — is ever sent to AWS to
be wrapped by a master key that never leaves AWS's HSMs. See the docstring
in `backend/app/security/secrets.py` for the full design.

**Honesty check**: this has been verified against a stubbed KMS client
(`botocore.stub.Stubber`) confirming the exact API calls and the
encrypt/decrypt round trip, but not against a real AWS account — this repo
has none available to test with. Confirm your first real encrypt/decrypt
in AWS's own console (CloudTrail will show the `Encrypt`/`Decrypt`/
`GenerateDataKey` calls) before trusting this with real customer data.

## 1. Create the KMS key

In the AWS Console → KMS → Create key (Symmetric, "Encrypt and decrypt"),
or via CLI:

```bash
aws kms create-key --description "Meridian credential encryption"
# note the KeyId / Arn from the output
```

## 2. Create a scoped IAM user (or role) for the app

The app needs exactly two permissions on this one key — nothing else, and
definitely not broad KMS access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
      "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/YOUR-KEY-ID"
    }
  ]
}
```

Attach this policy to a dedicated IAM user (if hosting outside AWS, e.g.
Railway/Render/Fly — you'll use that user's access keys) or an IAM role
(if hosting on AWS compute, which can assume the role without static
keys at all — preferred if available, not currently wired into this app's
boto3 client construction, which relies on boto3's standard credential
chain either way).

## 3. Configure the app

```bash
KMS_PROVIDER=aws
AWS_KMS_KEY_ID=arn:aws:kms:REGION:ACCOUNT_ID:key/YOUR-KEY-ID
AWS_REGION=us-east-1  # match the key's actual region
AWS_ACCESS_KEY_ID=...       # the scoped IAM user's keys
AWS_SECRET_ACCESS_KEY=...   # boto3 reads these standard env vars itself -
                             # they're not app-specific settings
```

## 4. Migrating existing credentials

Switching `KMS_PROVIDER` does **not** re-encrypt anything already stored —
existing `encrypted_password` values were encrypted with the local Fernet
key and stay that way; the app has no dual-read fallback for this. To
migrate a live database: for each `DataSourceConnection` row, decrypt with
the old (`local`) backend, re-encrypt with the new (`aws`) backend, and
update the row — a one-off script, not built into this app, since it needs
to run with *both* backends configured simultaneously for the duration of
the migration.

## 5. Rotating the master key

KMS key rotation (automatic annual, or on-demand) is transparent to this
app — old ciphertexts remain decryptable against a rotated key because AWS
tracks key versions internally. Nothing in this app needs to change when
you rotate the KMS key itself.
