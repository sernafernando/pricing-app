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
            competitors=[
                {
                    "seller_id": "100",
                    "seller_nickname": "CHEAP",
                    "item_id": "MLA_OTHER_1",
                    "price_ars": 100.0,
                },
                {
                    "seller_id": "200",
                    "seller_nickname": "MID",
                    "item_id": "MLA_OTHER_2",
                    "price_ars": 105.0,
                },
                {
                    "seller_id": "999",
                    "seller_nickname": "US",
                    "item_id": "MLA88201",
                    "price_ars": 108.0,
                },
            ],
            competitor_count=3,
        )
    )
    db.commit()

    from app.routers.para_ganar import obtener_sugerencia_mla

    body = obtener_sugerencia_mla(mla="MLA88201", db=db, _user=rma_superadmin_user)
    assert body.excluded_count == 1
    assert body.our_rank == 2  # CHEAP excluded → MID #1, us #2
    assert body.in_top is True
    assert body.top_sellers == 5
    assert body.positions[0].rank == 1
    assert body.positions[0].sellers[0].nickname == "MID"
    assert body.message

    response = client.get(
        "/api/para-ganar/criterios/MLA88201/sugerencia",
        headers=_auth(rma_superadmin_user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["our_rank"] == 2
