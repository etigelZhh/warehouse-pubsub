import os

import pytest
import sqlalchemy as sa
from redis.asyncio import Redis

from common.db import make_engine
from common.tables import metadata
from inventory_api.app import create_app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/inventory_test"
)
TEST_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture
async def engine():
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.execute(sa.text("TRUNCATE stock_events, stock_agg RESTART IDENTITY"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def redis():
    client = Redis.from_url(TEST_REDIS_URL)
    yield client
    await client.aclose()


@pytest.fixture
async def client(aiohttp_client, engine):
    app = create_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    return await aiohttp_client(app)
