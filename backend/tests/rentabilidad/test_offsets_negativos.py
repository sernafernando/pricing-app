"""
Negative-valued profit offsets must SUBTRACT from rentabilidad metrics, not be
dropped. Covers all 3 channels (ML/dashboard, Fuera, Tienda Nube) plus the
group-accumulation path. See spec "Offset sign is applied to rentabilidad
metrics" and "Group-path offset accumulation applies sign".
"""

from datetime import date, datetime, timezone

import pytest

from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica

MARCA = "MarcaOffsetNeg"

_ml_counter = 0
_fuera_counter = 0
_tn_counter = 0


def _make_ml_venta(db, *, marca=MARCA, monto_total=1000.0, costo_total_sin_iva=600.0, ganancia=300.0):
    global _ml_counter
    _ml_counter += 1
    row = MLVentaMetrica(
        id_operacion=900_000 + _ml_counter,
        mla_id=str(900_000 + _ml_counter),
        item_id=5000 + _ml_counter,
        codigo=f"MLA-{_ml_counter}",
        descripcion="Producto ML",
        marca=marca,
        categoria="CategoriaX",
        fecha_venta=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        cantidad=1,
        monto_unitario=monto_total,
        monto_total=monto_total,
        costo_unitario_sin_iva=costo_total_sin_iva,
        costo_total_sin_iva=costo_total_sin_iva,
        comision_ml=100.0,
        costo_envio_ml=0.0,
        tipo_logistica="flex",
        monto_limpio=monto_total - 100.0,
        costo_total=costo_total_sin_iva,
        ganancia=ganancia,
        markup_porcentaje=50.0,
    )
    db.add(row)
    db.flush()
    return row


def _make_fuera_venta(db, *, marca=MARCA, monto_total=1000.0, costo_total=600.0, ganancia=300.0):
    global _fuera_counter
    _fuera_counter += 1
    row = VentaFueraMLMetrica(
        it_transaction=800_000 + _fuera_counter,
        item_id=6000 + _fuera_counter,
        codigo=f"FUERA-{_fuera_counter}",
        descripcion="Producto Fuera",
        marca=marca,
        categoria="CategoriaX",
        fecha_venta=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        sd_id=1,
        signo=1,
        cantidad=1,
        monto_unitario=monto_total,
        monto_total=monto_total,
        costo_unitario=costo_total,
        costo_total=costo_total,
        moneda_costo="ARS",
        ganancia=ganancia,
        markup_porcentaje=50.0,
    )
    db.add(row)
    db.flush()
    return row


def _make_tn_venta(db, *, marca=MARCA, monto_total=1000.0, costo_total=600.0, ganancia=300.0):
    global _tn_counter
    _tn_counter += 1
    row = VentaTiendaNubeMetrica(
        it_transaction=700_000 + _tn_counter,
        item_id=7000 + _tn_counter,
        codigo=f"TN-{_tn_counter}",
        descripcion="Producto TN",
        marca=marca,
        categoria="CategoriaX",
        fecha_venta=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        sd_id=1,
        signo=1,
        cantidad=1,
        monto_unitario=monto_total,
        monto_total=monto_total,
        costo_unitario=costo_total,
        costo_total=costo_total,
        moneda_costo="ARS",
        comision_porcentaje=0.0,
        comision_monto=0.0,
        ganancia=ganancia,
        markup_porcentaje=50.0,
    )
    db.add(row)
    db.flush()
    return row


CHANNELS = [
    ("/api/rentabilidad", _make_ml_venta, "aplica_ml"),
    ("/api/rentabilidad-fuera", _make_fuera_venta, "aplica_fuera"),
    ("/api/rentabilidad-tienda-nube", _make_tn_venta, "aplica_tienda_nube"),
]

COMMON_PARAMS = {
    "fecha_desde": "2026-06-01",
    "fecha_hasta": "2026-06-30",
}


def _find_card(payload, marca=MARCA):
    for card in payload["cards"]:
        if card["nombre"] == marca:
            return card
    raise AssertionError(f"card for {marca} not found in {payload['cards']}")


class TestNegativeOffsetSubtracts:
    @pytest.mark.parametrize("endpoint,make_venta,aplica_field", CHANNELS)
    def test_single_negative_offset_subtracts(
        self, client, db, admin_auth_headers, offset_ganancia_factory, endpoint, make_venta, aplica_field
    ):
        make_venta(db)
        offset_ganancia_factory(
            **{
                "marca": MARCA,
                "tipo_offset": "monto_fijo",
                "monto": -50.0,
                aplica_field: True,
            }
        )
        db.commit()

        resp = client.get(endpoint, params=COMMON_PARAMS, headers=admin_auth_headers)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        card = _find_card(payload)
        assert card["offset_total"] == pytest.approx(-50.0)
        assert card["ganancia_con_offset"] < card["ganancia"]

    @pytest.mark.parametrize("endpoint,make_venta,aplica_field", CHANNELS)
    def test_mixed_positive_and_negative_offsets_net_correctly(
        self, client, db, admin_auth_headers, offset_ganancia_factory, endpoint, make_venta, aplica_field
    ):
        make_venta(db)
        offset_ganancia_factory(**{"marca": MARCA, "tipo_offset": "monto_fijo", "monto": 100.0, aplica_field: True})
        offset_ganancia_factory(**{"marca": MARCA, "tipo_offset": "monto_fijo", "monto": -30.0, aplica_field: True})
        db.commit()

        resp = client.get(endpoint, params=COMMON_PARAMS, headers=admin_auth_headers)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        card = _find_card(payload)
        assert card["offset_total"] == pytest.approx(70.0)


def test_negative_offset_appears_in_ml_desglose(client, db, admin_auth_headers, offset_ganancia_factory):
    """ML channel is the only one that exposes a per-offset desglose list."""
    _make_ml_venta(db)
    offset_ganancia_factory(marca=MARCA, tipo_offset="monto_fijo", monto=-50.0, aplica_ml=True)
    db.commit()

    resp = client.get("/api/rentabilidad", params=COMMON_PARAMS, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    card = _find_card(resp.json())
    montos = [d["monto"] for d in card["desglose_offsets"]]
    assert -50.0 in montos


class TestGroupPathAppliesSign:
    def test_negative_group_offset_subtracts(
        self, client, db, admin_auth_headers, offset_grupo_factory, offset_ganancia_factory
    ):
        """Verifies ADR-3: the group-accumulation path (offset_total +=
        grupo_info['offset_total']) is unguarded by any sign filter, so a
        negative group offset with NO limit should already subtract via the
        'calculado en tiempo real' branch (no resumen row seeded)."""
        from app.models.offset_grupo_filtro import OffsetGrupoFiltro

        _make_ml_venta(db)
        grupo = offset_grupo_factory()
        db.add(OffsetGrupoFiltro(grupo_id=grupo.id, marca=MARCA))
        offset_ganancia_factory(
            grupo_id=grupo.id,
            tipo_offset="monto_fijo",
            monto=-40.0,
            fecha_desde=date(2026, 1, 1),
        )
        db.commit()

        resp = client.get("/api/rentabilidad", params=COMMON_PARAMS, headers=admin_auth_headers)
        assert resp.status_code == 200, resp.text
        card = _find_card(resp.json())
        assert card["offset_total"] == pytest.approx(-40.0)
