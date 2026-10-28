"""P2: periodicidad subscription CRUD + scope validation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.para_ganar_periodicidad import validate_scope_payload
from tests.conftest import make_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def test_validate_scope_all_clears_children() -> None:
    cleaned = validate_scope_payload(
        scope_mode="all",
        mlas=["MLA1"],
        tipos_publicacion=["6"],
        pricelist_ids=[14],
        tienda_oficial_ids=[1],
    )
    assert cleaned["scope_mode"] == "all"
    assert cleaned["mlas"] == []
    assert cleaned["tipos_publicacion"] == []
    assert cleaned["pricelist_ids"] == []
    assert cleaned["tienda_oficial_ids"] == []


def test_validate_scope_mlas_requires_list() -> None:
    with pytest.raises(ValueError, match="al menos un MLA"):
        validate_scope_payload(
            scope_mode="mlas",
            mlas=[],
            tipos_publicacion=None,
            pricelist_ids=None,
            tienda_oficial_ids=None,
        )


def test_validate_scope_rules_requires_dimension() -> None:
    with pytest.raises(ValueError, match="tipos_publicacion"):
        validate_scope_payload(
            scope_mode="rules",
            mlas=None,
            tipos_publicacion=[],
            pricelist_ids=[],
            tienda_oficial_ids=[],
        )


def test_periodicidad_requires_auth(client: TestClient) -> None:
    response = client.get("/api/para-ganar/periodicidad")
    assert response.status_code in (401, 403)


def test_periodicidad_put_get_delete_roundtrip(client: TestClient, rma_superadmin_user) -> None:
    headers = _auth(rma_superadmin_user)
    ean = "7790001122334"

    put_res = client.put(
        f"/api/para-ganar/periodicidad/{ean}",
        headers=headers,
        json={
            "enabled": True,
            "scope_mode": "rules",
            "tipos_publicacion": ["6", "clasica"],
            "pricelist_ids": [14],
            "tienda_oficial_ids": [57997],
        },
    )
    assert put_res.status_code == 200, put_res.text
    body = put_res.json()
    assert body["ean"] == ean
    assert body["scope_mode"] == "rules"
    assert body["tipos_publicacion"] == ["6", "clasica"]
    assert body["pricelist_ids"] == [14]
    assert body["tienda_oficial_ids"] == [57997]
    assert body["mlas"] == []

    get_res = client.get(f"/api/para-ganar/periodicidad/{ean}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["scope_mode"] == "rules"

    list_res = client.get("/api/para-ganar/periodicidad", headers=headers, params={"q": "779000"})
    assert list_res.status_code == 200
    listed = list_res.json()
    assert listed["total"] >= 1
    assert any(item["ean"] == ean for item in listed["items"])

    mlas_res = client.put(
        f"/api/para-ganar/periodicidad/{ean}",
        headers=headers,
        json={"enabled": True, "scope_mode": "mlas", "mlas": ["mla111", "MLA222"]},
    )
    assert mlas_res.status_code == 200, mlas_res.text
    assert mlas_res.json()["mlas"] == ["MLA111", "MLA222"]
    assert mlas_res.json()["tipos_publicacion"] == []

    del_res = client.delete(f"/api/para-ganar/periodicidad/{ean}", headers=headers)
    assert del_res.status_code == 204
    assert client.get(f"/api/para-ganar/periodicidad/{ean}", headers=headers).status_code == 404


def test_periodicidad_put_rejects_bad_rules(client: TestClient, rma_superadmin_user) -> None:
    response = client.put(
        "/api/para-ganar/periodicidad/779999",
        headers=_auth(rma_superadmin_user),
        json={"scope_mode": "rules", "tipos_publicacion": [], "pricelist_ids": []},
    )
    assert response.status_code == 422


def test_periodicidad_catalogo_lists_subscribed_and_not(client: TestClient, rma_superadmin_user, db) -> None:
    """P3.1: catalog lists EANs in scope; suscripto filter; MLA checkboxes from filters."""
    from app.models.ml_publication_link import MlPublicationLink
    from app.models.producto import ProductoERP
    from app.models.publicacion_ml import PublicacionML

    catalog_id = "MLA-PG-PER-CAT-993"
    ean_sub = "779000PERCAT01"
    ean_plain = "779000PERCAT02"
    p_sub = ProductoERP(item_id=99301, codigo=ean_sub, descripcion="periodicidad sub", marca="Acme", costo=10)
    p_plain = ProductoERP(item_id=99302, codigo=ean_plain, descripcion="periodicidad plain", marca="Acme", costo=10)
    db.add_all([p_sub, p_plain])
    db.flush()
    for mla, item_id, codigo in (
        ("MLA99301A", 99301, ean_sub),
        ("MLA99301B", 99301, ean_sub),
        ("MLA99302A", 99302, ean_plain),
    ):
        db.add(
            PublicacionML(
                mla=mla,
                item_id=item_id,
                codigo=codigo,
                activo=True,
                pricelist_id=4,
                item_title=f"Title {mla}",
                lista_nombre="Lista test",
            )
        )
        db.add(
            MlPublicationLink(
                mla=mla,
                catalog_product_id=catalog_id,
                catalog_listing=True,
            )
        )
    db.commit()

    headers = _auth(rma_superadmin_user)
    put = client.put(
        f"/api/para-ganar/periodicidad/{ean_sub}",
        headers=headers,
        json={"enabled": True, "scope_mode": "all"},
    )
    assert put.status_code == 200, put.text

    all_res = client.get(
        "/api/para-ganar/periodicidad/catalogo",
        headers=headers,
        params={"catalog_product_id": catalog_id, "page_size": 50},
    )
    assert all_res.status_code == 200, all_res.text
    body = all_res.json()
    eans = {row["ean"]: row for row in body["items"]}
    assert ean_sub in eans and ean_plain in eans
    assert eans[ean_sub]["suscripto"] is True
    assert eans[ean_sub]["mla_count"] == 2
    assert eans[ean_plain]["suscripto"] is False

    only_sub = client.get(
        "/api/para-ganar/periodicidad/catalogo",
        headers=headers,
        params={"catalog_product_id": catalog_id, "suscripto": True},
    )
    assert only_sub.status_code == 200
    assert {row["ean"] for row in only_sub.json()["items"]} == {ean_sub}

    only_plain = client.get(
        "/api/para-ganar/periodicidad/catalogo",
        headers=headers,
        params={"catalog_product_id": catalog_id, "suscripto": False},
    )
    assert only_plain.status_code == 200
    assert {row["ean"] for row in only_plain.json()["items"]} == {ean_plain}

    mlas_res = client.get(
        f"/api/para-ganar/periodicidad/catalogo/{ean_sub}/mlas",
        headers=headers,
        params={"catalog_product_id": catalog_id},
    )
    assert mlas_res.status_code == 200, mlas_res.text
    mlas = {row["mla"] for row in mlas_res.json()["mlas"]}
    assert mlas == {"MLA99301A", "MLA99301B"}
