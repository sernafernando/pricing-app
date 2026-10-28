"""
GET /productos/{id}/mercadolibre gates each block by the permission the product
info modal uses to show it:

- productos.ver_info_mercadolibre -> publicaciones_ml (MercadoLibre tab)
- productos.ver_info_ventas       -> ventas (Ventas tab)

The response stays 200 with both keys: the modal loads it when either tab opens.

Publication cases call the endpoint function with a mocked session because its
raw Postgres SQL (`mla = ANY(:mla_ids)`) cannot run on the sqlite test DB (same
approach as test_productos_mercadolibre_lite.py). The user carries the
`_permisos_cache` that `get_current_user` preloads, so the real
`PermisosService.tiene_permiso` decides. Sales cases go through the HTTP
endpoint with real role grants.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.endpoints.productos_detail import obtener_datos_ml_producto
from app.models.ml_venta_metrica import MLVentaMetrica
from tests.conftest import make_access_token

ML = "productos.ver_info_mercadolibre"
VENTAS = "productos.ver_info_ventas"


def _mocked_db() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(mla="MLA9201", item_title="Pub", lista_nombre="Clásica", pricelist_id=4)
    ]
    # every sales window query returns the same stubbed aggregate
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        numero_ventas=3, cantidad_vendida=5, monto_total=Decimal("1234.50")
    )
    empty = MagicMock()
    empty.fetchall.return_value = []
    db.execute.return_value = empty
    return db


def _call(user: SimpleNamespace, db: MagicMock | None = None) -> dict:
    with (
        patch("app.services.ml_webhook_client.ml_webhook_client.get_items_batch", new_callable=AsyncMock) as batch,
        patch("app.api.endpoints.productos_detail.fetch_promo_summary_by_mla", return_value={}),
        patch("app.api.endpoints.productos_detail.fetch_publication_status_by_mla", return_value={}),
    ):
        batch.return_value = {}
        return asyncio.run(obtener_datos_ml_producto(item_id=9201, db=db or _mocked_db(), current_user=user))


SALES_WINDOW = {"cantidad_vendida": 5, "monto_total": 1234.5, "numero_ventas": 3}


def _user(*codigos: str, superadmin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=1, es_superadmin=superadmin, _permisos_cache=set(codigos))


def test_without_ml_permission_publications_are_hidden() -> None:
    assert _call(_user(VENTAS))["publicaciones_ml"] == []


def test_with_ml_permission_publications_are_returned() -> None:
    result = _call(_user(ML))

    assert [p["mla"] for p in result["publicaciones_ml"]] == ["MLA9201"]
    assert result["ventas"] is None


def test_superadmin_gets_publications_and_sales() -> None:
    result = _call(_user(superadmin=True))

    assert [p["mla"] for p in result["publicaciones_ml"]] == ["MLA9201"]
    assert result["ventas"] == {
        "ultimos_7_dias": SALES_WINDOW,
        "ultimos_15_dias": SALES_WINDOW,
        "ultimos_30_dias": SALES_WINDOW,
    }


def test_ventas_permission_returns_sales_of_this_item_only() -> None:
    db = _mocked_db()

    result = _call(_user(VENTAS), db)

    assert result["ventas"]["ultimos_30_dias"] == SALES_WINDOW
    windows = [c for c in db.query.return_value.filter.call_args_list if len(c.args) == 3]
    assert len(windows) == 3
    for window in windows:
        item_filter = window.args[0].compile(compile_kwargs={"literal_binds": True})
        assert str(item_filter) == "ml_ventas_metricas.item_id = 9201"


def test_without_ml_permission_publication_sources_are_not_read() -> None:
    db = _mocked_db()
    with (
        patch("app.api.endpoints.productos_detail.fetch_promo_summary_by_mla") as promos,
        patch("app.api.endpoints.productos_detail.fetch_publication_status_by_mla") as status,
        patch("app.services.ml_webhook_client.ml_webhook_client.get_items_batch", new_callable=AsyncMock) as batch,
    ):
        asyncio.run(obtener_datos_ml_producto(item_id=9201, db=db, current_user=_user(VENTAS)))

    promos.assert_not_called()
    status.assert_not_called()
    batch.assert_not_called()
    db.execute.assert_not_called()


def _get(client, user) -> dict:
    response = client.get(
        "/api/productos/9201/mercadolibre",
        headers={"Authorization": f"Bearer {make_access_token(user)}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _venta(db) -> None:
    db.add(
        MLVentaMetrica(
            id_operacion=1,
            item_id=9201,
            fecha_venta=datetime.now(UTC).replace(tzinfo=None),
            cantidad=2,
            monto_total=5000,
        )
    )
    db.commit()


def test_no_info_permission_gets_200_with_both_blocks_hidden(client, db, active_user) -> None:
    _venta(db)

    data = _get(client, active_user)

    assert data == {"publicaciones_ml": [], "ventas": None}


def test_ventas_permission_sees_sales(client, db, active_user, rol_ventas, grant_permiso) -> None:
    grant_permiso(rol_ventas, VENTAS)
    _venta(db)

    data = _get(client, active_user)

    # sqlite cannot evaluate the CAST(... AS DATE) window, so only the block's presence is asserted here
    assert set(data["ventas"]) == {"ultimos_7_dias", "ultimos_15_dias", "ultimos_30_dias"}
    assert data["publicaciones_ml"] == []


def test_ml_permission_alone_does_not_see_sales(client, db, active_user, rol_ventas, grant_permiso) -> None:
    grant_permiso(rol_ventas, ML)
    _venta(db)

    assert _get(client, active_user)["ventas"] is None


def test_revoked_ventas_override_hides_sales(client, db, active_user, rol_ventas, grant_permiso) -> None:
    from app.models.permiso import Permiso, UsuarioPermisoOverride

    grant_permiso(rol_ventas, VENTAS)
    permiso = db.query(Permiso).filter(Permiso.codigo == VENTAS).one()
    db.add(UsuarioPermisoOverride(usuario_id=active_user.id, permiso_id=permiso.id, concedido=False))
    db.commit()
    _venta(db)

    assert _get(client, active_user)["ventas"] is None
