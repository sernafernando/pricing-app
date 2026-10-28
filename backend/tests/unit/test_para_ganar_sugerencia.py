"""PARA GANAR TOP board endpoint (compute-only)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.models.para_ganar_catalog_seller import ParaGanarCatalogSeller
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from tests.conftest import make_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def test_sugerencia_requires_auth(client: TestClient) -> None:
    response = client.get("/api/para-ganar/criterios/MLA123/sugerencia")
    assert response.status_code in (401, 403)


def test_sugerencia_rank_board_excludes_sellers(client: TestClient, rma_superadmin_user, db) -> None:
    from app.models.ml_catalog_competition import MLCatalogCompetition
    from app.models.ml_publication_link import MlPublicationLink

    producto = ProductoERP(item_id=88201, codigo="SKU-PG-TOP", descripcion="TOP test", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88201", item_id=producto.item_id, codigo="SKU-PG-TOP", activo=True))
    db.add(MlPublicationLink(mla="MLA88201", catalog_product_id="MLA999882", catalog_listing=True))
    db.add(
        ParaGanarCatalogSeller(
            catalog_product_id="MLA999882",
            seller_id="100",
            nickname="CHEAP",
            disposition="excluded",
        )
    )
    db.add(
        MLCatalogCompetition(
            mla="MLA88201",
            fecha_consulta=datetime.now(UTC),
            catalog_product_id="MLA999882",
            fetch_status="ok",
            our_item_id="MLA88201",
            our_seller_id="999",
            our_price=108.0,
            our_bucket_key="gold_special|3",
            competitors=[
                {
                    "seller_id": "100",
                    "seller_nickname": "CHEAP",
                    "item_id": "MLA_OTHER_1",
                    "price_ars": 100.0,
                    "same_bucket": True,
                    "bucket_key": "gold_special|3",
                },
                {
                    "seller_id": "200",
                    "seller_nickname": "MID",
                    "item_id": "MLA_OTHER_2",
                    "price_ars": 105.0,
                    "same_bucket": True,
                    "bucket_key": "gold_special|3",
                },
                {
                    "seller_id": "300",
                    "seller_nickname": "CLASSIC_CHEAP",
                    "item_id": "MLA_CLASSIC",
                    "price_ars": 90.0,
                    "same_bucket": False,
                    "bucket_key": "gold_special|0",
                },
                {
                    "seller_id": "999",
                    "seller_nickname": "US",
                    "item_id": "MLA88201",
                    "price_ars": 108.0,
                    "same_bucket": True,
                    "bucket_key": "gold_special|3",
                },
            ],
            competitor_count=4,
        )
    )
    db.commit()

    from app.routers.para_ganar import obtener_sugerencia_mla

    body = obtener_sugerencia_mla(mla="MLA88201", db=db, _user=rma_superadmin_user)
    assert body.excluded_count == 1
    assert body.our_rank == 2  # CHEAP excluded → MID #1, us #2 (classic ignored)
    assert body.in_top is True
    assert body.top_sellers == 5
    assert body.positions[0].rank == 1
    assert body.positions[0].sellers[0].nickname == "MID"
    assert all(s.nickname != "CLASSIC_CHEAP" for p in body.positions for s in p.sellers)
    assert body.message

    response = client.get(
        "/api/para-ganar/criterios/MLA88201/sugerencia",
        headers=_auth(rma_superadmin_user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["our_rank"] == 2


def test_sugerencia_flags_needs_refresh_without_snapshot(
    client: TestClient, rma_superadmin_user, db
) -> None:
    from app.models.ml_publication_link import MlPublicationLink

    producto = ProductoERP(item_id=88202, codigo="SKU-PG-NEED", descripcion="need snap", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88202", item_id=producto.item_id, codigo="SKU-PG-NEED", activo=True))
    db.add(MlPublicationLink(mla="MLA88202", catalog_product_id="MLA999883", catalog_listing=True))
    db.commit()

    response = client.get(
        "/api/para-ganar/criterios/MLA88202/sugerencia",
        headers=_auth(rma_superadmin_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["needs_competition_refresh"] is True
    assert body["catalog_product_id"] == "MLA999883"


def test_competencia_refresh_persists_and_returns_board(
    client: TestClient, rma_superadmin_user, db, monkeypatch
) -> None:
    from app.models.ml_catalog_competition import MLCatalogCompetition
    from app.models.ml_publication_link import MlPublicationLink
    import app.routers.para_ganar as pg

    producto = ProductoERP(item_id=88203, codigo="SKU-PG-REF", descripcion="refresh", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88203", item_id=producto.item_id, codigo="SKU-PG-REF", activo=True))
    db.add(MlPublicationLink(mla="MLA88203", catalog_product_id="MLA999884", catalog_listing=True))
    db.commit()

    def _fake_refresh(session, mlas):
        row = MLCatalogCompetition(
            mla=mlas[0],
            fecha_consulta=datetime.now(UTC),
            catalog_product_id="MLA999884",
            fetch_status="ok",
            our_item_id=mlas[0],
            our_seller_id="999",
            our_price=200.0,
            our_bucket_key="gold_special|3",
            competitors=[
                {
                    "seller_id": "999",
                    "seller_nickname": "US",
                    "item_id": mlas[0],
                    "price_ars": 200.0,
                    "same_bucket": True,
                    "bucket_key": "gold_special|3",
                },
                {
                    "seller_id": "111",
                    "seller_nickname": "OTRO",
                    "item_id": "MLA_X",
                    "price_ars": 180.0,
                    "same_bucket": True,
                    "bucket_key": "gold_special|3",
                },
            ],
            competitor_count=2,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return [row]

    monkeypatch.setattr(pg, "refrescar_competencia_catalogo", _fake_refresh)
    monkeypatch.setattr(pg, "resolve_maybe_async", lambda value: value)

    response = client.post(
        "/api/para-ganar/criterios/MLA88203/competencia/refresh",
        headers=_auth(rma_superadmin_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["needs_competition_refresh"] is False
    assert body["our_rank"] == 2
    assert body["positions"][0]["sellers"][0]["nickname"] == "OTRO"
