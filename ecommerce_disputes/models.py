from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def money(value: str | Decimal | int = ZERO) -> Decimal:
    """Convert a CSV value to BRL rounded with commercial half-up rounding."""
    if value in (None, ""):
        return ZERO
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    opened_at: str
    claimed_order_id: str
    policy_version: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CaseInput":
        request = data.get("customer_request") or {}
        return cls(
            case_id=str(data.get("case_id", "")),
            opened_at=str(data.get("opened_at", "")),
            claimed_order_id=str(request.get("claimed_order_id", "")),
            policy_version=str(data.get("policy_version", "")),
        )


@dataclass(frozen=True)
class Order:
    order_id: str
    status: str
    delivered_carrier_at: datetime | None
    delivered_customer_at: datetime | None
    estimated_delivery_at: datetime | None


@dataclass(frozen=True)
class Item:
    order_id: str
    item_id: int
    seller_id: str
    shipping_limit_at: datetime
    price: Decimal
    freight: Decimal


@dataclass(frozen=True)
class Payment:
    order_id: str
    sequential: int
    value: Decimal


@dataclass(frozen=True)
class OrderFinding:
    order: Order
    items: tuple[Item, ...]
    violating_items: tuple[Item, ...]

    @property
    def seller_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.seller_id for item in self.items))

    @property
    def violating_seller_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.seller_id for item in self.violating_items))


@dataclass(frozen=True)
class PaymentFinding:
    payments: tuple[Payment, ...]
    item_total: Decimal
    freight_total: Decimal
    payment_total: Decimal
    reconciled: bool


@dataclass(frozen=True)
class DeliveryFinding:
    delivered_late: bool


@dataclass(frozen=True)
class Decision:
    primary_issue: str
    root_cause: str
    responsible_parties: tuple[tuple[str, str], ...]
    refund: Decimal
    action: str
