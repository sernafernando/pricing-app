"""RED→GREEN — manual price-edit endpoints tag producto_precio_origen(origen='manual').

Slice 2 of promo-price-propagation: /precios/set, /precios/set-rapido and
/precios/set-cuota must, after a successful write, upsert a
producto_precio_origen row (origen='manual') for each column they wrote.
The price-write behavior itself must not change (existing pricing tests
stay green — this file only asserts the *additional* tagging side effect).

Heavy pricing-calculation dependencies (commission tables, envio resolver)
are patched to fixed values so tests don't need to build the full comision
versioning fixture chain — only the origen-tagging side effect is under
test here.
"""

from unittest.mock import patch

from app.models.producto import ProductoERP, TipoMoneda
from app.models.producto_precio_origen import ProductoPrecioOrigen


def _make_producto(db, item_id: int = 2001) -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo=f"COD{item_id}",
        descripcion="Producto de prueba",
        subcategoria_id=1,
        costo=1000.0,
        moneda_costo=TipoMoneda.ARS,
        iva=21.0,
    )
    db.add(producto)
    db.commit()
    return producto


def _origen_rows(db, item_id):
    return {
        r.column_key: r
        for r in db.query(ProductoPrecioOrigen).filter(ProductoPrecioOrigen.item_id == item_id).all()
    }


class _PatchedPricingDeps:
    """Context manager patching the heavy pricing-calc dependencies to fixed values.

    /precios/set-rapido re-imports obtener_grupo_subcategoria/obtener_comision_base
    locally (inside the function body), shadowing the module-level names bound in
    app.api.endpoints.pricing at import time. So each dependency is patched both at
    its source module (app.services.pricing_calculator) — for that local re-import —
    and at app.api.endpoints.pricing's own namespace — for the endpoints that only
    reference the top-level imported name (set, set-cuota).
    """

    def __enter__(self):
        self._patches = [
            patch("app.services.pricing_calculator.obtener_grupo_subcategoria", return_value=1),
            patch("app.services.pricing_calculator.obtener_comision_base", return_value=15.0),
            patch("app.api.endpoints.pricing.obtener_grupo_subcategoria", return_value=1),
            patch("app.api.endpoints.pricing.obtener_comision_base", return_value=15.0),
            patch("app.api.endpoints.pricing.resolver_costo_envio", return_value=0.0),
            patch("app.api.endpoints.pricing.calcular_precio_producto", return_value={"precio": 500.0}),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class TestSetPrecioTagsManualOrigen:
    def test_set_tags_clasica_and_cuotas_as_manual(self, client, auth_headers, db):
        _make_producto(db)
        with _PatchedPricingDeps():
            response = client.post(
                "/api/precios/set",
                json={"item_id": 2001, "precio_lista_ml": 1200.0},
                headers=auth_headers,
            )
        assert response.status_code == 200

        rows = _origen_rows(db, 2001)
        assert "precio_lista_ml" in rows
        assert rows["precio_lista_ml"].origen == "manual"
        for cuota_col in ("precio_3_cuotas", "precio_6_cuotas", "precio_9_cuotas", "precio_12_cuotas"):
            assert cuota_col in rows, f"{cuota_col} should be tagged manual (auto-calculated cuota)"
            assert rows[cuota_col].origen == "manual"


class TestSetRapidoTagsManualOrigen:
    def test_set_rapido_web_tags_clasica_and_cascaded_cuotas(self, client, auth_headers, db):
        _make_producto(db, item_id=2002)
        with _PatchedPricingDeps():
            response = client.post(
                "/api/precios/set-rapido",
                params={"item_id": 2002, "precio": 1200.0, "recalcular_cuotas": True, "lista_tipo": "web"},
                headers=auth_headers,
            )
        assert response.status_code == 200

        rows = _origen_rows(db, 2002)
        assert rows["precio_lista_ml"].origen == "manual"
        for cuota_col in ("precio_3_cuotas", "precio_6_cuotas", "precio_9_cuotas", "precio_12_cuotas"):
            assert rows[cuota_col].origen == "manual"

    def test_set_rapido_pvp_tags_pvp_columns(self, client, auth_headers, db):
        _make_producto(db, item_id=2003)
        with _PatchedPricingDeps():
            response = client.post(
                "/api/precios/set-rapido",
                params={"item_id": 2003, "precio": 1200.0, "recalcular_cuotas": True, "lista_tipo": "pvp"},
                headers=auth_headers,
            )
        assert response.status_code == 200

        rows = _origen_rows(db, 2003)
        assert rows["precio_pvp"].origen == "manual"
        for cuota_col in (
            "precio_pvp_3_cuotas",
            "precio_pvp_6_cuotas",
            "precio_pvp_9_cuotas",
            "precio_pvp_12_cuotas",
        ):
            assert rows[cuota_col].origen == "manual"


class TestSetCuotaTagsManualOrigen:
    def test_set_cuota_clasica_web_tags_precio_lista_ml(self, client, auth_headers, db):
        _make_producto(db, item_id=2004)
        with _PatchedPricingDeps():
            response = client.post(
                "/api/precios/set-cuota",
                params={"item_id": 2004, "tipo_cuota": "clasica", "precio": 1200.0, "lista_tipo": "web"},
                headers=auth_headers,
            )
        assert response.status_code == 200

        rows = _origen_rows(db, 2004)
        assert rows["precio_lista_ml"].origen == "manual"

    def test_set_cuota_3_web_tags_precio_3_cuotas_only(self, client, auth_headers, db):
        _make_producto(db, item_id=2005)
        with _PatchedPricingDeps():
            response = client.post(
                "/api/precios/set-cuota",
                params={"item_id": 2005, "tipo_cuota": "3", "precio": 1200.0, "lista_tipo": "web"},
                headers=auth_headers,
            )
        assert response.status_code == 200

        rows = _origen_rows(db, 2005)
        assert list(rows.keys()) == ["precio_3_cuotas"]
        assert rows["precio_3_cuotas"].origen == "manual"

    def test_set_cuota_pvp_tags_precio_pvp(self, client, auth_headers, db):
        _make_producto(db, item_id=2006)
        with _PatchedPricingDeps():
            response = client.post(
                "/api/precios/set-cuota",
                params={"item_id": 2006, "tipo_cuota": "clasica", "precio": 1200.0, "lista_tipo": "pvp"},
                headers=auth_headers,
            )
        assert response.status_code == 200

        rows = _origen_rows(db, 2006)
        assert rows["precio_pvp"].origen == "manual"
