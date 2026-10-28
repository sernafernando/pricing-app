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


def test_criterios_get_includes_costo_ars(client: TestClient, rma_superadmin_user, db) -> None:
    producto = ProductoERP(item_id=88003, codigo="SKU-PG-COST", descripcion="Costo ARS", costo=250.5)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88003", item_id=producto.item_id, codigo="SKU-PG-COST", activo=True))
    db.commit()

    response = client.get("/api/para-ganar/criterios/MLA88003", headers=_auth(rma_superadmin_user))
    assert response.status_code == 200, response.text
    assert response.json()["costo_ars"] == 250.5


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


def test_aplicar_defaults_creates_row_and_is_idempotent(
    client: TestClient, rma_superadmin_user, db
) -> None:
    from app.models.para_ganar_criterio_mla import ParaGanarCriterioMla

    producto = ProductoERP(item_id=88004, codigo="SKU-PG-DEF", descripcion="Aplicar defaults", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88004", item_id=producto.item_id, codigo="SKU-PG-DEF", activo=True))
    db.commit()

    headers = _auth(rma_superadmin_user)
    first = client.post("/api/para-ganar/criterios/MLA88004/aplicar-defaults", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["source"] == "mla"
    assert body["markup_min"] == 5.0
    assert body["markup_max"] == 15.0
    assert body["top_sellers"] == 5
    assert db.get(ParaGanarCriterioMla, "MLA88004") is not None

    custom = client.put(
        "/api/para-ganar/criterios/MLA88004",
        headers=headers,
        json={"markup_min": 9, "markup_max": 18, "top_sellers": 3},
    )
    assert custom.status_code == 200, custom.text

    second = client.post("/api/para-ganar/criterios/MLA88004/aplicar-defaults", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["markup_min"] == 9
    assert second.json()["top_sellers"] == 3


def test_aplicar_defaults_unknown_mla_404(client: TestClient, rma_superadmin_user) -> None:
    response = client.post(
        "/api/para-ganar/criterios/MLA_NO_EXISTE/aplicar-defaults",
        headers=_auth(rma_superadmin_user),
    )
    assert response.status_code == 404


def test_aplicar_masivo_overwrites_scope_keeps_precio(
    client: TestClient, rma_superadmin_user, db
) -> None:
    """Mass apply hits every MLA in scope; overwrites markup; keeps precio caps."""
    from app.models.ml_publication_link import MlPublicationLink
    from app.models.para_ganar_criterio_mla import ParaGanarCriterioMla

    headers = _auth(rma_superadmin_user)
    # Scope filter `ean` matches productos_erp.codigo (same as Productos search).
    shared_codigo = "7790000000010"
    for item_id, mla, codigo in (
        (88010, "MLA88010", shared_codigo),
        (88011, "MLA88011", shared_codigo),
        (88012, "MLA88012", "7790000000099"),
    ):
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=codigo,
                descripcion=f"Mass {mla}",
                costo=10,
            )
        )
        db.flush()
        db.add(PublicacionML(mla=mla, item_id=item_id, codigo=codigo, activo=True))
        db.add(
            MlPublicationLink(
                mla=mla,
                catalog_listing=True,
                catalog_product_id=f"CBT-{mla}",
            )
        )
    db.add(
        ParaGanarCriterioMla(
            mla="MLA88010",
            markup_min=1,
            markup_max=2,
            top_sellers=1,
            precio_min=1000,
            precio_max=9000,
            ganar_catalogo=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/para-ganar/criterios/aplicar-masivo",
        headers=headers,
        params={"ean": shared_codigo},
        json={
            "markup_min": 7,
            "markup_max": 14,
            "top_sellers": 4,
            "ganar_catalogo": False,
            "ignorar_internacionales": True,
            "descartar_stock_residual": False,
            "descartar_reputacion_baja": False,
            "techo_monopolio": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope_total"] == 2
    assert body["applied"] == 2
    assert body["created"] == 1
    assert body["updated"] == 1

    row_a = db.get(ParaGanarCriterioMla, "MLA88010")
    row_b = db.get(ParaGanarCriterioMla, "MLA88011")
    row_out = db.get(ParaGanarCriterioMla, "MLA88012")
    assert row_a is not None and float(row_a.markup_min) == 7.0
    assert float(row_a.precio_min) == 1000.0
    assert float(row_a.precio_max) == 9000.0
    assert row_a.ignorar_internacionales is True
    assert row_a.ganar_catalogo is False
    assert row_b is not None and float(row_b.markup_max) == 14.0
    assert row_b.precio_min is None
    assert row_out is None


def test_aplicar_masivo_empty_scope_422(client: TestClient, rma_superadmin_user) -> None:
    response = client.post(
        "/api/para-ganar/criterios/aplicar-masivo",
        headers=_auth(rma_superadmin_user),
        params={"ean": "EAN-QUE-NO-EXISTE-999"},
        json={"markup_min": 5, "markup_max": 15, "top_sellers": 5},
    )
    assert response.status_code == 422
