"""
Map a GBP `scriptItem` row onto `tb_item`.

Every item sync (full, incremental, missing-items, the `/erp-sync/items` endpoint) writes through here, so they all
keep the same columns: the hand-picked fields, the dimensions and website images, and the whole row in `raw`.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from sqlalchemy.orm import Session

from app.models.tb_item import TBItem

DIMENSION_FIELDS = ("item_weight", "item_volume", "item_wide", "item_large", "item_higth")
IMAGE_FIELDS = tuple(f"item_WebSite_url4Image{i}" for i in range(1, 11))
TEXT_FIELDS = ("item_code", "item_desc", "item_liquidation", *IMAGE_FIELDS)
INT_FIELDS = ("comp_id", "item_id", "cat_id", "subcat_id", "brand_id")
DATE_FIELDS = ("item_cd", "item_LastUpdate", "item_lastUpdate_byProcess")

UpsertResult = Literal["nuevo", "actualizado", "sin_cambios"]


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _to_datetime(value: Any) -> Optional[datetime]:
    """Naive datetime, like the `DateTime` columns store (an offset is dropped, as Postgres does for them)."""
    if not value:
        return None
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return value.replace(tzinfo=None)


def _to_bool(value: Any) -> Optional[bool]:
    """item_expser is a BIT in SQL Server (0/1, sometimes "true"/"false")."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("true", "false"):
        return str(value).lower() == "true"
    as_int = _to_int(value)
    return bool(as_int) if as_int is not None else None


def tb_item_values(row: dict[str, Any]) -> dict[str, Any]:
    """Column values for `tb_item` from one scriptItem row, only for the keys the row carries.

    A source that sends fewer columns (an older script, the ERP worker) must not wipe what another sync stored.
    `raw` is set to the row here; `upsert_tb_item` merges it over the stored one.
    """
    converters: dict[str, Any] = {
        **{name: _to_int for name in INT_FIELDS},
        **{name: (lambda value: value) for name in TEXT_FIELDS},
        **{name: _to_datetime for name in DATE_FIELDS},
        **{name: _to_decimal for name in DIMENSION_FIELDS},
        "item_expser": _to_bool,
    }
    values = {name: convert(row[name]) for name, convert in converters.items() if name in row}
    values["raw"] = dict(row)
    return values


def upsert_tb_item(db: Session, row: dict[str, Any], only_insert: bool = False) -> UpsertResult:
    """Insert or update one `tb_item` from a scriptItem row; any changed column counts as an update.

    With `only_insert`, an item that already exists is left untouched.
    """
    values = tb_item_values(row)
    existing = db.query(TBItem).filter(TBItem.comp_id == values["comp_id"], TBItem.item_id == values["item_id"]).first()
    if existing is None:
        db.add(TBItem(**values))
        return "nuevo"
    if only_insert:
        return "sin_cambios"

    values["raw"] = {**(existing.raw or {}), **values["raw"]}
    changed = {name: value for name, value in values.items() if getattr(existing, name) != value}
    if not changed:
        return "sin_cambios"
    for name, value in changed.items():
        setattr(existing, name, value)
    return "actualizado"
