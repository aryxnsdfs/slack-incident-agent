from app.aws_tools import check_server_status as check_status_impl
from app.aws_tools import get_aws_logs as get_logs_impl

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - dependency installed from requirements
    FastMCP = None


if FastMCP:
    mcp = FastMCP("contextops-aws-diagnostics")

    @mcp.tool()
    async def get_aws_logs(service: str = "payment-api", minutes: int = 5, filter_pattern: str | None = None) -> dict:
        """Return recent CloudWatch diagnostic logs for a service."""
        diagnostics = await get_logs_impl(service=service, minutes=minutes, filter_pattern=filter_pattern)
        return {
            "service": diagnostics.service,
            "status": diagnostics.status,
            "summary": diagnostics.summary,
            "metrics": diagnostics.metrics,
            "log_events": [
                {
                    "timestamp": event.timestamp.isoformat(),
                    "log_stream": event.log_stream,
                    "message": event.message,
                }
                for event in diagnostics.log_events
            ],
        }

    @mcp.tool()
    async def check_server_status(service: str = "payment-api") -> dict:
        """Return a compact service health snapshot."""
        return await check_status_impl(service=service)
else:
    mcp = None


def main() -> None:
    if mcp is None:
        raise RuntimeError("Install requirements.txt before running the MCP server.")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
