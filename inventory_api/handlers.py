import json
import logging

from aiohttp import web
from pydantic import ValidationError

from common.events import CHANNEL_BY_TYPE, OperationIn, StockEvent
from inventory_api import queries

log = logging.getLogger(__name__)
routes = web.RouteTableDef()


def json_error(status: int, message: str, **extra) -> web.Response:
    return web.json_response({"error": message, **extra}, status=status)


async def _read_operation(request: web.Request) -> OperationIn:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "invalid JSON"}), content_type="application/json"
        )
    try:
        return OperationIn.model_validate(payload)
    except ValidationError as e:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "validation error", "details": e.errors(include_url=False)},
                            default=str),
            content_type="application/json",
        )


async def _publish(request: web.Request, event: StockEvent) -> None:
    redis = request.app["redis"]
    await redis.publish(CHANNEL_BY_TYPE[event.type], event.model_dump_json())


async def _create_operation(request: web.Request, type_: str) -> web.Response:
    op = await _read_operation(request)
    engine = request.app["engine"]

    async with engine.begin() as conn:
        if type_ == "issue":
            await queries.lock_pair(conn, op.warehouse, op.sku)
            balance = await queries.get_balance(conn, op.warehouse, op.sku)
            if balance < op.qty:
                return json_error(409, "insufficient stock", available=balance)
        row = await queries.insert_event(
            conn, type_=type_, sku=op.sku, warehouse=op.warehouse, qty=op.qty
        )

    # Публикуем только после коммита, чтобы воркер не увидел несохранённую операцию.
    event = StockEvent.model_validate(row)
    await _publish(request, event)
    return web.json_response(json.loads(event.model_dump_json()), status=201)


@routes.post("/receipts")
async def create_receipt(request: web.Request) -> web.Response:
    return await _create_operation(request, "receipt")


@routes.post("/issues")
async def create_issue(request: web.Request) -> web.Response:
    return await _create_operation(request, "issue")


@routes.get("/stock")
async def get_stock(request: web.Request) -> web.Response:
    warehouse = request.query.get("warehouse")
    if not warehouse:
        return json_error(400, "query parameter 'warehouse' is required")
    sku = request.query.get("sku") or None

    async with request.app["engine"].connect() as conn:
        items = await queries.get_stock(conn, warehouse, sku)
    return web.json_response({"warehouse": warehouse, "items": items})


@routes.get("/stock/summary")
async def get_summary(request: web.Request) -> web.Response:
    raw = request.query.get("top_n", "5")
    try:
        top_n = int(raw)
    except ValueError:
        return json_error(400, "top_n must be an integer")
    if not 1 <= top_n <= 100:
        return json_error(400, "top_n must be between 1 and 100")

    async with request.app["engine"].connect() as conn:
        summary = await queries.get_summary(conn, top_n)
    return web.json_response(summary)
