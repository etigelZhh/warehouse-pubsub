import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from analytics_worker.handler import handle_message
from common.events import CHANNELS

log = logging.getLogger(__name__)


async def run_worker(
    engine: AsyncEngine,
    redis: Redis,
    stop: asyncio.Event,
    ready: asyncio.Event | None = None,
) -> None:
    """Слушает каналы Redis pub/sub, пока не выставлен stop."""
    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(*CHANNELS)
    log.info("subscribed to %s", ", ".join(CHANNELS))
    if ready is not None:
        ready.set()
    try:
        while not stop.is_set():
            msg = await pubsub.get_message(timeout=1.0)
            if msg is None or msg["type"] != "message":
                continue
            channel = msg["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()
            try:
                await handle_message(engine, channel, msg["data"])
            except Exception:
                # Ошибка одного сообщения (например, БД недоступна) не должна ронять воркер.
                log.exception("failed to process message on %s", channel)
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
