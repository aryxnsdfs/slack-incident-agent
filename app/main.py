from fastapi import FastAPI, Request

from app.config import get_settings
from app.slack_app import handler
from app.storage import init_db

settings = get_settings()
api = FastAPI(title=settings.app_name)


@api.on_event("startup")
async def startup() -> None:
    await init_db()


@api.get("/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "app": settings.app_name, "demo_mode": settings.demo_mode}


@api.get("/slack-incident-agent")
async def mounted_health() -> dict[str, str | bool]:
    return await health()


@api.post("/slack/events")
async def slack_events(request: Request):
    return await handler.handle(request)


@api.post("/slack-incident-agent/slack/events")
async def mounted_slack_events(request: Request):
    return await handler.handle(request)
