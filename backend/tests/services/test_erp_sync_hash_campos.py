"""Regression: an isolated ERP field change must reach `productos_erp`.

`sincronizar_erp` gates every column update behind
`producto_existente.hash_datos != hash_nuevo`. `calcular_hash` therefore
defines what the sync is able to SEE — a persisted field missing from it is
invisible forever: the `elif` branch never runs and the `else` branch only
patches `stock`.

Four fields were missing:

- `Moneda_Costo` — reported on item_id 1972: the cost was corrected back to USD
  in the ERP (`curr_id` 1 -> 2, same `coslis_price`) and the app kept showing
  ARS, silently reinterpreting the same number in the wrong currency.
- `Marca` / `Categoría` / `subcat_id` — a recategorization with no price or
  stock movement never propagated. `subcategoria_id` feeds
  `obtener_grupo_subcategoria` -> ML commission -> markup, so the product kept
  pricing against the stale commission group.

No pytest-asyncio in this project — async code is driven with `asyncio.run(...)`
(same convention as test_erp_sync_batch_prefetch.py).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constants import SYSTEM_USERNAME
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.services import erp_sync
from app.services.erp_sync import sincronizar_erp


def _producto(item_id, *, moneda_costo="ARS", coslis_price=158, **overrides):
    """Fixture row mirroring the PRODUCTOS_LOCAL_SQL column keys."""
    return {
        "Item_ID": item_id,
        "Código": "4897098687130",
        "coslis_price": coslis_price,
        "Descripción": "PRODUCTO",
        "Envío": 0,
        "IVA": 21,
        "Precio_Publicado": None,
        "Moneda_Costo": moneda_costo,
        "subcat_id": 1,
        "Categoría": "CAT",
        "Marca": "MARCA",
        **overrides,
    }


def _moneda(row) -> str:
    """`moneda_costo` is a `TipoMoneda` enum on read, a plain str on write."""
    return getattr(row.moneda_costo, "value", row.moneda_costo)


@pytest.fixture()
def sistema_user(db) -> Usuario:
    usuario = Usuario(username=SYSTEM_USERNAME, nombre="Sistema")
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def _run_sync(db, productos, stock_dict):
    """Patch the 3 ERP ingress points so the fixture list is the sole input."""
    with (
        patch.object(erp_sync, "fetch_productos_local", return_value=productos),
        patch.object(erp_sync, "fetch_stock_erp", new=AsyncMock(return_value=stock_dict)),
        patch(
            "app.scripts.sync_price_list_items.sync_price_list_items_incremental",
            new=MagicMock(return_value=None),
        ),
    ):
        return asyncio.run(sincronizar_erp(db))


class TestCalcularHashCubreCadaCampoPersistido:
    """Every field the sync writes must move the hash on its own."""

    @pytest.mark.parametrize(
        ("campo", "valor_nuevo"),
        [
            ("Moneda_Costo", "USD"),
            ("Marca", "OTRA MARCA"),
            ("Categoría", "OTRA CAT"),
            ("subcat_id", 99),
            # Already covered before this fix — pinned so a future rewrite of
            # the field list can't silently drop them.
            ("Código", "0000000000000"),
            ("coslis_price", 200),
            ("Descripción", "OTRO PRODUCTO"),
            ("Envío", 500),
            ("IVA", 10.5),
        ],
    )
    def test_isolated_field_change_changes_the_hash(self, campo, valor_nuevo) -> None:
        base = {**_producto(1972), "Stock": 4}
        cambiado = {**base, campo: valor_nuevo}

        assert base[campo] != valor_nuevo, "el fixture ya traía el valor nuevo"
        assert erp_sync.calcular_hash(base) != erp_sync.calcular_hash(cambiado)

    def test_stock_change_changes_the_hash(self) -> None:
        base = {**_producto(1972), "Stock": 4}

        assert erp_sync.calcular_hash(base) != erp_sync.calcular_hash({**base, "Stock": 5})

    def test_identical_rows_still_hash_equal(self) -> None:
        """The hash stays a pure function of the row — no churn, no re-sync loop."""
        row = {**_producto(1972, moneda_costo="USD"), "Stock": 4}

        assert erp_sync.calcular_hash(row) == erp_sync.calcular_hash({**row})

    def test_adjacent_fields_cannot_be_confused(self) -> None:
        """Concatenating raw values lets `Marca`+`Categoría` = "AB"+"C" collide
        with "A"+"BC". Pinned so the collision is caught if it ever regresses."""
        izquierda = {**_producto(1972, Marca="AB", **{"Categoría": "C"}), "Stock": 4}
        derecha = {**_producto(1972, Marca="A", **{"Categoría": "BC"}), "Stock": 4}

        assert erp_sync.calcular_hash(izquierda) != erp_sync.calcular_hash(derecha)


class TestSyncPropagaCambioDeMoneda:
    """End-to-end: the currency-only flip must land on `productos_erp`."""

    def test_currency_only_flip_updates_moneda_costo(self, db, sistema_user) -> None:
        # Seeded state: what the previous sync persisted while the ERP said ARS.
        stale = _producto(1972, moneda_costo="ARS")
        db.add(
            ProductoERP(
                item_id=1972,
                codigo="4897098687130",
                descripcion="PRODUCTO",
                marca="MARCA",
                categoria="CAT",
                subcategoria_id=1,
                moneda_costo="ARS",
                costo=158,
                iva=21,
                stock=4,
                envio=0,
                hash_datos=erp_sync.calcular_hash({**stale, "Stock": 4}),
            )
        )
        db.commit()

        # ERP now says USD. Nothing else moved: same price, same stock, same
        # description — so ONLY the currency can trigger the update.
        corregido = _producto(1972, moneda_costo="USD")

        stats = _run_sync(db, [corregido], {1972: 4})

        assert stats["errores"] == []
        assert stats["productos_actualizados"] == 1
        assert stats["productos_sin_cambios"] == 0

        row = db.query(ProductoERP).filter(ProductoERP.item_id == 1972).first()
        assert _moneda(row) == "USD"
        assert row.costo == 158

    def test_recategorization_only_updates_marca_categoria_y_subcat(self, db, sistema_user) -> None:
        """`subcategoria_id` feeds the ML commission group, so a stale one
        keeps the product pricing against the wrong markup."""
        stale = _producto(1973)
        db.add(
            ProductoERP(
                item_id=1973,
                codigo="4897098687130",
                descripcion="PRODUCTO",
                marca="MARCA",
                categoria="CAT",
                subcategoria_id=1,
                moneda_costo="ARS",
                costo=158,
                iva=21,
                stock=4,
                envio=0,
                hash_datos=erp_sync.calcular_hash({**stale, "Stock": 4}),
            )
        )
        db.commit()

        recategorizado = _producto(1973, Marca="NUEVA MARCA", **{"Categoría": "NUEVA CAT", "subcat_id": 99})

        stats = _run_sync(db, [recategorizado], {1973: 4})

        assert stats["errores"] == []
        assert stats["productos_actualizados"] == 1

        row = db.query(ProductoERP).filter(ProductoERP.item_id == 1973).first()
        assert row.marca == "NUEVA MARCA"
        assert row.categoria == "NUEVA CAT"
        assert row.subcategoria_id == 99
