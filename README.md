# ContextOps

ContextOps is a native Slack incident-response agent. It listens for bot mentions,
pulls fresh AWS diagnostics through an MCP tool server, searches Slack history for
similar incidents, and replies with a concise diagnosis plus an optional incident
report workflow.

## What This Scaffold Includes

- FastAPI app with Slack Bolt event handling.
- MCP tool server exposing AWS diagnostic tools.
- MCP client abstraction used by the Slack agent.
- Slack historical search integration.
- Audit logging for Slack user actions.
- Incident report generation with S3 upload or local fallback.
- Demo mode for local development without cloud credentials.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system diagram.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:api --reload --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

## Slack App Setup

1. Create a Slack app and bot.
2. Enable Event Subscriptions.
3. Set the request URL to `https://api.yourdomain.com/slack/events`.
4. Subscribe to the `app_mention` bot event.
5. Add OAuth scopes:
   - `app_mentions:read`
   - `chat:write`
   - `search:read`
   - `files:write` if you later upload reports directly to Slack
6. Install the app to your workspace.
7. Set `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and `SLACK_APP_TOKEN` if needed.

## AWS Setup

Set these variables when switching out of demo mode:

```env
DEMO_MODE=false
AI_PROVIDER=bedrock
AWS_BEARER_TOKEN_BEDROCK=your-bedrock-api-key
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0
AWS_REGION=us-east-1
CLOUDWATCH_LOG_GROUP=/aws/ecs/payment-api
S3_REPORT_BUCKET=contextops-incident-reports
DATABASE_URL=postgresql+asyncpg://contextops:password@your-rds-host:5432/contextops
```

The EC2 role should be granted the smallest useful permissions:

- `logs:FilterLogEvents`
- `logs:DescribeLogStreams`
- `cloudwatch:GetMetricData`
- `s3:PutObject`
- `s3:GetObject`

## MCP Server

Run the MCP server directly:

```powershell
python -m app.mcp_server
```

The Slack agent can call tools directly in-process for local development, or
through the MCP stdio transport:

```env
CONTEXTOPS_MCP_MODE=stdio
```

Available tools:

- `get_aws_logs`
- `check_server_status`

## Deployment Shape

On EC2, run the FastAPI application behind Nginx or an ALB:

```powershell
uvicorn app.main:api --host 0.0.0.0 --port 8000
```

Point `api.yourdomain.com/slack/events` to `/slack/events`.

## Demo Prompt

Mention the bot in Slack:

```text
@ContextOps the payment API is throwing 500 timeouts
```

In demo mode, ContextOps returns a realistic Redis timeout diagnosis and links it
to a prior Slack incident pattern.
