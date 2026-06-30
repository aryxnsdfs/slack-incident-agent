import re

from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

from app.agent import ContextOpsAgent, format_slack_response
from app.config import get_settings
from app.reporting import save_report
from app.storage import record_audit


settings = get_settings()
slack_app = AsyncApp(
    token=settings.slack_bot_token or "xoxb-contextops-demo-token",
    signing_secret=settings.slack_signing_secret or "contextops-demo-signing-secret",
)
handler = AsyncSlackRequestHandler(slack_app)
agent = ContextOpsAgent()
incident_cache: dict[str, tuple[object, object]] = {}


@slack_app.event("app_mention")
async def handle_app_mention(event, say, logger):
    query = _clean_bot_mention(event.get("text", ""))
    channel = event["channel"]
    user = event.get("user", "unknown")
    thread_ts = event.get("thread_ts") or event.get("ts")

    await record_audit(
        slack_user_id=user,
        slack_channel_id=channel,
        action="investigate",
        query=query,
    )

    await say(text="I am checking AWS diagnostics and Slack history now.", thread_ts=thread_ts)
    try:
        context, resolution = await agent.investigate(
            query=query,
            requester=user,
            channel=channel,
            thread_ts=thread_ts,
        )
        incident_cache[thread_ts] = (context, resolution)
        await say(text=format_slack_response(resolution), thread_ts=thread_ts)
    except Exception as exc:
        logger.exception("ContextOps investigation failed")
        await record_audit(
            slack_user_id=user,
            slack_channel_id=channel,
            action="investigate",
            query=query,
            status="error",
        )
        await say(text=f"I could not complete the investigation: {exc}", thread_ts=thread_ts)


@slack_app.message(re.compile(r"^\s*report\s*$", re.IGNORECASE))
async def handle_report_request(message, say):
    channel = message["channel"]
    user = message.get("user", "unknown")
    thread_ts = message.get("thread_ts") or message.get("ts")
    cached = incident_cache.get(thread_ts)
    if not cached:
        await say(text="I do not have an investigation cached for this thread yet.", thread_ts=thread_ts)
        return

    context, resolution = cached
    report_url = await save_report(context, resolution)
    await record_audit(
        slack_user_id=user,
        slack_channel_id=channel,
        action="generate_report",
        query=getattr(context, "query", ""),
    )
    await say(text=f"Incident report generated: {report_url}", thread_ts=thread_ts)


def _clean_bot_mention(text: str) -> str:
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip() or "Investigate the current incident."
