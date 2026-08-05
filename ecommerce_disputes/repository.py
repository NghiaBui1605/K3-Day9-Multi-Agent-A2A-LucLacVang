from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .models import Item, Order, Payment, money, timestamp


class DataError(RuntimeError):
    pass


class OlistRepository:
    """Read-only, order-scoped indexes over the three policy-relevant CSVs."""

    def __init__(self, data_dir: Path, order_ids: Iterable[str]):
        self.data_dir = data_dir
        self.requested_order_ids = set(order_ids)
        self.orders: dict[str, Order] = {}
        self.items: dict[str, list[Item]] = {}
        self.payments: dict[str, list[Payment]] = {}
        self.known_sellers: set[str] = set()
        self._load()

    def _rows(self, name: str):
        path = self.data_dir / name
        if not path.is_file():
            raise DataError(f"Missing dataset: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)

    def _load(self) -> None:
        for row in self._rows("olist_orders_dataset.csv"):
            order_id = row["order_id"]
            if order_id in self.requested_order_ids:
                self.orders[order_id] = Order(
                    order_id=order_id,
                    status=row["order_status"],
                    delivered_carrier_at=timestamp(row["order_delivered_carrier_date"]),
                    delivered_customer_at=timestamp(row["order_delivered_customer_date"]),
                    estimated_delivery_at=timestamp(row["order_estimated_delivery_date"]),
                )

        for row in self._rows("olist_order_items_dataset.csv"):
            order_id = row["order_id"]
            if order_id in self.requested_order_ids:
                item = Item(
                    order_id=order_id,
                    item_id=int(row["order_item_id"]),
                    seller_id=row["seller_id"],
                    shipping_limit_at=timestamp(row["shipping_limit_date"]),  # type: ignore[arg-type]
                    price=money(row["price"]),
                    freight=money(row["freight_value"]),
                )
                self.items.setdefault(order_id, []).append(item)

        for row in self._rows("olist_order_payments_dataset.csv"):
            order_id = row["order_id"]
            if order_id in self.requested_order_ids:
                payment = Payment(
                    order_id=order_id,
                    sequential=int(row["payment_sequential"]),
                    value=money(row["payment_value"]),
                )
                self.payments.setdefault(order_id, []).append(payment)

        for row in self._rows("olist_sellers_dataset.csv"):
            self.known_sellers.add(row["seller_id"])

        for values in self.items.values():
            values.sort(key=lambda item: item.item_id)
        for values in self.payments.values():
            values.sort(key=lambda payment: payment.sequential)

        missing = self.requested_order_ids - self.orders.keys()
        if missing:
            raise DataError(f"Orders not found: {', '.join(sorted(missing))}")

    def order(self, order_id: str) -> Order:
        try:
            return self.orders[order_id]
        except KeyError as exc:
            raise DataError(f"Order not found: {order_id}") from exc

    def order_items(self, order_id: str) -> tuple[Item, ...]:
        return tuple(self.items.get(order_id, ()))

    def order_payments(self, order_id: str) -> tuple[Payment, ...]:
        return tuple(self.payments.get(order_id, ()))
