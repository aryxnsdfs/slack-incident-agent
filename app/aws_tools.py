import asyncio
from datetime import timedelta
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.models import AwsDiagnostics, AwsLogEvent, utc_now


DEMO_LOGS = [
    AwsLogEvent(
        timestamp=utc_now(),
        log_stream="payment-api/prod/redis-client",
        message="ERROR payment-api: Redis connection timeout after 3000ms while handling POST /charges",
    ),
    AwsLogEvent(
        timestamp=utc_now(),
        log_stream="payment-api/prod/web-2",
        message="HTTP 500 upstream timeout: cache lookup failed for customer payment session",
    ),
]


async def get_aws_logs(service: str = "payment-api", minutes: int = 5, filter_pattern: str | None = None) -> AwsDiagnostics:
    settings = get_settings()
    if settings.demo_mode:
        return AwsDiagnostics(
            service=service,
            status="degraded",
            summary="Recent CloudWatch logs show Redis connection timeouts causing payment API 500s.",
            log_events=DEMO_LOGS,
            metrics={"source": "demo", "window_minutes": minutes},
        )

    return await asyncio.to_thread(_fetch_cloudwatch_logs, service, minutes, filter_pattern)


def _fetch_cloudwatch_logs(service: str, minutes: int, filter_pattern: str | None) -> AwsDiagnostics:
    settings = get_settings()
    client = boto3.client("logs", region_name=settings.aws_region)
    start_time = int((utc_now() - timedelta(minutes=minutes)).timestamp() * 1000)
    pattern = filter_pattern or settings.cloudwatch_filter_pattern

    try:
        response = client.filter_log_events(
            logGroupName=settings.cloudwatch_log_group,
            startTime=start_time,
            filterPattern=pattern,
            limit=25,
        )
    except (BotoCoreError, ClientError) as exc:
        return AwsDiagnostics(
            service=service,
            status="unknown",
            summary=f"CloudWatch query failed: {exc}",
            log_events=[],
            metrics={"error": str(exc), "log_group": settings.cloudwatch_log_group},
        )

    events = [
        AwsLogEvent(
            timestamp=utc_now(),
            log_stream=event.get("logStreamName"),
            message=event.get("message", "").strip(),
        )
        for event in response.get("events", [])
    ]
    status = "degraded" if events else "healthy"
    summary = (
        f"Found {len(events)} matching CloudWatch log events in the last {minutes} minutes."
        if events
        else f"No matching CloudWatch errors in the last {minutes} minutes."
    )
    return AwsDiagnostics(
        service=service,
        status=status,
        summary=summary,
        log_events=events,
        metrics={"log_group": settings.cloudwatch_log_group, "filter_pattern": pattern},
    )


async def check_server_status(service: str = "payment-api") -> dict[str, Any]:
    settings = get_settings()
    if settings.demo_mode:
        return {
            "service": service,
            "status": "degraded",
            "checks": {
                "api_health": "failing",
                "redis": "connection_timeout",
                "database": "healthy",
            },
        }

    diagnostics = await get_aws_logs(service=service, minutes=5)
    return {
        "service": service,
        "status": diagnostics.status,
        "checks": {
            "cloudwatch_errors": len(diagnostics.log_events),
            "region": settings.aws_region,
        },
    }
