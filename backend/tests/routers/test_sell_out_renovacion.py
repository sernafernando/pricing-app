"""Renewing a sell-out campaign (campaign system, slice B): `GET /api/sell-out/campanas/{id}/renovacion` returns the
draft of a NEW campaign in the shape `POST /api/sell-out/campanas` takes, and an optional `programa_id` on create.

Runs on the SQLite test database like `test_sell_out_campanas.py`; the "writes nothing" proof with the queue is
Postgres (`tests/services/sell_out/test_renovacion_postgres.py`)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutCampanaItem, SellOutPrograma
from app.schemas.sell_out import SellOutCampanaIn

BASE = "/api/sell-out/campanas"
ROUTER, SWITCH, TINTA = 2964, 2270, 3001


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    grant_permiso(rol_admin, "sell_out.gestionar")
    return admin_auth_headers


@pytest.fixture()
def lector(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    return admin_auth_headers


@pytest.fixture()
def grupos(db) -> list[int]:
    """Two groups: TP-Link (router and switch) and Marca (ink)."""
    marcas = {ROUTER: "TP-LINK", SWITCH: "TP-LINK", TINTA: "MARCA"}
    db.add_all(
        ProductoERP(item_id=i, codigo=f"C{i}", descripcion=f"P{i}", marca=m, categoria="X", iva=21.0)
        for i, m in marcas.items()
    )
    tplink, marca = OffsetGrupo(nombre="TP-Link redes"), OffsetGrupo(nombre="Marca tintas")
    db.add_all([tplink, marca])
    db.flush()
    db.add_all(
        [
            OffsetGrupoFiltro(grupo_id=tplink.id, item_id=ROUTER),
            OffsetGrupoFiltro(grupo_id=tplink.id, item_id=SWITCH),
            OffsetGrupoFiltro(grupo_id=marca.id, item_id=TINTA),
        ]
    )
    db.flush()
    return [tplink.id, marca.id]


def _programa(db, admin_user, nombre: str = "Rebate TP-Link", estado: str = "activo") -> SellOutPrograma:
    programa = SellOutPrograma(nombre=nombre, usuario_id=admin_user.id, estado=estado)
    db.add(programa)
    db.flush()
    return programa


def _crear(client, headers, body: dict) -> dict:
    resp = client.post(BASE, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _por_unidad(grupos: list[int], **overrides) -> dict:
    body = {
        "nombre": "Rebate Q4 2026",
        "descripcion": "Acuerdo trimestral con TP-Link",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "tipo": "por_unidad",
        "monto_unit": "1500.00",
        "moneda": "USD",
        "tc_modo": "fijo",
        "tipo_cambio": "1050.500000",
        "tope_unidades": 500,
        "tope_monto": "90000.00",
        "acumulable": False,
        "monto_incluye_iva": True,
        "grupo_ids": [grupos[1], grupos[0]],
        "items": [{"item_id": SWITCH, "monto_unit": "900.00"}],
    }
    body.update(overrides)
    return body


def _renovacion(client, headers, campana_id: int):
    return client.get(f"{BASE}/{campana_id}/renovacion", headers=headers)


def _num(valor):
    return None if valor is None else Decimal(valor)


# ── The draft ───────────────────────────────────────────────────────


def test_the_draft_copies_the_terms_and_proposes_the_next_quarter(client, gestor, grupos, db, admin_user) -> None:
    programa = _programa(db, admin_user)
    original = _crear(client, gestor, _por_unidad(grupos, programa_id=programa.id))
    db.get(SellOutCampana, original["id"]).estado = "anulada"  # also set apart from the copy: never copied
    db.flush()

    resp = _renovacion(client, gestor, original["id"])
    assert resp.status_code == 200, resp.text
    draft = resp.json()
    assert set(draft) == set(SellOutCampanaIn.model_fields)  # exactly what create takes, nothing else
    assert (draft["fecha_desde"], draft["fecha_hasta"]) == ("2027-01-01", "2027-03-31")
    assert draft["nombre"] == "Rebate Q1 2027"
    assert draft["descripcion"] == "Acuerdo trimestral con TP-Link"
    assert (draft["tipo"], _num(draft["monto_unit"]), draft["porcentaje"], draft["monto_total"]) == (
        "por_unidad",
        Decimal("1500"),
        None,
        None,
    )
    assert (draft["base_porcentaje"], draft["moneda"]) == ("costo", "USD")
    assert (draft["tc_modo"], _num(draft["tipo_cambio"])) == ("fijo", Decimal("1050.5"))
    assert (draft["tope_unidades"], _num(draft["tope_monto"])) == (500, Decimal("90000"))
    assert (draft["acumulable"], draft["monto_incluye_iva"]) == (False, True)
    assert draft["grupo_ids"] == [grupos[1], grupos[0]]  # in link order
    assert [(i["item_id"], _num(i["monto_unit"])) for i in draft["items"]] == [(SWITCH, Decimal("900"))]
    assert draft["programa_id"] == programa.id
    # Not copied: the state, the legacy offset, what it credited, the payment rate (none of them is an input).
    for clave in ("estado", "offset_origen_id", "resumen", "consumos", "tc_definido_en", "id", "usuario_id"):
        assert clave not in draft


def test_the_payment_rate_of_an_al_cobro_campaign_is_not_copied(client, gestor, grupos, db) -> None:
    original = _crear(client, gestor, _por_unidad(grupos, tc_modo="al_cobro", tipo_cambio=None, items=[]))
    campana = db.get(SellOutCampana, original["id"])
    campana.tipo_cambio, campana.tc_definido_en = Decimal("1100"), datetime(2027, 1, 10)
    db.flush()

    draft = _renovacion(client, gestor, original["id"]).json()
    assert (draft["tc_modo"], draft["tipo_cambio"]) == ("al_cobro", None)
    assert draft["items"] == []


def test_a_percentage_campaign_in_pesos_keeps_its_base_and_no_rate(client, gestor, grupos) -> None:
    body = _por_unidad(
        grupos,
        nombre="Campaña noviembre 2026",
        fecha_desde="2026-11-01",
        fecha_hasta="2026-11-15",
        tipo="porcentaje",
        monto_unit=None,
        porcentaje="2.5",
        base_porcentaje="precio_neto",
        moneda="ARS",
        tc_modo=None,
        tipo_cambio=None,
        monto_incluye_iva=False,
        items=[],
    )
    draft = _renovacion(client, gestor, _crear(client, gestor, body)["id"]).json()
    assert (draft["nombre"], draft["fecha_desde"], draft["fecha_hasta"]) == (
        "Campaña enero 2027",
        "2027-01-01",
        "2027-03-31",
    )
    assert (draft["tipo"], _num(draft["porcentaje"]), draft["base_porcentaje"]) == (
        "porcentaje",
        Decimal("2.5"),
        "precio_neto",
    )
    assert (draft["moneda"], draft["tc_modo"], draft["tipo_cambio"], draft["programa_id"]) == ("ARS", None, None, None)


def test_a_monto_total_campaign_copies_its_total_and_its_split(client, gestor, grupos) -> None:
    body = {
        "nombre": "Bono 4Q26",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "tipo": "monto_total",
        "monto_total": "2000000.00",
        "moneda": "ARS",
        "grupo_ids": [grupos[0]],
        "items": [
            {"item_id": ROUTER, "reparto_porcentaje": "60"},
            {"item_id": SWITCH, "reparto_monto": "500000.00"},
        ],
    }
    draft = _renovacion(client, gestor, _crear(client, gestor, body)["id"]).json()
    assert (draft["nombre"], draft["tipo"], _num(draft["monto_total"])) == ("Bono 1Q27", "monto_total", Decimal("2e6"))
    shares = [(i["item_id"], _num(i["reparto_porcentaje"]), _num(i["reparto_monto"])) for i in draft["items"]]
    assert shares == [(SWITCH, None, Decimal("500000")), (ROUTER, Decimal("60"), None)]


def test_an_archived_program_is_not_copied(client, gestor, grupos, db, admin_user) -> None:
    programa = _programa(db, admin_user)
    original = _crear(client, gestor, _por_unidad(grupos, programa_id=programa.id))
    programa.estado = "archivado"
    db.flush()
    assert _renovacion(client, gestor, original["id"]).json()["programa_id"] is None


def test_a_product_that_left_the_groups_reach_is_not_copied(client, gestor, grupos, db) -> None:
    original = _crear(client, gestor, _por_unidad(grupos))
    db.query(OffsetGrupoFiltro).filter(OffsetGrupoFiltro.item_id == SWITCH).delete()
    db.flush()
    assert _renovacion(client, gestor, original["id"]).json()["items"] == []


def test_the_draft_writes_nothing_and_the_original_does_not_change(client, gestor, grupos, db) -> None:
    original = _crear(client, gestor, _por_unidad(grupos))
    antes = (db.query(SellOutCampana).count(), db.query(SellOutCampanaItem).count(), db.query(Auditoria).count())
    assert _renovacion(client, gestor, original["id"]).status_code == 200
    db.expire_all()
    assert (
        db.query(SellOutCampana).count(),
        db.query(SellOutCampanaItem).count(),
        db.query(Auditoria).count(),
    ) == antes
    assert client.get(f"{BASE}/{original['id']}", headers=gestor).json() == original


def test_saving_the_draft_creates_a_new_campaign_and_leaves_the_original(
    client, gestor, grupos, db, admin_user
) -> None:
    programa = _programa(db, admin_user)
    original = _crear(client, gestor, _por_unidad(grupos, programa_id=programa.id))
    draft = _renovacion(client, gestor, original["id"]).json()

    nueva = _crear(client, gestor, draft)
    assert nueva["id"] != original["id"]
    assert (nueva["nombre"], nueva["fecha_desde"], nueva["estado"]) == ("Rebate Q1 2027", "2027-01-01", "activa")
    assert nueva["programa"] == {"id": programa.id, "nombre": "Rebate TP-Link"}
    assert [(i["item_id"], _num(i["monto_unit"])) for i in nueva["items"]] == [(SWITCH, Decimal("900"))]
    assert client.get(f"{BASE}/{original['id']}", headers=gestor).json() == original


def test_the_draft_needs_gestionar(client, lector, auth_headers) -> None:
    assert _renovacion(client, auth_headers, 1).status_code == 403
    resp = _renovacion(client, lector, 1)
    assert resp.status_code == 403
    assert "sell_out.gestionar" in resp.json()["error"]["message"]


def test_the_draft_of_an_unknown_campaign_is_404(client, gestor) -> None:
    resp = _renovacion(client, gestor, 999)
    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "La campaña 999 no existe"


# ── The program on create ───────────────────────────────────────────


def test_create_stores_the_program_sent_and_audits_it(client, gestor, grupos, db, admin_user) -> None:
    programa = _programa(db, admin_user)
    out = _crear(client, gestor, _por_unidad(grupos, programa_id=programa.id))
    assert (out["programa_id"], out["programa"]) == (programa.id, {"id": programa.id, "nombre": "Rebate TP-Link"})
    assert db.get(SellOutCampana, out["id"]).programa_id == programa.id
    audit = db.query(Auditoria).filter(Auditoria.valores_nuevos.isnot(None)).order_by(Auditoria.id.desc()).first()
    assert audit.valores_nuevos["programa_id"] == programa.id


def test_create_without_a_program_stays_as_before(client, gestor, grupos, db) -> None:
    out = _crear(client, gestor, _por_unidad(grupos))
    assert (out["programa_id"], out["programa"]) == (None, None)
    audit = db.query(Auditoria).order_by(Auditoria.id.desc()).first()
    assert "programa_id" not in audit.valores_nuevos


def test_create_refuses_an_unknown_or_archived_program(client, gestor, grupos, db, admin_user) -> None:
    archivado = _programa(db, admin_user, "Viejo", estado="archivado")
    resp = client.post(BASE, json=_por_unidad(grupos, programa_id=9999), headers=gestor)
    assert (resp.status_code, resp.json()["error"]["message"]) == (404, "El programa 9999 no existe.")
    resp = client.post(BASE, json=_por_unidad(grupos, programa_id=archivado.id), headers=gestor)
    assert (resp.status_code, resp.json()["error"]["message"]) == (422, "El programa «Viejo» está archivado.")
    assert db.query(SellOutCampana).count() == 0


def test_an_edit_ignores_a_program_sent_and_keeps_the_stored_one(client, gestor, grupos, db, admin_user) -> None:
    """Assignment goes through `POST /programas/asignar`, which audits it; an edit never changes it."""
    guardado, otro = _programa(db, admin_user), _programa(db, admin_user, "Otro")
    out = _crear(client, gestor, _por_unidad(grupos, programa_id=guardado.id))
    for programa_id in (otro.id, None):
        resp = client.put(f"{BASE}/{out['id']}", json=_por_unidad(grupos, programa_id=programa_id), headers=gestor)
        assert resp.status_code == 200, resp.text
        assert resp.json()["programa_id"] == guardado.id
