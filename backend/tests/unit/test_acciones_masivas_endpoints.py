from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.endpoints.pricing import (
    AplicarMarkupMasivoRequest,
    aplicar_markup_masivo,
    _registrar_cambio_precio_clasica,
)
from app.api.endpoints.productos_pricing import actualizar_config_cuotas_masivo
from app.api.endpoints.productos_shared import ConfigCuotasMasivoRequest
from app.models.producto import ProductoERP, ProductoPricing, HistorialPrecio
from app.models.auditoria_precio import AuditoriaPrecio
from app.models.auditoria import Auditoria


def _db_for_models(producto=None, pricing=None):
    db = MagicMock()

    def query(model):
        q = MagicMock()
        if model is ProductoERP:
            q.filter.return_value.first.return_value = producto
        elif model is ProductoPricing:
            q.filter.return_value.first.return_value = pricing
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    return db


def test_aplicar_markup_masivo_sin_permiso_403():
    request = AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=[1])
    with patch("app.services.permisos_service.verificar_permiso", return_value=False):
        with pytest.raises(HTTPException) as exc:
            aplicar_markup_masivo(request, MagicMock(), MagicMock())
    assert exc.value.status_code == 403


def test_aplicar_markup_masivo_producto_inexistente():
    request = AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=[99], recalcular_cuotas=False)
    db = _db_for_models(producto=None)
    user = MagicMock(id=19)
    with (
        patch("app.services.permisos_service.verificar_permiso", return_value=True),
        patch("app.api.endpoints.pricing.obtener_tipo_cambio_actual", return_value=None),
    ):
        result = aplicar_markup_masivo(request, db, user)
    assert result["total"] == 1
    assert result["ok"] == 0
    assert result["errores"] == 1
    assert result["resultados"][0]["error"] == "Producto no encontrado"


def test_aplicar_markup_masivo_happy_path_guarda_markup_en_porcentaje():
    request = AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=[10], recalcular_cuotas=False)
    producto = MagicMock(
        codigo="ABC",
        descripcion="Test",
        moneda_costo="ARS",
        costo=1000,
        iva=21,
        subcategoria_id=1,
    )
    pricing = MagicMock(precio_lista_ml=0, markup_adicional_cuotas_custom=None)
    db = _db_for_models(producto=producto, pricing=pricing)
    user = MagicMock(id=19)

    with (
        patch("app.services.permisos_service.verificar_permiso", return_value=True),
        patch("app.api.endpoints.pricing.resolver_costo_envio", return_value=0),
        patch("app.api.endpoints.pricing.calcular_precio_producto", return_value={"precio": 15000.0}),
        patch("app.services.pricing_calculator.convertir_a_pesos", return_value=10000.0),
        patch("app.services.pricing_calculator.obtener_grupo_subcategoria", return_value=1),
        patch("app.services.pricing_calculator.obtener_comision_base", return_value=0.13),
        patch(
            "app.services.pricing_calculator.calcular_comision_ml_total",
            return_value={"comision_total": 0.16},
        ),
        patch("app.services.pricing_calculator.calcular_limpio", return_value=10500.0),
        patch("app.services.pricing_calculator.calcular_markup", return_value=0.05),
        patch("app.api.endpoints.pricing.calcular_markup_rebate", return_value=None),
        patch("app.api.endpoints.pricing.calcular_markup_oferta", return_value=None),
        patch("app.api.endpoints.pricing.obtener_tipo_cambio_actual", return_value=None),
        patch("app.services.auditoria_service.registrar_auditoria") as audit,
    ):
        result = aplicar_markup_masivo(request, db, user)

    assert result["ok"] == 1
    assert result["errores"] == 0
    assert result["resultados"][0]["precio_antes"] == 0.0
    assert result["resultados"][0]["markup_real"] == 5.0
    assert pricing.markup_calculado == 5.0
    assert pricing.precio_lista_ml == 15000
    db.commit.assert_called()
    added_types = [type(call.args[0]) for call in db.add.call_args_list]
    assert HistorialPrecio in added_types
    assert AuditoriaPrecio in added_types
    assert Auditoria in added_types
    assert audit.call_count == 1
    assert audit.call_args.kwargs.get("valores_nuevos", {}).get("item_ids") == [10]


def test_helper_auditoria_no_commitea():
    db = MagicMock()
    pricing = MagicMock(id=7, precio_lista_ml=100)
    _registrar_cambio_precio_clasica(
        db,
        pricing=pricing,
        item_id=7,
        usuario_id=19,
        precio_anterior=100,
        precio_nuevo=200,
        comentario="test",
        motivo="test",
    )
    db.commit.assert_not_called()
    added_types = [type(call.args[0]) for call in db.add.call_args_list]
    assert AuditoriaPrecio in added_types
    assert Auditoria in added_types
    assert HistorialPrecio in added_types


def test_si_falla_despues_del_helper_no_queda_auditoria_commiteada():
    request = AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=[10], recalcular_cuotas=False)
    producto = MagicMock(
        codigo="ABC",
        descripcion="Test",
        moneda_costo="ARS",
        costo=1000,
        iva=21,
        subcategoria_id=1,
    )
    pricing = MagicMock(precio_lista_ml=14000, markup_adicional_cuotas_custom=None)
    db = _db_for_models(producto=producto, pricing=pricing)
    user = MagicMock(id=19)

    with (
        patch("app.services.permisos_service.verificar_permiso", return_value=True),
        patch("app.api.endpoints.pricing.resolver_costo_envio", return_value=0),
        patch("app.api.endpoints.pricing.calcular_precio_producto", return_value={"precio": 15000.0}),
        patch("app.services.pricing_calculator.convertir_a_pesos", return_value=10000.0),
        patch("app.services.pricing_calculator.obtener_grupo_subcategoria", return_value=1),
        patch("app.services.pricing_calculator.obtener_comision_base", return_value=0.13),
        patch(
            "app.services.pricing_calculator.calcular_comision_ml_total",
            return_value={"comision_total": 0.16},
        ),
        patch("app.services.pricing_calculator.calcular_limpio", return_value=10500.0),
        patch("app.services.pricing_calculator.calcular_markup", return_value=0.05),
        patch("app.api.endpoints.pricing.calcular_markup_rebate", side_effect=RuntimeError("boom")),
        patch("app.api.endpoints.pricing.obtener_tipo_cambio_actual", return_value=None),
        patch("app.services.auditoria_service.registrar_auditoria") as audit,
    ):
        result = aplicar_markup_masivo(request, db, user)

    assert result["ok"] == 0
    assert result["errores"] == 1
    db.commit.assert_not_called()
    db.rollback.assert_called()
    audit.assert_not_called()


def test_config_cuotas_masivo_sin_permiso_403():
    body = ConfigCuotasMasivoRequest(item_ids=[1], markup_adicional_cuotas_custom=3)
    with patch("app.services.permisos_service.verificar_permiso", return_value=False) as vp:
        with pytest.raises(HTTPException) as exc:
            actualizar_config_cuotas_masivo(body, MagicMock(), MagicMock())
    assert exc.value.status_code == 403
    assert vp.call_args.args[2] == "productos.aplicar_markup_masivo"


def test_config_cuotas_masivo_sin_campos_400():
    body = ConfigCuotasMasivoRequest(item_ids=[1])
    with patch("app.services.permisos_service.verificar_permiso", return_value=True):
        with pytest.raises(HTTPException) as exc:
            actualizar_config_cuotas_masivo(body, MagicMock(), MagicMock())
    assert exc.value.status_code == 400


def test_config_cuotas_masivo_no_pisa_markup_pvp_omitido():
    body = ConfigCuotasMasivoRequest(item_ids=[7], markup_adicional_cuotas_custom=3)
    pricing = MagicMock(markup_adicional_cuotas_pvp_custom=8.0)
    db = _db_for_models(pricing=pricing)
    user = MagicMock(id=19)

    with (
        patch("app.services.permisos_service.verificar_permiso", return_value=True),
        patch("app.services.auditoria_service.registrar_auditoria"),
    ):
        result = actualizar_config_cuotas_masivo(body, db, user)

    assert result["ok"] == 1
    assert pricing.markup_adicional_cuotas_custom == 3
    assert pricing.markup_adicional_cuotas_pvp_custom == 8.0
    db.commit.assert_called()
