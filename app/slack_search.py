from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from app.config import get_settings
from app.models import SlackSearchHit


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
        hits = []
        for match in matches:
            hits.append(
                SlackSearchHit(
                    title=match.get("channel", {}).get("name", "Prior Slack discussion"),
                    permalink=match.get("permalink", ""),
                    channel_name=match.get("channel", {}).get("name"),
                    user_name=match.get("user_name") or match.get("username"),
                    text=match.get("text", ""),
                    timestamp=match.get("ts"),
                )
            )
        return hits
