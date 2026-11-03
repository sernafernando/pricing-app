"""Pin `_load_work_items` SQL filters (linked pubs require item_id)."""

from __future__ import annotations

from app.services.publicacion_repair import envio as envio_mod
from app.services.publicacion_repair import sku as sku_mod


class _FilterCapture:
    """Minimal query chain stand-in that records `.filter(...)` criteria."""

    def __init__(self) -> None:
        self.criteria: list[object] = []

    def query(self, *args, **kwargs):  # noqa: ANN001, ANN003
        return self

    def join(self, *args, **kwargs):  # noqa: ANN001, ANN003
        return self

    def filter(self, *criteria):  # noqa: ANN001
        self.criteria.extend(criteria)
        return self

    def all(self) -> list:
        return []


def _criterion_sql(criterion: object) -> str:
    return str(criterion).replace('"', "").lower()


def test_envio_load_work_items_requires_item_id() -> None:
    db = _FilterCapture()
    envio_mod._load_work_items(db)  # type: ignore[arg-type]
    sqls = [_criterion_sql(c) for c in db.criteria]
    assert any("item_id" in s and "is not null" in s for s in sqls), sqls


def test_sku_load_work_items_requires_item_id() -> None:
    db = _FilterCapture()
    sku_mod._load_work_items(db)  # type: ignore[arg-type]
    sqls = [_criterion_sql(c) for c in db.criteria]
    assert any("item_id" in s and "is not null" in s for s in sqls), sqls
