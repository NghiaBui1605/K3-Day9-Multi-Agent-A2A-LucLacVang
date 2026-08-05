"""
Data Loader – loads and caches Olist CSV files, provides join utilities.
All agents use this shared layer to query data.
"""

import pandas as pd
from pathlib import Path
from functools import lru_cache
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"


@lru_cache(maxsize=1)
def _load_all() -> dict[str, pd.DataFrame]:
    """Load all 9 CSV files once and cache them."""
    files = {
        "orders":       "olist_orders_dataset.csv",
        "customers":    "olist_customers_dataset.csv",
        "order_items":  "olist_order_items_dataset.csv",
        "order_payments": "olist_order_payments_dataset.csv",
        "order_reviews":  "olist_order_reviews_dataset.csv",
        "products":     "olist_products_dataset.csv",
        "sellers":      "olist_sellers_dataset.csv",
        "geolocation":  "olist_geolocation_dataset.csv",
        "category_translation": "product_category_name_translation.csv",
    }
    dfs = {}
    for key, fname in files.items():
        path = DATA_DIR / fname
        if path.exists():
            dfs[key] = pd.read_csv(path, low_memory=False)
        else:
            dfs[key] = pd.DataFrame()
    return dfs


def get_order(order_id: str) -> Optional[dict]:
    """Return a single order row as dict, or None if not found."""
    dfs = _load_all()
    orders = dfs["orders"]
    row = orders[orders["order_id"] == order_id]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def get_order_items(order_id: str) -> list[dict]:
    """Return list of order_item dicts for an order."""
    dfs = _load_all()
    items = dfs["order_items"]
    rows = items[items["order_id"] == order_id]
    return rows.to_dict(orient="records")


def get_order_payments(order_id: str) -> list[dict]:
    """Return list of payment dicts for an order."""
    dfs = _load_all()
    payments = dfs["order_payments"]
    rows = payments[payments["order_id"] == order_id]
    return rows.to_dict(orient="records")


def get_seller(seller_id: str) -> Optional[dict]:
    """Return seller info as dict, or None if not found."""
    dfs = _load_all()
    sellers = dfs["sellers"]
    row = sellers[sellers["seller_id"] == seller_id]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def get_order_review(order_id: str) -> Optional[dict]:
    """Return first review for an order, or None."""
    dfs = _load_all()
    reviews = dfs["order_reviews"]
    rows = reviews[reviews["order_id"] == order_id]
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


def get_customer(customer_id: str) -> Optional[dict]:
    """Return customer info as dict, or None."""
    dfs = _load_all()
    customers = dfs["customers"]
    row = customers[customers["customer_id"] == customer_id]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def sample_order_ids(n: int = 50, seed: int = 42) -> list[str]:
    """Sample n order IDs from the dataset with reproducible seed."""
    dfs = _load_all()
    orders = dfs["orders"]
    return orders["order_id"].sample(n=n, random_state=seed).tolist()


def get_all_orders() -> pd.DataFrame:
    """Return the full orders DataFrame."""
    return _load_all()["orders"]


def ts(val) -> Optional[str]:
    """Return string timestamp or None if NaN/NaT."""
    if pd.isna(val):
        return None
    return str(val)
