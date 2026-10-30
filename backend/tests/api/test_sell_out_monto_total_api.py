"""Fixed-total sell-out campaigns through the API (sell-in-sell-out T26c, S34/S35), on the SQLite test database like
`tests/api/test_sell_out_campana_items.py`: the campaign (`sell_out.gestionar`), its manual split among its products
(`PUT /{id}/reparto`, `sell_out.repartir` or `sell_out.gestionar`, a PM only over the products of their brands) and
what the responses show. The queue is Postgres only: `tests/services/sell_out/test_reparto_postgres.py`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.marca_pm import MarcaPM
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana

BASE = "/api/sell-out/campanas"
ROUTER, SWITCH, TINTA, AJENO = 2964, 2270, 3001, 950
PRODUCTOS = {ROUTER: ("TP-LINK", "Routers"), SWITCH: ("TP-LINK", "Switches"), TINTA: ("EPSON", "Tintas")}


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    grant_permiso(rol_admin, "sell_out.gestionar")
    return admin_auth_headers


@pytest.fixture()
def pm(db, rol_ventas, active_user, auth_headers, grant_permiso):
    """A PM of TP-Link (both categories) holding only `sell_out.repartir`."""
    grant_permiso(rol_ventas, "sell_out.repartir")
    db.add_all(MarcaPM(marca="TP-LINK", categoria=c, usuario_id=active_user.id) for c in ("Routers", "Switches"))
    db.flush()
    return auth_headers


@pytest.fixture()
def grupo(db) -> int:
    db.add_all(
        ProductoERP(item_id=i, codigo=f"C{i}", descripcion=f"P{i}", marca=m, categoria=c)
        for i, (m, c) in PRODUCTOS.items()
    )
    db.add(ProductoERP(item_id=AJENO, codigo=f"C{AJENO}", descripcion="Fuera", marca="MERCUSYS", categoria="Routers"))
    grupo = OffsetGrupo(nombre="Bono trimestral")
    db.add(grupo)
    db.flush()
    db.add_all(OffsetGrupoFiltro(grupo_id=grupo.id, item_id=i) for i in PRODUCTOS)
    db.flush()
    return grupo.id


def _body(grupo: int, **overrides) -> dict:
    body = {
        "nombre": "Bono Q4",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "tipo": "monto_total",
        "monto_total": "2000000.00",
        "moneda": "ARS",
        "grupo_ids": [grupo],
    }
    body.update(overrides)
    return body


def _crear(client, headers, grupo, **overrides) -> dict:
    resp = client.post(BASE, json=_body(grupo, **overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _repartir(client, headers, campana_id, repartos):
    return client.put(f"{BASE}/{campana_id}/reparto", json={"repartos": repartos}, headers=headers)


def _shares(out: dict) -> list:
    def num(x):
        return None if x is None else float(x)

    return [(i["item_id"], num(i["reparto_porcentaje"]), num(i["reparto_monto"])) for i in out["items"]]


# ── Create / edit a monto_total campaign ────────────────────────────


def test_create_a_fixed_total_campaign_without_shares(client, gestor, grupo) -> None:
    out = _crear(client, gestor, grupo)

    assert (out["tipo"], float(out["monto_total"]), out["monto_unit"], out["porcentaje"]) == (
        "monto_total",
        2000000.0,
        None,
        None,
    )
    assert out["items"] == []
    reparto = dict(out["resumen"]["reparto"])
    assert reparto.pop("motivo") is None
    assert {k: float(v) for k, v in reparto.items()} == {
        "asignado": 0.0,
        "asignado_sin_ventas": 0.0,
        "sin_asignar": 2000000.0,
    }


def test_a_negative_total_is_a_deduction_and_is_accepted(client, gestor, grupo) -> None:
    out = _crear(client, gestor, grupo, monto_total="-13662075.00")
    assert float(out["monto_total"]) == -13662075.0
    assert float(out["resumen"]["reparto"]["sin_asignar"]) == -13662075.0


@pytest.mark.parametrize(
    "overrides,mensaje",
    [
        ({"monto_total": "0"}, "Una campaña por monto total necesita un monto total distinto de 0"),
        ({"monto_total": None}, "Una campaña por monto total necesita un monto total distinto de 0"),
        ({"monto_unit": "5"}, "Una campaña por monto total no lleva monto por unidad"),
        ({"porcentaje": "5"}, "Una campaña por monto total no lleva porcentaje"),
        ({"tope_unidades": 10}, "Una campaña por monto total no lleva topes: el monto total es el tope"),
        ({"tope_monto": "10"}, "Una campaña por monto total no lleva topes: el monto total es el tope"),
    ],
)
def test_a_broken_fixed_total_campaign_is_a_422(client, gestor, grupo, db, overrides, mensaje) -> None:
    resp = client.post(BASE, json=_body(grupo, **overrides), headers=gestor)
    assert resp.status_code == 422
    assert mensaje in resp.text
    assert db.query(SellOutCampana).count() == 0


def test_a_total_on_another_type_is_a_422(client, gestor, grupo) -> None:
    resp = client.post(BASE, json=_body(grupo, tipo="por_unidad", monto_unit="5"), headers=gestor)
    assert resp.status_code == 422
    assert "Una campaña por unidad no lleva monto total" in resp.text

    body = _body(grupo, tipo="porcentaje", porcentaje="2")
    resp = client.post(BASE, json=body, headers=gestor)
    assert resp.status_code == 422
    assert "Una campaña por porcentaje no lleva monto total" in resp.text


def test_create_with_shares_returns_them_with_the_product(client, gestor, grupo) -> None:
    items = [{"item_id": ROUTER, "reparto_porcentaje": "60"}, {"item_id": TINTA, "reparto_monto": "100000"}]
    out = _crear(client, gestor, grupo, items=items)

    assert _shares(out) == [(ROUTER, 60.0, None), (TINTA, None, 100000.0)]
    assert [(i["codigo"], i["descripcion"], i["monto_unit"]) for i in out["items"]] == [
        (f"C{ROUTER}", f"P{ROUTER}", None),
        (f"C{TINTA}", f"P{TINTA}", None),
    ]
    reparto = {k: float(v) for k, v in out["resumen"]["reparto"].items() if k != "motivo"}
    # No sale yet: everything assigned has no sales; the rest is unassigned.
    assert reparto == {"asignado": 1300000.0, "asignado_sin_ventas": 1300000.0, "sin_asignar": 700000.0}


def test_a_share_on_a_per_unit_campaign_and_an_amount_on_a_fixed_total_are_a_422(client, gestor, grupo) -> None:
    body = _body(grupo, tipo="por_unidad", monto_total=None, monto_unit="5")
    body["items"] = [{"item_id": ROUTER, "reparto_porcentaje": "10"}]
    resp = client.post(BASE, json=body, headers=gestor)
    assert resp.status_code == 422
    assert "Una campaña por unidad no lleva reparto por producto" in resp.text

    resp = client.post(BASE, json=_body(grupo, items=[{"item_id": ROUTER, "monto_unit": "5"}]), headers=gestor)
    assert resp.status_code == 422
    assert "Una campaña por monto total no lleva montos por unidad por producto" in resp.text


def test_lowering_the_total_below_the_shares_is_a_422_naming_the_excess(client, gestor, grupo) -> None:
    out = _crear(client, gestor, grupo, items=[{"item_id": ROUTER, "reparto_monto": "1500000"}])

    resp = client.put(f"{BASE}/{out['id']}", json=_body(grupo, monto_total="1000000"), headers=gestor)

    assert resp.status_code == 422
    assert "El reparto (1500000.00) supera el monto total (1000000.00) en 500000.00" in resp.text
    detalle = client.get(f"{BASE}/{out['id']}", headers=gestor).json()
    assert (float(detalle["monto_total"]), _shares(detalle)) == (2000000.0, [(ROUTER, None, 1500000.0)])


def test_flipping_the_total_sign_under_a_fixed_share_is_a_422(client, gestor, grupo) -> None:
    out = _crear(client, gestor, grupo, items=[{"item_id": ROUTER, "reparto_monto": "1000"}])
    resp = client.put(f"{BASE}/{out['id']}", json=_body(grupo, monto_total="-2000000"), headers=gestor)
    assert resp.status_code == 422
    assert f"El reparto del producto {ROUTER} tiene que tener el signo del monto total" in resp.text


def test_switching_a_split_campaign_to_per_unit_without_clearing_the_shares_is_a_422(client, gestor, grupo) -> None:
    out = _crear(client, gestor, grupo, items=[{"item_id": ROUTER, "reparto_porcentaje": "10"}])
    body = _body(grupo, tipo="por_unidad", monto_total=None, monto_unit="5")
    resp = client.put(f"{BASE}/{out['id']}", json=body, headers=gestor)
    assert resp.status_code == 422
    assert "Una campaña por unidad no lleva reparto por producto: quitá el reparto para cambiarla" in resp.text


# ── PUT /{id}/reparto: rules ────────────────────────────────────────


def test_the_split_needs_repartir_or_gestionar(client, gestor, grupo, auth_headers, rol_ventas, grant_permiso) -> None:
    cid = _crear(client, gestor, grupo)["id"]
    resp = _repartir(client, auth_headers, cid, [])
    assert resp.status_code == 403
    assert "sell_out.repartir" in resp.text

    grant_permiso(rol_ventas, "sell_out.ver")
    assert _repartir(client, auth_headers, cid, []).status_code == 403

    assert _repartir(client, gestor, cid, []).status_code == 200
    assert client.put(f"{BASE}/{cid}/reparto", json={"repartos": []}).status_code in (401, 403)


def test_an_admin_replaces_the_whole_split(client, gestor, grupo) -> None:
    cid = _crear(client, gestor, grupo, items=[{"item_id": TINTA, "reparto_monto": "5"}])["id"]

    resp = _repartir(
        client,
        gestor,
        cid,
        [{"item_id": ROUTER, "reparto_porcentaje": "90"}, {"item_id": SWITCH, "reparto_monto": "1"}],
    )

    assert resp.status_code == 200, resp.text
    assert _shares(resp.json()) == [(SWITCH, None, 1.0), (ROUTER, 90.0, None)]
    assert _shares(client.get(f"{BASE}/{cid}", headers=gestor).json()) == [(SWITCH, None, 1.0), (ROUTER, 90.0, None)]


def test_a_negative_total_takes_percent_shares_and_same_sign_fixed_shares(client, gestor, grupo) -> None:
    cid = _crear(client, gestor, grupo, monto_total="-13662075.00")["id"]

    resp = _repartir(
        client,
        gestor,
        cid,
        [{"item_id": ROUTER, "reparto_porcentaje": "60"}, {"item_id": TINTA, "reparto_monto": "-5"}],
    )

    assert resp.status_code == 200, resp.text
    reparto = {k: float(v) for k, v in resp.json()["resumen"]["reparto"].items() if k != "motivo"}
    assert reparto["asignado"] == -8197250.0  # 60 % of -13.662.075 = -8.197.245 plus -5
    assert reparto["sin_asignar"] == -5464825.0


@pytest.mark.parametrize(
    "share,mensaje",
    [
        ({"item_id": ROUTER}, f"El producto {ROUTER} necesita un porcentaje o un monto de reparto"),
        (
            {"item_id": ROUTER, "reparto_porcentaje": "10", "reparto_monto": "5"},
            f"El producto {ROUTER} lleva un porcentaje o un monto de reparto, no los dos",
        ),
        (
            {"item_id": ROUTER, "reparto_porcentaje": "0"},
            "El porcentaje de reparto tiene que ser mayor a 0 y hasta 100",
        ),
        (
            {"item_id": ROUTER, "reparto_porcentaje": "100.5"},
            "El porcentaje de reparto tiene que ser mayor a 0 y hasta 100",
        ),
        ({"item_id": ROUTER, "reparto_monto": "0"}, f"El monto de reparto del producto {ROUTER} no puede ser 0"),
        (
            {"item_id": ROUTER, "reparto_monto": "-5"},
            f"El reparto del producto {ROUTER} tiene que tener el signo del monto total",
        ),
        ({"item_id": AJENO, "reparto_monto": "5"}, f"El producto {AJENO} no está en los grupos de la campaña"),
        ({"item_id": ROUTER, "monto_unit": "5"}, "Una campaña por monto total no lleva montos por unidad por producto"),
    ],
)
def test_a_broken_share_is_a_422_and_nothing_changes(client, gestor, grupo, share, mensaje) -> None:
    cid = _crear(client, gestor, grupo, items=[{"item_id": TINTA, "reparto_monto": "5"}])["id"]

    resp = _repartir(client, gestor, cid, [share])

    assert resp.status_code == 422
    assert mensaje in resp.text
    assert _shares(client.get(f"{BASE}/{cid}", headers=gestor).json()) == [(TINTA, None, 5.0)]


def test_a_product_listed_twice_is_a_422(client, gestor, grupo) -> None:
    cid = _crear(client, gestor, grupo)["id"]
    shares = [{"item_id": ROUTER, "reparto_monto": "5"}, {"item_id": ROUTER, "reparto_porcentaje": "5"}]
    resp = _repartir(client, gestor, cid, shares)
    assert resp.status_code == 422
    assert f"El producto {ROUTER} tiene más de un reparto" in resp.text


def test_shares_over_the_total_are_a_422_naming_the_excess(client, gestor, grupo) -> None:
    cid = _crear(client, gestor, grupo)["id"]
    shares = [{"item_id": ROUTER, "reparto_porcentaje": "90"}, {"item_id": TINTA, "reparto_monto": "200000.01"}]
    resp = _repartir(client, gestor, cid, shares)
    assert resp.status_code == 422
    assert "El reparto (2000000.01) supera el monto total (2000000.00) en 0.01" in resp.text

    shares[1]["reparto_monto"] = "200000.00"  # exactly the total
    assert _repartir(client, gestor, cid, shares).status_code == 200


def test_only_an_active_fixed_total_campaign_is_split(client, gestor, grupo) -> None:
    por_unidad = _crear(client, gestor, grupo, tipo="por_unidad", monto_total=None, monto_unit="5")["id"]
    resp = _repartir(client, gestor, por_unidad, [])
    assert resp.status_code == 422
    assert "Solo las campañas por monto total se reparten por producto" in resp.text

    cid = _crear(client, gestor, grupo)["id"]
    assert client.post(f"{BASE}/{cid}/anular", headers=gestor).status_code == 200
    resp = _repartir(client, gestor, cid, [])
    assert resp.status_code == 409  # like edit, void and rate change on a voided campaign
    assert f"La campaña {cid} está anulada" in resp.text

    assert _repartir(client, gestor, 999999, []).status_code == 404


# ── PUT /{id}/reparto: PM brand scope ───────────────────────────────


def test_a_pm_cannot_split_another_brands_product(client, gestor, pm, grupo) -> None:
    cid = _crear(client, gestor, grupo)["id"]

    resp = _repartir(
        client, pm, cid, [{"item_id": ROUTER, "reparto_monto": "5"}, {"item_id": TINTA, "reparto_monto": "5"}]
    )

    assert resp.status_code == 403
    assert f"El producto {TINTA} (C{TINTA}) no es de tus marcas" in resp.text
    assert _shares(client.get(f"{BASE}/{cid}", headers=gestor).json()) == []


def test_a_pm_split_keeps_the_shares_of_brands_they_cannot_see(client, gestor, pm, grupo) -> None:
    items = [{"item_id": TINTA, "reparto_porcentaje": "30"}, {"item_id": SWITCH, "reparto_monto": "7"}]
    cid = _crear(client, gestor, grupo, items=items)["id"]

    resp = _repartir(client, pm, cid, [{"item_id": ROUTER, "reparto_porcentaje": "50"}])

    assert resp.status_code == 200, resp.text
    # SWITCH (theirs, not sent) is removed; TINTA (EPSON, not theirs) is kept as it was.
    assert _shares(client.get(f"{BASE}/{cid}", headers=gestor).json()) == [(ROUTER, 50.0, None), (TINTA, 30.0, None)]

    _repartir(client, pm, cid, [])
    assert _shares(client.get(f"{BASE}/{cid}", headers=gestor).json()) == [(TINTA, 30.0, None)]


def test_a_scoped_pm_response_shows_only_the_shares_of_their_brands(client, gestor, pm, grupo) -> None:
    # An empty PUT must not turn into a read of the other brands' split.
    items = [{"item_id": TINTA, "reparto_porcentaje": "30"}, {"item_id": SWITCH, "reparto_monto": "7"}]
    cid = _crear(client, gestor, grupo, items=items)["id"]

    resp = _repartir(client, pm, cid, [])
    assert resp.status_code == 200, resp.text
    assert _shares(resp.json()) == []
    assert "reparto_porcentaje" not in resp.text

    resp = _repartir(client, pm, cid, [{"item_id": ROUTER, "reparto_monto": "1"}])
    assert _shares(resp.json()) == [(ROUTER, None, 1.0)]
    # The summary is the campaign's, aggregated: what is left to assign, no product of another brand.
    assert float(resp.json()["resumen"]["reparto"]["sin_asignar"]) == 2000000.0 - 600000.0 - 1.0


def test_a_repartir_user_who_sees_every_brand_replaces_the_whole_split(
    client, gestor, grupo, rol_ventas, auth_headers, grant_permiso
) -> None:
    grant_permiso(rol_ventas, "sell_out.repartir")
    grant_permiso(rol_ventas, "ventas_ml.ver_todas_marcas")  # pm_scope: no brand filter
    cid = _crear(client, gestor, grupo, items=[{"item_id": TINTA, "reparto_porcentaje": "30"}])["id"]

    resp = _repartir(client, auth_headers, cid, [{"item_id": ROUTER, "reparto_monto": "5"}])

    assert resp.status_code == 200, resp.text
    assert _shares(resp.json()) == [(ROUTER, None, 5.0)]
    assert _shares(client.get(f"{BASE}/{cid}", headers=gestor).json()) == [(ROUTER, None, 5.0)]


def test_a_pm_split_counts_the_kept_shares_against_the_total(client, gestor, pm, grupo) -> None:
    cid = _crear(client, gestor, grupo, items=[{"item_id": TINTA, "reparto_porcentaje": "80"}])["id"]
    resp = _repartir(client, pm, cid, [{"item_id": ROUTER, "reparto_porcentaje": "30"}])
    assert resp.status_code == 422
    assert "El reparto (2200000.00) supera el monto total (2000000.00) en 200000.00" in resp.text


def test_every_split_change_is_audited_with_who_and_before_after(client, gestor, pm, grupo, db, active_user) -> None:
    cid = _crear(client, gestor, grupo, items=[{"item_id": TINTA, "reparto_monto": "5"}])["id"]

    assert _repartir(client, pm, cid, [{"item_id": ROUTER, "reparto_porcentaje": "12.5"}]).status_code == 200

    audit = (
        db.query(Auditoria)
        .filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_EDITADA)
        .order_by(Auditoria.id.desc())
        .first()
    )
    assert audit.usuario_id == active_user.id
    assert audit.comentario == "Reparto del monto total"
    assert audit.valores_anteriores["items"] == [
        {"item_id": TINTA, "reparto_porcentaje": None, "reparto_monto": "5.00"}
    ]
    assert audit.valores_nuevos["items"] == [
        {"item_id": ROUTER, "reparto_porcentaje": "12.5000", "reparto_monto": None},
        {"item_id": TINTA, "reparto_porcentaje": None, "reparto_monto": "5.00"},
    ]
    assert audit.valores_nuevos["monto_total"] == "2000000.00"


# ── Per-unit and percentage responses are unchanged ─────────────────

VOLATILES = ("id", "usuario_id", "created_at", "updated_at")


def _estable(out: dict) -> dict:
    out = {k: v for k, v in out.items() if k not in VOLATILES}
    out["grupos"] = [g["nombre"] for g in out["grupos"]]
    return out


ORDEN = (
    "id nombre descripcion fecha_desde fecha_hasta tipo monto_unit porcentaje base_porcentaje moneda tc_modo "
    "tipo_cambio tc_definido_en tope_unidades tope_monto acumulable monto_incluye_iva estado usuario_id "
    "offset_origen_id created_at updated_at grupos items resumen"
).split()
RESUMEN_VACIO = {
    "lineas": 0,
    "unidades": 0,
    "monto": "0",
    "monto_ars": "0",
    "tope_unidades_restantes": None,
    "tope_monto_restante": None,
    "por_canal": [],
    "pendientes_base": 0,
    "recalculo": {"estado": "al_dia", "intentos": 0, "error": None, "detenida": False, "encolada_en": None},
}
COMUNES = {
    "descripcion": None,
    "fecha_desde": "2026-11-01",
    "fecha_hasta": "2026-11-30",
    "base_porcentaje": "costo",
    "tipo_cambio": None,
    "tc_definido_en": None,
    "tope_unidades": None,
    "tope_monto": None,
    "acumulable": True,
    "monto_incluye_iva": False,
    "estado": "activa",
    "offset_origen_id": None,
    "grupos": ["Bono trimestral"],
}


def test_per_unit_and_percentage_responses_are_byte_identical(client, gestor, grupo) -> None:
    fechas = {"fecha_desde": "2026-11-01", "fecha_hasta": "2026-11-30"}
    por_unidad = _body(grupo, tipo="por_unidad", monto_total=None, monto_unit="10", moneda="USD", nombre="N", **fechas)
    por_unidad["items"] = [{"item_id": ROUTER, "monto_unit": "25"}]
    porcentaje = _body(grupo, tipo="porcentaje", monto_total=None, porcentaje="2.5", nombre="P", **fechas)
    del por_unidad["monto_total"], porcentaje["monto_total"]

    a, b = (client.post(BASE, json=body, headers=gestor) for body in (por_unidad, porcentaje))
    assert (a.status_code, b.status_code) == (201, 201), (a.text, b.text)
    a, b = a.json(), b.json()

    esperado_a = {
        **COMUNES,
        "nombre": "N",
        "tipo": "por_unidad",
        "monto_unit": "10.00",
        "porcentaje": None,
        "moneda": "USD",
        "tc_modo": "al_cobro",
        "items": [{"item_id": ROUTER, "monto_unit": "25.00", "codigo": f"C{ROUTER}", "descripcion": f"P{ROUTER}"}],
        "resumen": {**RESUMEN_VACIO, "ars_estimado": True},
    }
    esperado_b = {
        **COMUNES,
        "nombre": "P",
        "tipo": "porcentaje",
        "monto_unit": None,
        "porcentaje": "2.5000",
        "moneda": "ARS",
        "tc_modo": None,
        "items": [],
        "resumen": {**RESUMEN_VACIO, "ars_estimado": False},
    }
    assert _estable(a) == esperado_a
    assert _estable(b) == esperado_b
    assert list(a) == ORDEN  # same keys, same order: no new key on these types
    assert list(a["items"][0]) == ["item_id", "monto_unit", "codigo", "descripcion"]
    assert list(a["resumen"]) == list(RESUMEN_VACIO)[:4] + ["ars_estimado"] + list(RESUMEN_VACIO)[4:]
    assert _estable(client.get(f"{BASE}/{a['id']}", headers=gestor).json()) == esperado_a
    listado = {c["id"]: _estable(c) for c in client.get(BASE, headers=gestor).json()["items"]}
    assert listado == {a["id"]: esperado_a, b["id"]: esperado_b}
    editado = client.put(f"{BASE}/{a['id']}", json=por_unidad, headers=gestor)
    assert _estable(editado.json()) == esperado_a


# ── Error shapes ────────────────────────────────────────────────────


@pytest.mark.parametrize("tipo,extra", [("por_unidad", {"monto_unit": "10"}), ("porcentaje", {"porcentaje": "2"})])
def test_an_item_without_its_amount_keeps_the_field_required_422(client, gestor, grupo, tipo, extra) -> None:
    body = _body(grupo, tipo=tipo, items=[{"item_id": ROUTER}], **extra)
    del body["monto_total"]

    resp = client.post(BASE, json=body, headers=gestor)

    # Byte for byte what the API answered before T26c.
    assert resp.status_code == 422
    assert resp.json() == {
        "detail": [
            {
                "type": "missing",
                "loc": ["body", "items", 0, "monto_unit"],
                "msg": "Field required",
                "input": {"item_id": ROUTER},
            }
        ]
    }


def test_the_summary_only_absorbs_a_split_refusal(client, gestor, grupo, monkeypatch) -> None:
    from app.services.sell_out import reparto

    cid = _crear(client, gestor, grupo)["id"]

    def rehusa(*_args):
        raise reparto.RepartoInvalido("the shares exceed the total", suma=Decimal("3.00"), total=Decimal("2.00"))

    monkeypatch.setattr(reparto, "resumen_monto_total", rehusa)
    out = client.get(f"{BASE}/{cid}", headers=gestor).json()
    assert out["resumen"]["reparto"] == {
        "asignado": None,
        "asignado_sin_ventas": None,
        "sin_asignar": None,
        "motivo": "El reparto (3.00) supera el monto total (2.00) en 1.00",
    }

    def falla(*_args):
        raise ValueError("an unrelated bug")

    monkeypatch.setattr(reparto, "resumen_monto_total", falla)
    assert client.get(f"{BASE}/{cid}", headers=gestor).status_code == 500  # surfaces, never a null summary


def test_a_vat_loaded_split_on_a_product_without_vat_does_not_break_the_list(client, gestor, grupo, db) -> None:
    db.get(ProductoERP, ROUTER).iva = None
    db.flush()
    rota = _crear(client, gestor, grupo, monto_incluye_iva=True, items=[{"item_id": ROUTER, "reparto_monto": "5"}])
    sana = _crear(client, gestor, grupo, items=[{"item_id": TINTA, "reparto_monto": "5"}])

    resp = client.get(BASE, headers=gestor)

    assert resp.status_code == 200, resp.text
    por_id = {c["id"]: c["resumen"]["reparto"] for c in resp.json()["items"]}
    assert por_id[rota["id"]] == {
        "asignado": None,
        "asignado_sin_ventas": None,
        "sin_asignar": None,
        "motivo": f"El producto {ROUTER} no tiene IVA y el monto se cargó con IVA",
    }
    assert float(por_id[sana["id"]]["sin_asignar"]) == 1999995.0
    assert por_id[sana["id"]]["motivo"] is None
    assert client.get(f"{BASE}/{rota['id']}", headers=gestor).status_code == 200


# ── GET by a brand-scoped PM ────────────────────────────────────────


@pytest.fixture()
def pm_lector(pm, rol_ventas, grant_permiso):
    grant_permiso(rol_ventas, "sell_out.ver")
    return pm


def _dos_marcas(client, gestor, grupo) -> int:
    items = [{"item_id": ROUTER, "reparto_monto": "100"}, {"item_id": TINTA, "reparto_porcentaje": "30"}]
    return _crear(client, gestor, grupo, items=items)["id"]


def test_a_scoped_pm_detail_and_list_show_only_their_brands_shares(client, gestor, pm_lector, grupo) -> None:
    cid = _dos_marcas(client, gestor, grupo)

    detalle = client.get(f"{BASE}/{cid}", headers=pm_lector)
    [listada] = client.get(BASE, headers=pm_lector).json()["items"]

    assert detalle.status_code == 200, detalle.text
    for out in (detalle.json(), listada):
        assert _shares(out) == [(ROUTER, None, 100.0)]
        # The totals stay the campaign's: 100 + 30 % of 2.000.000 assigned.
        assert float(out["resumen"]["reparto"]["asignado"]) == 600100.0
        assert float(out["resumen"]["reparto"]["sin_asignar"]) == 1399900.0


def test_a_scoped_pm_round_trip_keeps_the_other_brands_shares(client, gestor, pm_lector, grupo) -> None:
    cid = _dos_marcas(client, gestor, grupo)
    visibles = client.get(f"{BASE}/{cid}", headers=pm_lector).json()["items"]
    repartos = [
        {"item_id": i["item_id"], "reparto_porcentaje": i["reparto_porcentaje"], "reparto_monto": "250"}
        for i in visibles
    ]

    resp = _repartir(client, pm_lector, cid, repartos)

    assert resp.status_code == 200, resp.text
    assert _shares(client.get(f"{BASE}/{cid}", headers=gestor).json()) == [(ROUTER, None, 250.0), (TINTA, 30.0, None)]


def test_a_gestionar_user_still_sees_every_share(client, gestor, grupo) -> None:
    cid = _dos_marcas(client, gestor, grupo)
    esperado = [
        {
            "item_id": ROUTER,
            "monto_unit": None,
            "codigo": f"C{ROUTER}",
            "descripcion": f"P{ROUTER}",
            "reparto_porcentaje": None,
            "reparto_monto": "100.00",
        },
        {
            "item_id": TINTA,
            "monto_unit": None,
            "codigo": f"C{TINTA}",
            "descripcion": f"P{TINTA}",
            "reparto_porcentaje": "30.0000",
            "reparto_monto": None,
        },
    ]
    assert client.get(f"{BASE}/{cid}", headers=gestor).json()["items"] == esperado
    assert client.get(BASE, headers=gestor).json()["items"][0]["items"] == esperado


def test_a_scoped_pm_still_sees_a_per_unit_campaigns_amounts(client, gestor, pm_lector, grupo) -> None:
    body = _body(grupo, tipo="por_unidad", monto_unit="5", items=[{"item_id": TINTA, "monto_unit": "9"}])
    del body["monto_total"]
    cid = client.post(BASE, json=body, headers=gestor).json()["id"]
    [item] = client.get(f"{BASE}/{cid}", headers=pm_lector).json()["items"]
    assert (item["item_id"], item["monto_unit"]) == (TINTA, "9.00")


def test_a_page_without_shares_skips_the_brand_lookup(client, gestor, pm_lector, grupo, monkeypatch) -> None:
    from app.services.sell_out import campanas

    _crear(client, gestor, grupo)  # monto_total, no shares
    body = _body(grupo, tipo="por_unidad", monto_unit="5", items=[{"item_id": TINTA, "monto_unit": "9"}])
    del body["monto_total"]
    assert client.post(BASE, json=body, headers=gestor).status_code == 201

    def no_lookup(*_args):
        raise AssertionError("brand lookup on a page without shares")

    monkeypatch.setattr(campanas, "_de_sus_marcas", no_lookup)
    resp = client.get(BASE, headers=pm_lector)
    assert resp.status_code == 200, resp.text
    assert campanas.solo_sus_marcas(None, [], {("TP-LINK", "ROUTERS")}) == []


def test_a_reader_without_repartir_sees_every_share(
    client, gestor, grupo, db, rol_ventas, active_user, auth_headers, grant_permiso
) -> None:
    # A PM brand of their own does not scope a plain reader: only `sell_out.repartir` does.
    db.add(MarcaPM(marca="TP-LINK", categoria="Routers", usuario_id=active_user.id))
    db.flush()
    grant_permiso(rol_ventas, "sell_out.ver")
    cid = _dos_marcas(client, gestor, grupo)
    assert _shares(client.get(f"{BASE}/{cid}", headers=auth_headers).json()) == [
        (ROUTER, None, 100.0),
        (TINTA, 30.0, None),
    ]


def test_a_repartir_pm_who_sees_every_brand_sees_every_share(
    client, gestor, grupo, rol_ventas, auth_headers, grant_permiso
) -> None:
    for codigo in ("sell_out.ver", "sell_out.repartir", "ventas_ml.ver_todas_marcas"):
        grant_permiso(rol_ventas, codigo)
    cid = _dos_marcas(client, gestor, grupo)
    assert _shares(client.get(f"{BASE}/{cid}", headers=auth_headers).json()) == [
        (ROUTER, None, 100.0),
        (TINTA, 30.0, None),
    ]
    [listada] = client.get(BASE, headers=auth_headers).json()["items"]
    assert _shares(listada) == [(ROUTER, None, 100.0), (TINTA, 30.0, None)]


def test_a_scoped_pm_list_is_filtered_per_type(client, gestor, pm_lector, grupo) -> None:
    total = _dos_marcas(client, gestor, grupo)
    body = _body(grupo, tipo="por_unidad", monto_unit="5", items=[{"item_id": TINTA, "monto_unit": "9"}])
    del body["monto_total"]
    por_unidad = client.post(BASE, json=body, headers=gestor).json()["id"]

    por_id = {c["id"]: c for c in client.get(BASE, headers=pm_lector).json()["items"]}

    assert _shares(por_id[total]) == [(ROUTER, None, 100.0)]
    assert [(i["item_id"], i["monto_unit"]) for i in por_id[por_unidad]["items"]] == [(TINTA, "9.00")]


def test_a_share_whose_product_left_the_reach_is_reported_as_such(client, gestor, grupo, db) -> None:
    out = _crear(client, gestor, grupo, monto_incluye_iva=True, items=[{"item_id": ROUTER, "reparto_monto": "5"}])
    db.query(OffsetGrupoFiltro).filter(OffsetGrupoFiltro.item_id == ROUTER).delete()
    db.flush()

    reparto = client.get(f"{BASE}/{out['id']}", headers=gestor).json()["resumen"]["reparto"]

    # It has VAT (21 %): the reason is the reach, not a missing VAT rate.
    assert reparto["motivo"] == f"El producto {ROUTER} no está en los grupos de la campaña"
    assert reparto["sin_asignar"] is None


def test_an_excess_below_a_cent_is_reported_exactly(client, gestor, grupo) -> None:
    cid = _crear(client, gestor, grupo, monto_total="100.00")["id"]
    shares = [{"item_id": ROUTER, "reparto_porcentaje": "50.0001"}, {"item_id": TINTA, "reparto_monto": "50.00"}]

    resp = _repartir(client, gestor, cid, shares)

    assert resp.status_code == 422
    assert "El reparto (100.0001) supera el monto total (100.00) en 0.0001" in resp.text
