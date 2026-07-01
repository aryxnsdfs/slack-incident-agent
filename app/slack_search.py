from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from app.config import get_settings
from app.models import SlackSearchHit


# The agent's own Slack replies start with these phrases. Filtering them out
# prevents the bot from citing its own past messages as "prior context".
_AGENT_REPLY_SIGNATURES = (
    "i checked aws diagnostics",
    "i am checking aws diagnostics",
    "i could not complete the investigation",
    "incident report generated",
    "i do not have an investigation cached",
    "reply `report`",
    "reply report",
)


def _is_agent_echo(text: str) -> bool:
    low = text.strip().lower()
    return any(sig in low for sig in _AGENT_REPLY_SIGNATURES)


DEMO_HITS = [
    SlackSearchHit(
        title="Payment API 500s from Redis cache saturation",
        permalink="https://example.slack.com/archives/C123/p1697040000000000",
        channel_name="incidents",
        user_name="Sarah",
        text=(
            "Payment API returned 500s because Redis cache connections were exhausted. "
            "Flushing the payment session cache and restarting the cache client restored traffic."
        ),
        timestamp="2025-10-11T18:40:00Z",
    )
]


class SlackKnowledgeSearch:
    def __init__(self, client: AsyncWebClient | None = None) -> None:
        settings = get_settings()
        self.settings = settings
        # search.messages requires a user token (xoxp-) with search:read;
        # a bot token (xoxb-) returns not_allowed_token_type.
        self.search_token = settings.slack_user_token or settings.slack_bot_token
        self.client = client or AsyncWebClient(token=self.search_token)

    async def search(self, query: str) -> list[SlackSearchHit]:
        if self.settings.demo_mode or not self.search_token:
            return DEMO_HITS

        try:
            response = await self.client.api_call(
                self.settings.slack_realtime_search_method,
                params={
                    "query": query,
                    "count": self.settings.slack_search_count,
                    "sort": "timestamp",
                    "sort_dir": "desc",
                },
            )
        except SlackApiError as exc:
            return [
                SlackSearchHit(
                    title="Slack search unavailable",
                    permalink="",
                    channel_name=None,
                    user_name=None,
                    text=f"Slack search failed: {exc.response.get('error', 'unknown_error')}",
                )
            ]

        messages = response.get("messages", {})
        matches = messages.get("matches", []) if isinstance(messages, dict) else []
        bot_user_id = self.settings.slack_bot_user_id
        hits = []
        for match in matches:
            text = (match.get("text") or "").strip()
            # Skip empty hits, the bot's own author id, and the bot's echoed replies.
            if not text or _is_agent_echo(text):
                continue
            if bot_user_id and match.get("user") == bot_user_id:
                continue
            channel_name = match.get("channel", {}).get("name")
            hits.append(
                SlackSearchHit(
                    title=channel_name or "Prior Slack discussion",
                    permalink=match.get("permalink", ""),
                    channel_name=channel_name,
                    user_name=match.get("user_name") or match.get("username"),
                    text=text,
                    timestamp=match.get("ts"),
                )
            )
        return hits
