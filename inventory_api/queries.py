"""SQLAlchemy Core запросы сервиса inventory_api."""

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from common.tables import stock_events

# +qty для поступления, -qty для расхода.
signed_qty = sa.case(
    (stock_events.c.type == "receipt", stock_events.c.qty),
    else_=-stock_events.c.qty,
)


def balances_subquery() -> sa.Subquery:
    """Остатки по каждой паре (warehouse, sku): GROUP BY по журналу операций."""
    return (
        sa.select(
            stock_events.c.warehouse,
            stock_events.c.sku,
            sa.func.sum(signed_qty).label("qty"),
        )
        .group_by(stock_events.c.warehouse, stock_events.c.sku)
        .subquery("balances")
    )


async def insert_event(
    conn: AsyncConnection, *, type_: str, sku: str, warehouse: str, qty: int
) -> dict:
    stmt = (
        sa.insert(stock_events)
        .values(event_id=uuid.uuid4(), type=type_, sku=sku, warehouse=warehouse, qty=qty)
        .returning(
            stock_events.c.event_id,
            stock_events.c.type,
            stock_events.c.sku,
            stock_events.c.warehouse,
            stock_events.c.qty,
            stock_events.c.created_at,
        )
    )
    row = (await conn.execute(stmt)).mappings().one()
    return dict(row)


async def lock_pair(conn: AsyncConnection, warehouse: str, sku: str) -> None:
    """Транзакционная блокировка пары, чтобы параллельные расходы не ушли в минус."""
    key = sa.func.hashtext(sa.literal(f"{warehouse}:{sku}"))
    await conn.execute(sa.select(sa.func.pg_advisory_xact_lock(key)))


async def get_balance(conn: AsyncConnection, warehouse: str, sku: str) -> int:
    stmt = sa.select(sa.func.coalesce(sa.func.sum(signed_qty), 0)).where(
        stock_events.c.warehouse == warehouse, stock_events.c.sku == sku
    )
    return int((await conn.execute(stmt)).scalar_one())


async def get_stock(conn: AsyncConnection, warehouse: str, sku: str | None = None) -> list[dict]:
    stmt = (
        sa.select(stock_events.c.sku, sa.func.sum(signed_qty).label("qty"))
        .where(stock_events.c.warehouse == warehouse)
        .group_by(stock_events.c.sku)
        .order_by(stock_events.c.sku)
    )
    if sku is not None:
        stmt = stmt.where(stock_events.c.sku == sku)
    rows = (await conn.execute(stmt)).mappings().all()
    return [{"sku": r["sku"], "qty": int(r["qty"])} for r in rows]


async def get_summary(conn: AsyncConnection, top_n: int) -> dict:
    balances = balances_subquery()

    warehouses_stmt = (
        sa.select(
            balances.c.warehouse,
            sa.func.sum(balances.c.qty).label("total_qty"),
            sa.func.count().filter(balances.c.qty > 0).label("sku_count"),
        )
        .group_by(balances.c.warehouse)
        .order_by(balances.c.warehouse)
    )

    total_qty = sa.func.sum(balances.c.qty).label("total_qty")
    top_skus_stmt = (
        sa.select(balances.c.sku, total_qty)
        .group_by(balances.c.sku)
        .order_by(total_qty.desc(), balances.c.sku)
        .limit(top_n)
    )

    warehouses = (await conn.execute(warehouses_stmt)).mappings().all()
    top_skus = (await conn.execute(top_skus_stmt)).mappings().all()
    return {
        "warehouses": [
            {
                "warehouse": r["warehouse"],
                "total_qty": int(r["total_qty"]),
                "sku_count": int(r["sku_count"]),
            }
            for r in warehouses
        ],
        "top_skus": [{"sku": r["sku"], "total_qty": int(r["total_qty"])} for r in top_skus],
    }
