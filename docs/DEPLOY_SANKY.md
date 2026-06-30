# Deploying ContextOps on sanky.space

These steps deploy the Slack incident agent on the existing server at `54.90.5.155`
under `/var/www/sanky`.

## 1. Copy the project to the server

From your Windows machine, run this from the project folder:

```powershell
scp -i "C:\Users\aryan\.ssh\cortex-key.pem" -r . ubuntu@54.90.5.155:/var/www/sanky/slack-incident-agent
```

If `/var/www/sanky/slack-incident-agent` already exists, SSH in first and move it
aside or pull/update it from Git.

## 2. SSH into the server

```powershell
ssh -i "C:\Users\aryan\.ssh\cortex-key.pem" ubuntu@54.90.5.155
```

Then:

```bash
cd /var/www/sanky/slack-incident-agent
```

## 3. Create the production environment file

Create `/var/www/sanky/slack-incident-agent/.env`:

```bash
nano .env
```

Use this template and replace the placeholders:

```env
APP_NAME=ContextOps
PUBLIC_BASE_URL=https://sanky.space/slack-incident-agent
DEMO_MODE=false

SLACK_BOT_TOKEN=xoxb-your-real-slack-bot-token
SLACK_SIGNING_SECRET=your-real-slack-signing-secret
SLACK_REALTIME_SEARCH_METHOD=search.messages
SLACK_SEARCH_COUNT=5

AI_PROVIDER=bedrock
AWS_BEARER_TOKEN_BEDROCK=your-bedrock-api-key
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-6

AWS_REGION=us-east-1
CLOUDWATCH_LOG_GROUP=/aws/ecs/contextops
CLOUDWATCH_FILTER_PATTERN=ERROR ?Exception ?Timeout ?500
S3_REPORT_BUCKET=aryan-contextops-reports

DATABASE_URL=postgresql+asyncpg://contextops:your-db-password@contextops.cyhmmk2iixru.us-east-1.rds.amazonaws.com:5432/contextops

CONTEXTOPS_MCP_MODE=direct
MCP_TOOL_TIMEOUT_SECONDS=20
LOCAL_REPORT_DIR=reports
```

Do not commit this file.

## 4. Install Python dependencies

You said the server venv is at `/var/www/sanky/venv`.

```bash
source /var/www/sanky/venv/bin/activate
pip install -r requirements.txt
```

## 5. Add AWS credentials for CloudWatch and S3

The Bedrock API key is only for model calls. The app still needs AWS credentials
or an instance role for CloudWatch logs and S3 reports.

If this server is EC2, attach an IAM role to the instance. If it is not EC2,
create an IAM user and add these to `.env`:

```env
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
```

Required IAM permissions:

```text
logs:FilterLogEvents
logs:DescribeLogStreams
cloudwatch:GetMetricData
s3:PutObject
s3:GetObject
```

Scope S3 access to:

```text
arn:aws:s3:::aryan-contextops-reports/*
```

Scope CloudWatch Logs access to the `/aws/ecs/contextops` log group if possible.

## 6. Run a quick local server test

```bash
source /var/www/sanky/venv/bin/activate
cd /var/www/sanky/slack-incident-agent
uvicorn app.main:api --host 127.0.0.1 --port 8001
```

In another SSH terminal:

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8001/slack-incident-agent
```

Both should return JSON with `"status":"ok"`.

## 7. Create a systemd service

Create:

```bash
sudo nano /etc/systemd/system/contextops.service
```

Paste:

```ini
[Unit]
Description=ContextOps Slack Incident Agent
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/sanky/slack-incident-agent
EnvironmentFile=/var/www/sanky/slack-incident-agent/.env
ExecStart=/var/www/sanky/venv/bin/uvicorn app.main:api --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable contextops
sudo systemctl restart contextops
sudo systemctl status contextops
```

## 8. Add Nginx routing

Edit:

```bash
sudo nano /etc/nginx/sites-enabled/sanky.space
```

Inside the `server` block for `sanky.space`, add:

```nginx
location /slack-incident-agent/ {
    proxy_pass http://127.0.0.1:8001/slack-incident-agent/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /slack-incident-agent {
    proxy_pass http://127.0.0.1:8001/slack-incident-agent;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Then:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 9. Enable HTTPS

Slack event URLs should use HTTPS. If `sanky.space` does not already have TLS:

```bash
sudo certbot --nginx -d sanky.space
```

The Slack request URL should be:

```text
https://sanky.space/slack-incident-agent/slack/events
```

## 10. Slack final settings

In Slack app settings:

Event Subscriptions request URL:

```text
https://sanky.space/slack-incident-agent/slack/events
```

Bot event:

```text
app_mention
```

Bot scopes:

```text
app_mentions:read
chat:write
files:write
search:read.files
search:read.im
search:read.mpim
search:read.private
search:read.public
```

After changing scopes or event URLs, reinstall the app to the workspace.

Invite the bot to incident channels:

```text
/invite @slack-incident-agent
```

## 11. Smoke test

Check the public health route:

```bash
curl https://sanky.space/slack-incident-agent
```

Then mention the bot in Slack:

```text
@slack-incident-agent payment API is throwing 500 errors
```

Check logs if needed:

```bash
sudo journalctl -u contextops -f
```
