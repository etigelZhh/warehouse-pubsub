import asyncio
import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from analytics_worker.handler import handle_message
from analytics_worker.worker import run_worker
from common.events import CHANNEL_ISSUE, CHANNEL_RECEIPT
from common.tables import stock_agg


def make_event(type_: str, qty: int, sku="A-100", warehouse="WH-1") -> str:
    return json.dumps(
        {
            "event_id": str(uuid.uuid4()),
            "type": type_,
            "sku": sku,
            "warehouse": warehouse,
            "qty": qty,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


async def agg_rows(engine):
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(stock_agg.c.warehouse, stock_agg.c.sku, stock_agg.c.qty).order_by(
                stock_agg.c.warehouse, stock_agg.c.sku
            )
        )
        return [tuple(r) for r in result]


async def test_events_update_single_row(engine):
    assert await handle_message(engine, CHANNEL_RECEIPT, make_event("receipt", 50))
    assert await handle_message(engine, CHANNEL_ISSUE, make_event("issue", 20))
    assert await agg_rows(engine) == [("WH-1", "A-100", 30)]


async def test_invalid_messages_are_skipped(engine):
    assert not await handle_message(engine, CHANNEL_RECEIPT, b"not json")
    assert not await handle_message(engine, CHANNEL_RECEIPT, json.dumps({"sku": "A"}))
    # тип события не совпадает с каналом
    assert not await handle_message(engine, CHANNEL_ISSUE, make_event("receipt", 5))
    assert not await handle_message(engine, CHANNEL_RECEIPT, make_event("receipt", 0))
    assert await agg_rows(engine) == []


async def test_end_to_end_api_to_worker(client, engine, redis):
    stop, ready = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(run_worker(engine, redis, stop, ready))
    await asyncio.wait_for(ready.wait(), 5)
    try:
        await client.post("/receipts", json={"sku": "E2E", "qty": 50, "warehouse": "WH-9"})
        await client.post("/issues", json={"sku": "E2E", "qty": 20, "warehouse": "WH-9"})

        for _ in range(50):
            rows = await agg_rows(engine)
            if rows == [("WH-9", "E2E", 30)]:
                break
            await asyncio.sleep(0.1)
        assert rows == [("WH-9", "E2E", 30)]
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)
