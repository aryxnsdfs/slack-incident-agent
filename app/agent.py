import asyncio
import json
import os
import re

import boto3
from openai import AsyncOpenAI

from app.config import get_settings
from app.mcp_client import DiagnosticsClient, build_diagnostics_client
from app.models import IncidentContext, IncidentResolution, SlackSearchHit
from app.slack_search import SlackKnowledgeSearch


_SYSTEM_PROMPT = (
    "You are ContextOps, a Slack-native incident responder. "
    "Reply with a single JSON object and nothing else, no markdown fences, no prose. "
    "Schema: {\"diagnosis\": string, \"recommendation\": string, \"confidence\": \"high\"|\"medium\"|\"low\"}. "
    "Keep diagnosis to one or two plain sentences. "
    "Keep recommendation to a short actionable next step (one to three sentences). "
    "Do not include headings, emojis, or bullet lists."
)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace:
            candidate = brace.group(0)
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


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
        if self.settings.demo_mode:
            return self._deterministic_resolution(context)
        if self.settings.ai_provider == "bedrock" and self.settings.aws_bearer_token_bedrock:
            return await self._resolve_with_bedrock(context)
        if self.settings.ai_provider == "openai" and self.settings.openai_api_key:
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
        response = await client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": self._build_prompt(context)},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or ""
        return self._parse_resolution(text, context)

    async def _resolve_with_bedrock(self, context: IncidentContext) -> IncidentResolution:
        text = await asyncio.to_thread(self._bedrock_converse, context)
        return self._parse_resolution(text, context)

    def _build_prompt(self, context: IncidentContext) -> str:
        logs = "\n".join(event.message for event in context.aws.log_events[:8]) or "No matching log events."
        hits = "\n".join(hit.text for hit in context.slack_hits[:5]) or "No matching Slack history."
        return f"Request: {context.query}\nAWS logs:\n{logs}\nSlack history:\n{hits}"

    def _parse_resolution(self, text: str, context: IncidentContext) -> IncidentResolution:
        history = context.slack_hits[0] if context.slack_hits else None
        fallback_confidence = "medium" if context.aws.log_events else "low"
        data = _extract_json(text)
        if data:
            diagnosis = str(data.get("diagnosis") or "").strip() or context.aws.summary
            recommendation = str(data.get("recommendation") or "").strip() or context.aws.summary
            confidence = str(data.get("confidence") or "").strip().lower() or fallback_confidence
            if confidence not in {"high", "medium", "low"}:
                confidence = fallback_confidence
            return IncidentResolution(
                diagnosis=diagnosis,
                recommendation=recommendation,
                confidence=confidence,
                historical_reference=history,
            )
        # Model did not return JSON; degrade to the raw text as a single diagnosis line.
        clean = " ".join(text.split()).strip()
        return IncidentResolution(
            diagnosis=clean or context.aws.summary,
            recommendation=clean or context.aws.summary,
            confidence=fallback_confidence,
            historical_reference=history,
        )

    def _bedrock_converse(self, context: IncidentContext) -> str:
        if self.settings.aws_bearer_token_bedrock and not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = self.settings.aws_bearer_token_bedrock

        client = boto3.client("bedrock-runtime", region_name=self.settings.aws_region)
        response = client.converse(
            modelId=self.settings.bedrock_model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": self._build_prompt(context)}],
                }
            ],
            inferenceConfig={"temperature": 0.2, "maxTokens": 600},
        )
        content = response.get("output", {}).get("message", {}).get("content", [])
        return "\n".join(block.get("text", "") for block in content if block.get("text")).strip()


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
