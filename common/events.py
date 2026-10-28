from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CHANNEL_RECEIPT = "inventory.receipt"
CHANNEL_ISSUE = "inventory.issue"
CHANNELS = (CHANNEL_RECEIPT, CHANNEL_ISSUE)

EventType = Literal["receipt", "issue"]
CHANNEL_BY_TYPE: dict[str, str] = {"receipt": CHANNEL_RECEIPT, "issue": CHANNEL_ISSUE}


class OperationIn(BaseModel):
    """Тело запроса POST /receipts и POST /issues."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0)
    warehouse: str = Field(min_length=1, max_length=64)


class StockEvent(BaseModel):
    """Событие, которое публикуется в Redis."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    type: EventType
    sku: str = Field(min_length=1)
    warehouse: str = Field(min_length=1)
    qty: int = Field(gt=0)
    created_at: datetime

    @property
    def delta(self) -> int:
        return self.qty if self.type == "receipt" else -self.qty
