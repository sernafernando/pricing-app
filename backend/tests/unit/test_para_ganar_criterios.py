"""Focused tests for PARA GANAR per-MLA criteria GET/PUT."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from tests.conftest import make_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def test_criterios_get_requires_auth(client: TestClient) -> None:
    response = client.get("/api/para-ganar/criterios/MLA123")
    assert response.status_code in (401, 403)


def test_criterios_get_defaults_when_missing(client: TestClient, rma_superadmin_user) -> None:
    response = client.get("/api/para-ganar/criterios/MLA999999", headers=_auth(rma_superadmin_user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mla"] == "MLA999999"
    assert body["source"] == "default"
    assert body["markup_min"] == 5.0
    assert body["markup_max"] == 15.0
    assert body["top_sellers"] == 5
    assert body["precio_min"] is None
    assert body["precio_max"] is None
    assert body["ganar_catalogo"] is False
    assert body["ignorar_internacionales"] is False
    assert body["descartar_stock_residual"] is False
    assert body["descartar_reputacion_baja"] is False
    assert body["techo_monopolio"] is False


def test_criterios_put_unknown_mla_404(client: TestClient, rma_superadmin_user) -> None:
    response = client.put(
        "/api/para-ganar/criterios/MLA_NO_EXISTE",
        headers=_auth(rma_superadmin_user),
        json={"markup_min": 8, "ganar_catalogo": True},
    )
    assert response.status_code == 404


def test_criterios_put_rejects_inverted_markup(client: TestClient, rma_superadmin_user, db) -> None:
    producto = ProductoERP(item_id=88001, codigo="SKU-PG-CRIT", descripcion="Criterios test", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88001", item_id=producto.item_id, codigo="SKU-PG-CRIT", activo=True))
    db.commit()

    response = client.put(
        "/api/para-ganar/criterios/MLA88001",
        headers=_auth(rma_superadmin_user),
        json={"markup_min": 20, "markup_max": 5},
    )
    assert response.status_code == 422


def test_criterios_put_and_get_roundtrip(client: TestClient, rma_superadmin_user, db) -> None:
    producto = ProductoERP(item_id=88002, codigo="SKU-PG-CRIT2", descripcion="Criterios roundtrip", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88002", item_id=producto.item_id, codigo="SKU-PG-CRIT2", activo=True))
    db.commit()

    put = client.put(
        "/api/para-ganar/criterios/MLA88002",
        headers=_auth(rma_superadmin_user),
        json={
            "markup_min": 8,
            "markup_max": 22,
            "top_sellers": 5,
            "precio_min": 1000,
            "precio_max": 5000,
            "ganar_catalogo": True,
            "ignorar_internacionales": True,
            "descartar_stock_residual": False,
            "descartar_reputacion_baja": True,
            "techo_monopolio": True,
        },
    )
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["source"] == "mla"
    assert saved["markup_min"] == 8
    assert saved["ignorar_internacionales"] is True
    assert saved["techo_monopolio"] is True

    get = client.get("/api/para-ganar/criterios/MLA88002", headers=_auth(rma_superadmin_user))
    assert get.status_code == 200
    body = get.json()
    assert body["source"] == "mla"
    assert body["markup_max"] == 22
    assert body["top_sellers"] == 5
    assert body["descartar_reputacion_baja"] is True
