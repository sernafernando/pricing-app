"""S12: Productos' wholesale (PxQ) quick view on Publicaciones ML's Producto rows.

Owner rule: everything Productos does goes to Publicaciones ML. Productos shows beside each product "N tramos · desde
$X" (`PxqTramosBadge`) from `pxq_tramos` (the deepest tier ladder of one of the product's publications) and
`pxq_precio_desde` (the lowest tier price of any of them), over every publication of the product (`publicaciones_ml`).
A Producto row carries the same two fields over every publication LINKED to the product (the store's own links, whatever
the filter shows), only when the product has tiers; a failed tier read leaves them out (fail-open, like Productos: the
badge is an ornament, the list still answers).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.services import ml_pxq_tiers_read_service
from app.services.ml_pxq_tiers_read_service import PxqTier
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_presence import fill
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

PRODUCTS_URL = "/api/ml-publications/view/products"
PXQ_KEYS = ("pxq_tramos", "pxq_precio_desde")


@pytest.fixture()
def reader(client, db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


def linked(pg) -> None:
    """`fill` links MLA1 to 77 and MLA2 to 78; 77 has another publication linked (and a variation of MLA1, once)."""
    seed_rows(pg, fill)
    with pg.begin() as conn:
        seed.add_link(conn, "MLA7702", 77)
        seed.add_link(conn, "MLA1", 77, variation_id=5)


def pxq(client, headers) -> dict[str, dict]:
    response = client.get(PRODUCTS_URL, headers=headers)
    assert response.status_code == 200, response.text
    return {row["key"]: {k: row[k] for k in PXQ_KEYS if k in row} for row in response.json()["rows"]}


def test_a_product_row_carries_its_deepest_ladder_and_lowest_price(client, pg, reader, monkeypatch):
    linked(pg)
    asked = []

    def tiers(mla_ids):
        asked.append(sorted(mla_ids))
        return {
            "MLA1": [PxqTier(3, 900.0), PxqTier(6, 850.0)],
            "MLA7702": [PxqTier(2, 990.0), PxqTier(5, 940.0), PxqTier(10, 800.0)],
        }

    monkeypatch.setattr(ml_pxq_tiers_read_service, "fetch_pxq_tiers_by_mla", tiers)

    assert pxq(client, reader) == {
        "77": {"pxq_tramos": 3, "pxq_precio_desde": 800.0},  # the deepest single ladder, not 5
        "78": {},  # no tiers: no fields
        "0": {},  # the "Sin producto" row
    }
    assert asked == [["MLA1", "MLA2", "MLA7702"]]  # one read for the page, each MLA once


def test_a_failed_tier_read_leaves_the_rows_without_the_badge(client, pg, reader, monkeypatch):
    linked(pg)

    def down(mla_ids):
        raise OperationalError("SELECT", {}, Exception("mlwebhook down"))

    monkeypatch.setattr(ml_pxq_tiers_read_service, "fetch_pxq_tiers_by_mla", down)

    assert pxq(client, reader) == {"77": {}, "78": {}, "0": {}}
