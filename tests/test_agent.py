import pytest

from app.config import get_settings
from app.agent import ContextOpsAgent
from app.aws_tools import get_aws_logs
from app.models import AwsDiagnostics
from app.slack_search import SlackKnowledgeSearch


@pytest.fixture(autouse=True)
def demo_settings(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_demo_aws_logs_return_redis_timeout():
    diagnostics = await get_aws_logs(service="payment-api")

    assert isinstance(diagnostics, AwsDiagnostics)
    assert diagnostics.status == "degraded"
    assert any("Redis" in event.message for event in diagnostics.log_events)


@pytest.mark.asyncio
async def test_agent_correlates_aws_and_slack_history():
    agent = ContextOpsAgent(knowledge_search=SlackKnowledgeSearch())
    _, resolution = await agent.investigate(
        query="payment API is throwing 500 timeouts",
        requester="U123",
        channel="C123",
        thread_ts="123.45",
    )

    assert resolution.confidence == "high"
    assert "Redis" in resolution.diagnosis
