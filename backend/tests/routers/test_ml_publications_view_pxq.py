"""S12: Productos' wholesale (PxQ) quick view on Publicaciones ML's Producto rows.

Owner rule: everything Productos does goes to Publicaciones ML. Productos shows beside each product "N tramos · desde
$X" (`PxqTramosBadge`) from `pxq_tramos` (the deepest tier ladder of one of the product's publications) and
`pxq_precio_desde` (the lowest tier price of any of them), over every publication of the product (`publicaciones_ml`).
A Producto row carries the same two fields, only when the product has tiers; a failed tier read leaves them out
(fail-open, like Productos: the badge is an ornament, the list still answers).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services import ml_pxq_tiers_read_service
from app.services.ml_pxq_tiers_read_service import PxqTier
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_presence import fill
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

PRODUCTS_URL = "/api/ml-publications/view/products"
PXQ_KEYS = ("pxq_tramos", "pxq_precio_desde")


@pytest.fixture()
def reader(client, db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def publicaciones(db) -> None:
    """Product 77 has two publications in the ERP mirror, 78 one."""
    db.add_all(ProductoERP(item_id=item_id, codigo=f"C{item_id}", descripcion=f"P{item_id}") for item_id in (77, 78))
    db.flush()
    db.add_all(
        PublicacionML(mla=mla, item_id=item_id) for mla, item_id in (("MLA7701", 77), ("MLA7702", 77), ("MLA7801", 78))
    )
    db.flush()


def pxq(client, headers) -> dict[str, dict]:
    response = client.get(PRODUCTS_URL, headers=headers)
    assert response.status_code == 200, response.text
    return {row["key"]: {k: row[k] for k in PXQ_KEYS if k in row} for row in response.json()["rows"]}


def test_a_product_row_carries_its_deepest_ladder_and_lowest_price(client, pg, reader, publicaciones, monkeypatch):
    seed_rows(pg, fill)
    asked = []

    def tiers(mla_ids):
        asked.append(sorted(mla_ids))
        return {
            "MLA7701": [PxqTier(3, 900.0), PxqTier(6, 850.0)],
            "MLA7702": [PxqTier(2, 990.0), PxqTier(5, 940.0), PxqTier(10, 800.0)],
        }

    monkeypatch.setattr(ml_pxq_tiers_read_service, "fetch_pxq_tiers_by_mla", tiers)

    assert pxq(client, reader) == {
        "77": {"pxq_tramos": 3, "pxq_precio_desde": 800.0},  # the deepest single ladder, not 5
        "78": {},  # no tiers: no fields
        "0": {},  # the "Sin producto" row
    }
    assert asked == [["MLA7701", "MLA7702", "MLA7801"]]  # one read for the page


def test_a_failed_tier_read_leaves_the_rows_without_the_badge(client, pg, reader, publicaciones, monkeypatch):
    seed_rows(pg, fill)

    def down(mla_ids):
        raise OperationalError("SELECT", {}, Exception("mlwebhook down"))

    monkeypatch.setattr(ml_pxq_tiers_read_service, "fetch_pxq_tiers_by_mla", down)

    assert pxq(client, reader) == {"77": {}, "78": {}, "0": {}}


def test_products_without_publications_ask_nothing(client, pg, reader, monkeypatch):
    seed_rows(pg, fill)
    monkeypatch.setattr(
        ml_pxq_tiers_read_service, "fetch_pxq_tiers_by_mla", lambda mla_ids: pytest.fail("no tier read expected")
    )

    assert pxq(client, reader) == {"77": {}, "78": {}, "0": {}}
