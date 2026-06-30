import asyncio
import sys
from datetime import datetime
from typing import Any

from app.aws_tools import get_aws_logs as direct_get_aws_logs
from app.config import get_settings
from app.models import AwsDiagnostics, AwsLogEvent


class DiagnosticsClient:
    async def get_aws_logs(self, query: str) -> AwsDiagnostics:
        raise NotImplementedError


class DirectDiagnosticsClient(DiagnosticsClient):
    async def get_aws_logs(self, query: str) -> AwsDiagnostics:
        service = infer_service(query)
        return await direct_get_aws_logs(service=service, minutes=5)


class StdioMCPDiagnosticsClient(DiagnosticsClient):
    async def get_aws_logs(self, query: str) -> AwsDiagnostics:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("The mcp package is required for stdio MCP mode.") from exc

        service = infer_service(query)
        settings = get_settings()
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"])

        async def call_tool() -> AwsDiagnostics:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("get_aws_logs", {"service": service, "minutes": 5})
                    payload = _extract_mcp_payload(result)
                    return _diagnostics_from_payload(payload)

        return await asyncio.wait_for(call_tool(), timeout=settings.mcp_tool_timeout_seconds)


def build_diagnostics_client() -> DiagnosticsClient:
    settings = get_settings()
    if settings.contextops_mcp_mode == "stdio":
        return StdioMCPDiagnosticsClient()
    return DirectDiagnosticsClient()


def infer_service(query: str) -> str:
    lowered = query.lower()
    if "payment" in lowered:
        return "payment-api"
    if "checkout" in lowered:
        return "checkout"
    if "auth" in lowered:
        return "auth-api"
    return "payment-api"


def _extract_mcp_payload(result: Any) -> dict[str, Any]:
    content = getattr(result, "content", None)
    if content and hasattr(content[0], "text"):
        import json

        return json.loads(content[0].text)
    if isinstance(result, dict):
        return result
    raise ValueError(f"Unexpected MCP result shape: {result!r}")


def _diagnostics_from_payload(payload: dict[str, Any]) -> AwsDiagnostics:
    events = []
    for item in payload.get("log_events", []):
        raw_ts = item.get("timestamp")
        timestamp = datetime.fromisoformat(raw_ts) if raw_ts else datetime.utcnow()
        events.append(
            AwsLogEvent(
                timestamp=timestamp,
                log_stream=item.get("log_stream"),
                message=item.get("message", ""),
            )
        )
    return AwsDiagnostics(
        service=payload.get("service", "unknown"),
        status=payload.get("status", "unknown"),
        summary=payload.get("summary", ""),
        log_events=events,
        metrics=payload.get("metrics", {}),
    )
