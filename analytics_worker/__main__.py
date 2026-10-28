import asyncio
import logging
import signal

from redis.asyncio import Redis

from analytics_worker.worker import run_worker
from common import config
from common.db import make_engine


async def main() -> None:
    engine = make_engine()
    redis = Redis.from_url(config.REDIS_URL)
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        await run_worker(engine, redis, stop)
    finally:
        await redis.aclose()
        await engine.dispose()
        logging.getLogger(__name__).info("worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
