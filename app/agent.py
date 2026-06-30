from openai import AsyncOpenAI

from app.config import get_settings
from app.mcp_client import DiagnosticsClient, build_diagnostics_client
from app.models import IncidentContext, IncidentResolution, SlackSearchHit
from app.slack_search import SlackKnowledgeSearch


class ContextOpsAgent:
    def __init__(
        self,
        diagnostics: DiagnosticsClient | None = None,
        knowledge_search: SlackKnowledgeSearch | None = None,
    ) -> None:
        self.settings = get_settings()
        self.diagnostics = diagnostics or build_diagnostics_client()
        self.knowledge_search = knowledge_search or SlackKnowledgeSearch()

    async def investigate(
        self,
        *,
        query: str,
        requester: str,
        channel: str,
        thread_ts: str | None,
    ) -> tuple[IncidentContext, IncidentResolution]:
        aws = await self.diagnostics.get_aws_logs(query)
        slack_hits = await self.knowledge_search.search(query)
        context = IncidentContext(
            query=query,
            requester=requester,
            channel=channel,
            thread_ts=thread_ts,
            aws=aws,
            slack_hits=slack_hits,
        )
        return context, await self._resolve(context)

    async def _resolve(self, context: IncidentContext) -> IncidentResolution:
        if self.settings.openai_api_key and not self.settings.demo_mode:
            return await self._resolve_with_openai(context)
        return self._deterministic_resolution(context)

    def _deterministic_resolution(self, context: IncidentContext) -> IncidentResolution:
        logs = " ".join(event.message.lower() for event in context.aws.log_events)
        history = context.slack_hits[0] if context.slack_hits else None
        if "redis" in logs or _hit_mentions(history, "redis"):
            return IncidentResolution(
                diagnosis="AWS logs point to Redis connection timeouts behind the payment API 500s.",
                recommendation=(
                    "Follow the prior incident playbook: check Redis connection saturation, flush the "
                    "payment session cache if approved, then restart the payment API cache client."
                ),
                confidence="high",
                historical_reference=history,
            )

        return IncidentResolution(
            diagnosis=context.aws.summary,
            recommendation="Review the matching CloudWatch events and compare them with the linked Slack incidents.",
            confidence="medium" if context.aws.log_events else "low",
            historical_reference=history,
        )

    async def _resolve_with_openai(self, context: IncidentContext) -> IncidentResolution:
        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        logs = "\n".join(event.message for event in context.aws.log_events[:8])
        hits = "\n".join(hit.text for hit in context.slack_hits[:5])
        response = await client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ContextOps, a Slack-native incident responder. "
                        "Return a short diagnosis, recommendation, and confidence."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Request: {context.query}\nAWS logs:\n{logs}\nSlack history:\n{hits}",
                },
            ],
            temperature=0.2,
        )
        text = response.choices[0].message.content or context.aws.summary
        return IncidentResolution(
            diagnosis=text.splitlines()[0] if text else context.aws.summary,
            recommendation=text,
            confidence="medium",
            historical_reference=context.slack_hits[0] if context.slack_hits else None,
        )


def format_slack_response(resolution: IncidentResolution) -> str:
    history = resolution.historical_reference
    if history and history.permalink:
        reference = f"We had a similar incident here: <{history.permalink}|{history.title}>."
    elif history:
        reference = f"Slack search found a related note: {history.text}"
    else:
        reference = "I did not find a matching prior Slack thread."

    return (
        f"I checked AWS diagnostics and Slack history.\n\n"
        f"*Diagnosis:* {resolution.diagnosis}\n"
        f"*Prior context:* {reference}\n"
        f"*Recommended next step:* {resolution.recommendation}\n\n"
        "Reply `report` in this thread and I will generate the incident report."
    )


def _hit_mentions(hit: SlackSearchHit | None, phrase: str) -> bool:
    if not hit:
        return False
    return phrase.lower() in hit.text.lower()
