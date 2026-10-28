from aiohttp import web
from redis.asyncio import Redis

from common import config
from common.db import make_engine
from inventory_api.handlers import routes


def create_app(database_url: str | None = None, redis_url: str | None = None) -> web.Application:
    app = web.Application()
    app.add_routes(routes)

    async def resources(app: web.Application):
        app["engine"] = make_engine(database_url)
        app["redis"] = Redis.from_url(redis_url or config.REDIS_URL)
        yield
        await app["redis"].aclose()
        await app["engine"].dispose()

    app.cleanup_ctx.append(resources)
    return app
