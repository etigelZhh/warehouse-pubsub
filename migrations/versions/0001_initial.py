"""initial: stock_events, stock_agg

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("sku", sa.Text, nullable=False),
        sa.Column("warehouse", sa.Text, nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('receipt', 'issue')", name="ck_stock_events_type"),
        sa.CheckConstraint("qty > 0", name="ck_stock_events_qty_positive"),
    )
    op.create_index("ix_stock_events_warehouse_sku", "stock_events", ["warehouse", "sku"])

    op.create_table(
        "stock_agg",
        sa.Column("warehouse", sa.Text, primary_key=True),
        sa.Column("sku", sa.Text, primary_key=True),
        sa.Column("qty", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stock_agg")
    op.drop_index("ix_stock_events_warehouse_sku", table_name="stock_events")
    op.drop_table("stock_events")
