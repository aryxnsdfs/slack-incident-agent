from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slack_user_id: Mapped[str] = mapped_column(String(80), index=True)
    slack_channel_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(120))
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="ok")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


settings = get_settings()
engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def record_audit(
    *,
    slack_user_id: str,
    slack_channel_id: str,
    action: str,
    query: str,
    status: str = "ok",
) -> None:
    async with SessionLocal() as session:
        session.add(
            AuditLog(
                slack_user_id=slack_user_id,
                slack_channel_id=slack_channel_id,
                action=action,
                query=query,
                status=status,
            )
        )
        await session.commit()
