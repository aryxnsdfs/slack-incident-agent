from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class AwsLogEvent:
    timestamp: datetime
    message: str
    log_stream: str | None = None


@dataclass(slots=True)
class AwsDiagnostics:
    service: str
    status: str
    summary: str
    log_events: list[AwsLogEvent] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SlackSearchHit:
    title: str
    permalink: str
    channel_name: str | None
    user_name: str | None
    text: str
    timestamp: str | None = None


@dataclass(slots=True)
class IncidentContext:
    query: str
    requester: str
    channel: str
    thread_ts: str | None
    aws: AwsDiagnostics
    slack_hits: list[SlackSearchHit]


@dataclass(slots=True)
class IncidentResolution:
    diagnosis: str
    recommendation: str
    confidence: str
    historical_reference: SlackSearchHit | None = None
