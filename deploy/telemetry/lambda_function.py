"""Receives opt-in telemetry reports from FishEye desktop apps and stores
each one as a JSON file in S3.

Invoked over HTTP through a Lambda function URL (auth type NONE - the
desktop app has no AWS credentials). The desktop app only ever sees this
function's URL, never the bucket.

Apps upload once a day in batches: the body is {"reports": [...]}. The
response has one result per report, in the same order:

    {"results": [{"status": "saved"}, {"status": "rejected", "error": "..."}, ...]}

- saved: stored; the app deletes it from its outbox
- rejected: malformed in a way retrying won't fix; the app deletes it too
- error: storing it failed; the app keeps it and retries later

A non-200 status means the whole batch wasn't processed, and the app
retries all of it later.

Deliberately dependency-free (only boto3, which the Lambda Python runtime
already includes), so it deploys as a single pasted file - validation here
is a light structural check, not the full TelemetryPayload model from
fisheye_ui/schemas.py.
"""

import base64
import json
import os
import re

import boto3

BUCKET_NAME = os.environ["BUCKET_NAME"]

# Per batch. One report per job, with ~250-300 bytes per input file (a counts entry
# plus a track_stats entry), so a large batch folder - e.g. a month of
# hourly sonar files, ~720 files - is ~200 KB. 1 MB fits several thousand
# files while staying well under the function URL's 6 MB request limit.
MAX_BODY_BYTES = 1024 * 1024

SUPPORTED_SCHEMA_VERSIONS = {1}

REQUIRED_FIELDS = (
    "schema_version",
    "job_id",
    "os",
    "status",
    "file_count",
    "counts",
    "track_stats",
)

# job_id is a uuid4 from fisheye.common.system.generate_job_id. Validated
# strictly because it becomes part of the S3 key.
JOB_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

s3 = boto3.client("s3")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _validation_error(report):
    """A short reason the report is rejected, or None if it looks valid."""
    if not isinstance(report, dict):
        return "report must be a JSON object"
    missing = [field for field in REQUIRED_FIELDS if field not in report]
    if missing:
        return f"missing fields: {', '.join(missing)}"
    if report["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        return "unsupported schema_version"
    if not isinstance(report["job_id"], str) or not JOB_ID_PATTERN.match(
        report["job_id"]
    ):
        return "invalid job_id"
    if not isinstance(report["counts"], list) or not isinstance(
        report["track_stats"], list
    ):
        return "counts and track_stats must be lists"
    contact = report.get("contact")
    if contact is not None and not (
        isinstance(contact, dict) and isinstance(contact.get("email"), str)
    ):
        return "invalid contact"
    return None


def _store(report):
    """Validate and store one report, returning its result entry."""
    error = _validation_error(report)
    if error:
        return {"status": "rejected", "error": error}

    # Keyed by job_id rather than a fresh random ID so a retried report
    # (sent, saved, but the response got lost) overwrites itself instead of
    # creating a duplicate. Bucket versioning keeps the earlier copy anyway.
    key = f"telemetry/v{report['schema_version']}/{report['job_id']}.json"
    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(report).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as e:
        # Logged to CloudWatch; the app keeps the report and retries later.
        print(f"put_object failed for {key}: {type(e).__name__}")
        return {"status": "error"}
    return {"status": "saved"}


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method != "POST":
        return _response(405, {"error": "method not allowed"})

    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", errors="replace")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        return _response(413, {"error": "batch too large"})

    try:
        batch = json.loads(body)
    except json.JSONDecodeError:
        return _response(400, {"error": "invalid JSON"})
    if not isinstance(batch, dict) or not isinstance(batch.get("reports"), list):
        return _response(400, {"error": 'expected {"reports": [...]}'})

    return _response(200, {"results": [_store(report) for report in batch["reports"]]})
