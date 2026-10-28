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
