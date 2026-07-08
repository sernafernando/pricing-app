"""Batch-prefetch regression + query-count tests for `sincronizar_erp`.

Scope: only the two in-loop `.first()` lookups (ProductoERP by item_id,
ProductoPricing by item_id) become per-batch prefetch dicts. Site 3
(pricing-calc lookups: tipo_cambio, subcategoria_grupo, comision) stays out
of scope and is excluded from the query-count assertions.

No pytest-asyncio in this project (see
tests/unit/test_sync_stock_por_deposito.py) — async code is driven with
`asyncio.run(...)`.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constants import SYSTEM_USERNAME
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from app.services import erp_sync
from app.services.erp_sync import sincronizar_erp


def _producto(
    item_id,
    *,
    codigo="COD1",
    descripcion="DESC",
    envio=0,
    iva=21,
    precio_publicado=None,
    moneda_costo="ARS",
    subcat_id=1,
    coslis_price=100,
):
    """Build a fixture row mirroring PRODUCTOS_LOCAL_SQL column keys."""
    return {
        "Item_ID": item_id,
        "Código": codigo,
        "coslis_price": coslis_price,
        "Descripción": descripcion,
        "Envío": envio,
        "IVA": iva,
        "Precio_Publicado": precio_publicado,
        "Moneda_Costo": moneda_costo,
        "subcat_id": subcat_id,
        "Categoría": "CAT",
        "Marca": "MARCA",
    }


@pytest.fixture()
def sistema_user(db) -> Usuario:
    """Seed the system user required by `get_system_user_id`."""
    usuario = Usuario(username=SYSTEM_USERNAME, nombre="Sistema")
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def _patch_ingress(productos, stock_dict):
    """Patch the 3 ERP ingress points so the fixture list is the sole input."""
    return (
        patch.object(erp_sync, "fetch_productos_local", return_value=productos),
        patch.object(erp_sync, "fetch_stock_erp", new=AsyncMock(return_value=stock_dict)),
        patch(
            "app.scripts.sync_price_list_items.sync_price_list_items_incremental",
            new=MagicMock(return_value=None),
        ),
    )


def _run_sync(db, productos, stock_dict, sistema_user):
    p1, p2, p3 = _patch_ingress(productos, stock_dict)
    with p1, p2, p3:
        return asyncio.run(sincronizar_erp(db))


class TestBatchPrefetchQueryCount:
    """Test 1 (design §6.4): bounded per-batch query count.

    MUST fail RED on current (pre-prefetch) code — counts scale with the
    number of rows in the batch instead of staying flat at `num_batches`.
    """

    def test_single_batch_flat_query_count(self, db, query_counter, sistema_user):
        productos = [_producto(100 + i) for i in range(5)]
        stock_dict = {p["Item_ID"]: 10 for p in productos}

        with query_counter() as counter:
            stats = _run_sync(db, productos, stock_dict, sistema_user)

        assert stats["errores"] == []
        assert counter.matching("productos_erp") == 1
        assert counter.matching("productos_pricing") == 1

    def test_multi_batch_flat_query_count(self, db, query_counter, sistema_user):
        # 150 unique products -> batch_size=100 -> 2 batches (100 + 50).
        productos = [_producto(1000 + i) for i in range(150)]
        stock_dict = {p["Item_ID"]: 5 for p in productos}

        with query_counter() as counter:
            stats = _run_sync(db, productos, stock_dict, sistema_user)

        assert stats["errores"] == []
        num_batches = 2
        assert counter.matching("productos_erp") == num_batches
        assert counter.matching("productos_pricing") == num_batches


class TestBatchPrefetchStatsSnapshot:
    """Test 2 (design §6.5): byte-identical stats/DB-state regression pin.

    Must pass BOTH before and after the prefetch edit (baseline capture).
    """

    def test_all_branches_stats_and_rows_snapshot(self, db, sistema_user):
        # 1. New product (no pricing) -> productos_nuevos.
        nuevo = _producto(5001, codigo="NEW1", descripcion="Nuevo Producto")

        # 2. Changed-hash product: pre-seed with different data.
        cambiado = _producto(5002, codigo="UPD1", descripcion="Actualizado", coslis_price=200)
        db.add(
            ProductoERP(
                item_id=5002,
                codigo="OLD1",
                descripcion="Viejo",
                marca="MARCA",
                categoria="CAT",
                subcategoria_id=1,
                moneda_costo="ARS",
                costo=50,
                iva=21,
                stock=10,
                envio=0,
                hash_datos="stale-hash",
            )
        )

        # 3. Stock-only change: same hash-relevant fields, different stock.
        stock_only = _producto(5003, codigo="STK1", descripcion="Stock Only")
        hash_stock_only = erp_sync.calcular_hash({**stock_only, "Stock": 10})
        db.add(
            ProductoERP(
                item_id=5003,
                codigo="STK1",
                descripcion="Stock Only",
                marca="MARCA",
                categoria="CAT",
                subcategoria_id=1,
                moneda_costo="ARS",
                costo=100,
                iva=21,
                stock=10,
                envio=0,
                hash_datos=hash_stock_only,
            )
        )

        # 4. Unchanged product: same hash-relevant fields, same stock.
        sin_cambios = _producto(5004, codigo="SC1", descripcion="Sin Cambios")
        hash_sin_cambios = erp_sync.calcular_hash({**sin_cambios, "Stock": 7})
        db.add(
            ProductoERP(
                item_id=5004,
                codigo="SC1",
                descripcion="Sin Cambios",
                marca="MARCA",
                categoria="CAT",
                subcategoria_id=1,
                moneda_costo="ARS",
                costo=100,
                iva=21,
                stock=7,
                envio=0,
                hash_datos=hash_sin_cambios,
            )
        )

        # 5. New pricing row: existing product, Precio_Publicado > 0, no pricing yet.
        con_precio = _producto(5005, codigo="PR1", descripcion="Con Precio", precio_publicado=1000)
        hash_con_precio = erp_sync.calcular_hash({**con_precio, "Stock": 3})
        db.add(
            ProductoERP(
                item_id=5005,
                codigo="PR1",
                descripcion="Con Precio",
                marca="MARCA",
                categoria="CAT",
                subcategoria_id=1,
                moneda_costo="ARS",
                costo=100,
                iva=21,
                stock=3,
                envio=0,
                hash_datos=hash_con_precio,
            )
        )
        db.commit()

        productos = [nuevo, cambiado, stock_only, sin_cambios, con_precio]
        stock_dict = {
            5001: 1,
            5002: 10,
            5003: 20,  # different from seeded stock=10 -> stock-only update
            5004: 7,  # same as seeded stock=7 -> unchanged
            5005: 3,  # same as seeded stock=3 -> stock unchanged for this row
        }

        stats = _run_sync(db, productos, stock_dict, sistema_user)

        assert stats == {
            "productos_nuevos": 1,
            "productos_actualizados": 2,
            # 5004 (sin_cambios) + 5005 (con_precio, hash+stock unchanged too).
            "productos_sin_cambios": 2,
            "productos_duplicados": 0,
            "precios_sincronizados": 1,
            "errores": [],
        }

        # Row-level pin.
        nuevo_row = db.query(ProductoERP).filter(ProductoERP.item_id == 5001).first()
        assert nuevo_row is not None
        assert nuevo_row.codigo == "NEW1"
        assert nuevo_row.stock == 1

        cambiado_row = db.query(ProductoERP).filter(ProductoERP.item_id == 5002).first()
        assert cambiado_row.codigo == "UPD1"
        assert cambiado_row.descripcion == "Actualizado"
        assert cambiado_row.costo == 200
        assert cambiado_row.hash_datos != "stale-hash"

        stock_only_row = db.query(ProductoERP).filter(ProductoERP.item_id == 5003).first()
        assert stock_only_row.stock == 20

        sin_cambios_row = db.query(ProductoERP).filter(ProductoERP.item_id == 5004).first()
        assert sin_cambios_row.stock == 7

        pricing_row = db.query(ProductoPricing).filter(ProductoPricing.item_id == 5005).first()
        assert pricing_row is not None
        assert pricing_row.precio_lista_ml == 1000
        assert pricing_row.motivo_cambio == "Sincronización ERP - Inicial"

    def test_falsy_item_id_is_skipped(self, db, sistema_user):
        """A3: a row with a falsy Item_ID must be skipped like current code."""
        falsy = _producto(0, codigo="FALSY")
        valido = _producto(6001, codigo="OK1")
        stock_dict = {0: 1, 6001: 1}

        stats = _run_sync(db, [falsy, valido], stock_dict, sistema_user)

        assert stats["errores"] == []
        assert stats["productos_nuevos"] == 1
        assert db.query(ProductoERP).filter(ProductoERP.item_id == 0).first() is None
