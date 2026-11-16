"""The 5-minute ERP master tables sync seeds the categories, subcategories and brands masters right after it refreshes
`tb_category`, `tb_subcategory` and `tb_brand`, so a category or brand new in GBP shows up in the ABM (abm-productos
delivery 2+3)."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.scripts import sync_erp_master_tables_incremental as script


class _NoClose:
    def __init__(self, session) -> None:
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self) -> None:
        pass


def test_the_incremental_sync_seeds_the_masters(db, monkeypatch) -> None:
    async def fake_categories(session) -> dict:
        session.execute(text("INSERT INTO tb_category (comp_id, cat_id, cat_desc) VALUES (1, 46, 'CONECTIVIDAD')"))
        return {"nuevos": 1, "actualizados": 0}

    async def noop(*_args, **_kwargs) -> dict:
        return {}

    monkeypatch.setattr(script, "SessionLocal", lambda: _NoClose(db))
    monkeypatch.setattr(script, "sync_categories", fake_categories)
    for name in ("sync_brands", "sync_subcategories", "sync_tax_names", "sync_item_taxes_for_items"):
        monkeypatch.setattr(script, name, noop)
    monkeypatch.setattr(script, "sync_items_incremental", lambda *_a, **_k: noop())
    monkeypatch.setattr(script, "verificar_items_faltantes", noop)

    asyncio.run(script.main_async())

    assert db.execute(text("SELECT id FROM producto_categorias")).scalars().all() == [46]
