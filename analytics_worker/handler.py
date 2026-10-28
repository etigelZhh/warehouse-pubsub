import logging

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine
import sqlalchemy as sa

from common.events import CHANNEL_BY_TYPE, StockEvent
from common.tables import stock_agg

log = logging.getLogger(__name__)


def parse_event(channel: str, data: bytes | str) -> StockEvent | None:
    """Валидирует сообщение. Возвращает None, если оно некорректно."""
    try:
        event = StockEvent.model_validate_json(data)
    except ValidationError as e:
        log.warning("invalid event on %s: %s", channel, e.errors(include_url=False))
        return None
    if CHANNEL_BY_TYPE[event.type] != channel:
        log.warning("event type %r does not match channel %s", event.type, channel)
        return None
    return event


async def apply_event(engine: AsyncEngine, event: StockEvent) -> None:
    """Обновляет остаток пары (warehouse, sku) в stock_agg одним upsert-запросом."""
    stmt = insert(stock_agg).values(warehouse=event.warehouse, sku=event.sku, qty=event.delta)
    stmt = stmt.on_conflict_do_update(
        index_elements=[stock_agg.c.warehouse, stock_agg.c.sku],
        set_={"qty": stock_agg.c.qty + stmt.excluded.qty, "updated_at": sa.func.now()},
    )
    async with engine.begin() as conn:
        await conn.execute(stmt)


async def handle_message(engine: AsyncEngine, channel: str, data: bytes | str) -> bool:
    """Обрабатывает одно сообщение. True — если агрегат обновлён."""
    event = parse_event(channel, data)
    if event is None:
        return False
    await apply_event(engine, event)
    log.info("applied %s %s/%s delta=%d", event.type, event.warehouse, event.sku, event.delta)
    return True
