from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from common import config


def make_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or config.DATABASE_URL, pool_pre_ping=True)
