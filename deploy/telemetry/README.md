# Telemetry receiver setup

Receives opt-in usage reports from FishEye desktop apps (see #152) and
stores each one as a JSON file in a private S3 bucket. A Lambda function
with a public function URL sits in front of the bucket, so the desktop app
never holds AWS credentials and never sees the bucket name.

```
FishEye app ──POST report──▶ Lambda function URL ──PutObject──▶ S3 (private)
            ◀── 200 / 4xx ──                                     telemetry/v1/<job_id>.json
```

Telemetry is desktop-only for now. It's turned off on the cloud GPU worker
(`FISHEYE_UI_TELEMETRY_ENABLED=0` in `deploy/gpu-worker/fisheye-ui.service`).

## Files

| File | What it is |
|------|------------|
| `lambda_function.py` | The Lambda handler. Paste it into the console as-is. |
| `lambda-role-policy.json` | Permissions for the Lambda's role: upload to `telemetry/` only. |
| `bucket-policy.json` | Bucket policy: reject any request not over HTTPS. |

In every JSON file, replace `REPLACE_WITH_BUCKET_NAME` with the real bucket
name before using it.

## 1. Create the bucket

S3 console → **Create bucket**:

| Setting | Value |
|---------|-------|
| Bucket type | General purpose |
| Bucket name | Lowercase, globally unique, **can't be changed later** |
| Region | The same region you'll create the Lambda in |
| Object Ownership | ACLs disabled (Bucket owner enforced) |
| Block Public Access | **All four checked** |
| Bucket Versioning | Enable |
| Tags | e.g. `project=fisheye`, `purpose=telemetry` |
| Default encryption | SSE-S3 |
| Object Lock (Advanced) | **Disable**: reports must stay deletable, e.g. if someone who chose "contact" asks to have their details removed |

Then **Permissions → Bucket policy** → paste `bucket-policy.json`.

Optional: **Management → Lifecycle rule** to expire reports after a set
time. With versioning on, also add "permanently delete noncurrent versions
after 30 days" so deleted reports don't linger.

Leave static website hosting, CORS, and access points off.

## 2. Create the Lambda

Lambda console → **Create Event Function** → Author from scratch. (Not a
Web Function: those run their own web server, while this is a plain
`lambda_handler(event, context)`.)

- **Runtime:** Python 3.12
- **Architecture:** arm64 (cheaper; nothing here depends on x86)
- **Execution role:** create a new role with basic Lambda permissions
  (this gives it CloudWatch logging)

Then:

1. **Code:** replace the default `lambda_function.py` with this folder's
   copy, and click **Deploy**.
2. **Configuration → Environment variables:** add `BUCKET_NAME` = your
   bucket name.
3. **Configuration → General configuration:** 128 MB memory, 10 s timeout.
4. **Configuration → Permissions:** click the role name → **Add
   permissions → Create inline policy** → JSON → paste
   `lambda-role-policy.json`.
5. **Configuration → Concurrency:** set **reserved concurrency** to `2`.
   Caps how many copies can run at once, so abuse can't run up costs. Real
   traffic is a few small uploads per user per day, so 2 is plenty.
   Requests over the cap get a 429, and the desktop app retries them later.
6. **Configuration → Function URL → Create:** auth type **NONE**. Leave
   CORS off (the app sends from its Python backend, not the browser).

Copy the function URL. It isn't stored in the repo: release builds of the
desktop app take it from `FISHEYE_TELEMETRY_URL` at build time (see "Usage
reporting URL" in `electron/README.md`). Builds without it have usage
reporting turned off, so a fork of this repo only reports anywhere once it
deploys its own receiver from this folder and builds with that URL.

**Write the URL down somewhere durable.** Installed apps have it built in.
Recreating the function, or moving to another AWS account, gives a new URL,
and installed apps keep sending to the old one until users update.

## 3. Verify

```bash
URL=https://<your-function-url>/

# One valid and one invalid report →
# {"results": [{"status": "saved"}, {"status": "rejected", "error": "missing fields: ..."}]}
curl -s -X POST "$URL" -H 'Content-Type: application/json' -d '{"reports": [
  {
    "schema_version": 1,
    "job_id": "00000000-0000-4000-8000-000000000000",
    "os": "darwin", "status": "completed", "file_count": 0,
    "counts": [], "track_stats": []
  },
  {"hello": "world"}
]}'

# Not a batch → 400
curl -s -X POST "$URL" -H 'Content-Type: application/json' -d '{"hello": "world"}'
```

The valid one should appear at
`telemetry/v1/00000000-0000-4000-8000-000000000000.json` in the bucket.
Delete it afterwards.

If it fails, check **Monitor → View CloudWatch logs** on the Lambda.

## 4. Reading the reports

Anyone whose existing AWS login has S3 read access in this account can
download everything with:

```bash
aws s3 sync s3://<bucket-name>/telemetry/ ./fisheye-telemetry/
```

and load it in Python:

```python
import json, pathlib
import pandas as pd

reports = [json.loads(p.read_text()) for p in pathlib.Path("fisheye-telemetry").rglob("*.json")]
jobs = pd.json_normalize(reports)
files = pd.json_normalize(reports, record_path="counts", meta=["job_id"])
```

Reports with the "contact" choice include names and emails, so everyone
with S3 read access in this account can see those.

## How reports are stored

- Apps upload once a day, sending `{"reports": [...]}`, split into batches
  under 1 MB. The response has a `saved` / `rejected` / `error` result per
  report, in order; see the docstring in `lambda_function.py`.
- One file per job: `telemetry/v<schema_version>/<job_id>.json`.
- Keyed by `job_id`, so a report the app retries (because the response got
  lost) overwrites itself instead of creating a duplicate.
- The Lambda does a light structural check only: required fields,
  supported `schema_version`, a valid `job_id`, and batches under 1 MB (a
  single report fits several thousand input files) with at most 100
  reports. Anyone can send to the URL, so filter on the full schema when
  analyzing.

## Abuse and cost

The URL ships inside every installed app, so anyone can find it and send
junk. What limits the damage:

- **Reserved concurrency (2)** caps how fast requests can be processed.
- **At most 100 reports per request**, rejected before anything is written,
  so one request can cause at most 100 S3 writes.
- **Write-only role**: the Lambda can't read, list, or delete existing
  reports, so nothing private is exposed even if it's abused.

Also set up a **billing alert**: Billing → Budgets → Create budget → a
monthly cost budget of e.g. $10 that emails you. Normal use costs cents.

**Kill switch:** set reserved concurrency to `0`. Every request then gets a
429 immediately and nothing is written. Apps keep their reports in their
outbox and retry later, so nothing is lost; set it back to `2` to resume.

If abuse becomes ongoing, put API Gateway (built-in throttling) or
CloudFront + WAF (per-IP rate limits) in front of the function. Junk that
did get stored can be filtered out at analysis time or deleted by key.

## Moving to another AWS account

Buckets can't be transferred. Create a new bucket and Lambda in the new
account following the steps above, then copy the data:

```bash
# Run as the destination account, after adding a bucket policy on the old
# bucket that grants it s3:ListBucket + s3:GetObject
aws s3 sync s3://<old-bucket> s3://<new-bucket>
```

The new Lambda gets a new function URL, so ship an app update built with
the new `FISHEYE_TELEMETRY_URL` before retiring the old one.
