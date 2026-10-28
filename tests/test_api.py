import asyncio
import json

from common.events import CHANNEL_RECEIPT


async def post(client, path, sku="A-100", qty=10, warehouse="WH-1"):
    return await client.post(path, json={"sku": sku, "qty": qty, "warehouse": warehouse})


async def test_receipt_and_issue_change_stock(client):
    resp = await post(client, "/receipts", qty=50)
    assert resp.status == 201
    body = await resp.json()
    assert body["type"] == "receipt" and body["qty"] == 50 and body["event_id"]

    resp = await post(client, "/issues", qty=20)
    assert resp.status == 201

    resp = await client.get("/stock", params={"warehouse": "WH-1"})
    assert resp.status == 200
    assert await resp.json() == {"warehouse": "WH-1", "items": [{"sku": "A-100", "qty": 30}]}


async def test_stock_filter_by_sku(client):
    await post(client, "/receipts", sku="A-100", qty=5)
    await post(client, "/receipts", sku="B-200", qty=7)
    await post(client, "/receipts", sku="B-200", qty=1, warehouse="WH-2")

    resp = await client.get("/stock", params={"warehouse": "WH-1", "sku": "B-200"})
    assert (await resp.json())["items"] == [{"sku": "B-200", "qty": 7}]


async def test_issue_more_than_available_is_rejected(client):
    await post(client, "/receipts", qty=5)
    resp = await post(client, "/issues", qty=6)
    assert resp.status == 409
    assert (await resp.json())["available"] == 5


async def test_invalid_body(client):
    resp = await client.post("/receipts", json={"sku": "A-100", "qty": -1, "warehouse": "WH-1"})
    assert resp.status == 400
    resp = await client.post("/receipts", data="not json")
    assert resp.status == 400
    resp = await client.get("/stock")
    assert resp.status == 400


async def test_summary(client):
    await post(client, "/receipts", sku="A", qty=10, warehouse="WH-1")
    await post(client, "/receipts", sku="B", qty=3, warehouse="WH-1")
    await post(client, "/receipts", sku="C", qty=4, warehouse="WH-1")
    await post(client, "/issues", sku="C", qty=4, warehouse="WH-1")  # C на WH-1 = 0
    await post(client, "/receipts", sku="B", qty=20, warehouse="WH-2")

    resp = await client.get("/stock/summary", params={"top_n": 2})
    assert resp.status == 200
    assert await resp.json() == {
        "warehouses": [
            {"warehouse": "WH-1", "total_qty": 13, "sku_count": 2},
            {"warehouse": "WH-2", "total_qty": 20, "sku_count": 1},
        ],
        "top_skus": [{"sku": "B", "total_qty": 23}, {"sku": "A", "total_qty": 10}],
    }

    resp = await client.get("/stock/summary", params={"top_n": "abc"})
    assert resp.status == 400


async def test_receipt_publishes_event(client, redis):
    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(CHANNEL_RECEIPT)
    try:
        await post(client, "/receipts", qty=3)
        msg = None
        for _ in range(20):  # первый вызов может вернуть подтверждение подписки
            msg = await pubsub.get_message(timeout=0.1)
            if msg is not None:
                break
            await asyncio.sleep(0)
        assert msg is not None
        event = json.loads(msg["data"])
        assert event["sku"] == "A-100" and event["qty"] == 3 and event["type"] == "receipt"
    finally:
        await pubsub.aclose()
