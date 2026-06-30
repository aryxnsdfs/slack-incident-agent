import asyncio
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.models import IncidentContext, IncidentResolution


def render_markdown_report(context: IncidentContext, resolution: IncidentResolution) -> str:
    log_lines = "\n".join(
        f"- `{event.timestamp.isoformat()}` `{event.log_stream or 'unknown'}` {event.message}"
        for event in context.aws.log_events
    ) or "- No matching log events found."
    history_lines = "\n".join(
        f"- [{hit.title}]({hit.permalink}) by {hit.user_name or 'unknown'}: {hit.text}"
        for hit in context.slack_hits
    ) or "- No similar Slack incidents found."

    return f"""# ContextOps Incident Report

## Request

{context.query}

## Diagnosis

{resolution.diagnosis}

## Recommendation

{resolution.recommendation}

## AWS Diagnostics

Service: `{context.aws.service}`

Status: `{context.aws.status}`

{context.aws.summary}

{log_lines}

## Prior Slack Knowledge

{history_lines}
"""


async def save_report(context: IncidentContext, resolution: IncidentResolution) -> str:
    settings = get_settings()
    body = render_markdown_report(context, resolution)
    key = f"incident-reports/{uuid4()}.md"

    if settings.s3_report_bucket and not settings.demo_mode:
        return await asyncio.to_thread(_upload_to_s3, settings.s3_report_bucket, key, body)

    settings.local_report_dir.mkdir(parents=True, exist_ok=True)
    local_path = settings.local_report_dir / Path(key).name
    local_path.write_text(body, encoding="utf-8")
    return str(local_path.resolve())


def _upload_to_s3(bucket: str, key: str, body: str) -> str:
    settings = get_settings()
    client = boto3.client("s3", region_name=settings.aws_region)
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
            ServerSideEncryption="AES256",
        )
        return client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"Unable to upload incident report to S3: {exc}") from exc
