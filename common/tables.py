import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

metadata = sa.MetaData()

# Журнал складских операций (пишет inventory_api).
stock_events = sa.Table(
    "stock_events",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("event_id", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("sku", sa.Text, nullable=False),
    sa.Column("warehouse", sa.Text, nullable=False),
    sa.Column("qty", sa.Integer, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("type IN ('receipt', 'issue')", name="ck_stock_events_type"),
    sa.CheckConstraint("qty > 0", name="ck_stock_events_qty_positive"),
    sa.Index("ix_stock_events_warehouse_sku", "warehouse", "sku"),
)

# Агрегированные остатки по паре (warehouse, sku) (ведёт analytics_worker).
stock_agg = sa.Table(
    "stock_agg",
    metadata,
    sa.Column("warehouse", sa.Text, primary_key=True),
    sa.Column("sku", sa.Text, primary_key=True),
    sa.Column("qty", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)
