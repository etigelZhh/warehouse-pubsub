import logging

from aiohttp import web

from common import config
from inventory_api.app import create_app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    web.run_app(create_app(), host=config.API_HOST, port=config.API_PORT)
