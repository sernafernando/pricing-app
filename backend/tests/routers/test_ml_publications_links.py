"""P5L2.T3: the product-link endpoints (`/api/ml-publications/...`).

Authentication, permission and the user table live in the SQLite test database; the link tables live in
a throwaway Postgres schema (`mlpub_pg`), reached through the router's own `get_links_db` seam. Items are
real captures stored through `apply_fetch`; products and the audit table are plain test data.

Decision recorded here (design D20): link WRITES need `links.enabled` (409 otherwise); READS never do.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.permiso import Permiso, RolPermisoBase
from app.routers import ml_publications_links
from app.services.ml_publications.settings_store import set_setting
from tests.services.ml_publications.conftest import item_with_variations, mlpub_pg, sample_item  # noqa: F401
from tests.services.ml_publications.test_links_manual import AUDIT_DDL
from tests.services.ml_publications.test_links_store import ITEM, SKU_A, add_product
from tests.services.ml_publications.test_store_apply_fetch import apply

pytestmark = pytest.mark.postgres

BASE = "/api/ml-publications"
VER = "ml_ops.ver"
VINCULAR = "ml_publicaciones.vincular"


def grant(db, rol, *codigos: str) -> None:
    for codigo in codigos:
        permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
        if permiso is None:
            permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="ml_ops", orden=205)
            db.add(permiso)
            db.flush()
        db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


@pytest.fixture()
def pg(client, request):
    """The link tables (plus products and audit) behind the router. `client` goes first so the shared column
    types are restored to Postgres' after the SQLite engine patched them."""
    from app.models.producto import ProductoERP

    engine = request.getfixturevalue("mlpub_pg")
    ProductoERP.__table__.create(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(AUDIT_DDL))
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    sessions: list[Session] = []

    def _links_db():
        session = factory()
        sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[ml_publications_links.get_links_db] = _links_db
    yield engine
    app.dependency_overrides.pop(ml_publications_links.get_links_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def writer(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, VINCULAR)
    return admin_auth_headers


@pytest.fixture()
def links_on(pg):
    set_setting("links.enabled", True, "test")
    return pg


def rows(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).mappings().all()


def counts(engine) -> dict:
    return {
        "links": len(rows(engine, "SELECT 1 FROM ml_item_product_links")),
        "log": len(rows(engine, "SELECT 1 FROM ml_change_log WHERE resource_type = 'product_link'")),
        "audit": len(rows(engine, "SELECT 1 FROM auditoria")),
    }


def put_manual(client, headers, producto_item_id=42, variation_id=0, item_id=ITEM, **body):
    return client.put(
        f"{BASE}/items/{item_id}/product-links/{variation_id}",
        json={"producto_item_id": producto_item_id, **body},
        headers=headers,
    )


class TestContract:
    def test_the_permission_codes_are_the_catalog_ones(self) -> None:
        assert ml_publications_links.PERMISO_VER == VER
        assert ml_publications_links.PERMISO_VINCULAR == VINCULAR

    @pytest.mark.parametrize(
        "method, path",
        [
            ("get", f"/items/{ITEM}/product-links"),
            ("put", f"/items/{ITEM}/product-links/0"),
            ("put", f"/items/{ITEM}/product-links/0/none"),
            ("post", f"/items/{ITEM}/product-links/0/revert-auto"),
            ("get", "/product-links?class=unmatched"),
            ("get", "/product-links/coverage"),
        ],
    )
    def test_every_route_requires_authentication(self, client, pg, method, path) -> None:
        response = getattr(client, method)(BASE + path, **({"json": {}} if method == "put" else {}))
        assert response.status_code in (401, 403)

    def test_there_is_no_delete_verb_on_any_link_route(self) -> None:
        verbs = {method for route in ml_publications_links.router.routes for method in getattr(route, "methods", set())}
        assert verbs == {"GET", "PUT", "POST"}


class TestReadItem:
    def test_without_ml_ops_ver_is_403(self, client, pg, auth_headers) -> None:
        assert client.get(f"{BASE}/items/{ITEM}/product-links", headers=auth_headers).status_code == 403

    def test_returns_the_units_with_suggestion_and_candidates_even_while_linking_is_off(
        self, client, pg, reader
    ) -> None:
        add_product(pg, 41, SKU_A)
        add_product(pg, 5, SKU_A)
        apply(sample_item(ITEM), ITEM)

        response = client.get(f"{BASE}/items/{ITEM}/product-links", headers=reader)

        assert response.status_code == 200
        body = response.json()
        assert body["item_id"] == ITEM
        (unit,) = body["units"]
        assert unit["variation_id"] == 0 and unit["link"] is None
        assert unit["suggestion"]["status"] == "conflict"
        assert [c["item_id"] for c in unit["suggestion"]["candidates"]] == [5, 41]

    def test_an_unknown_item_is_404(self, client, pg, reader) -> None:
        assert client.get(f"{BASE}/items/MLA1/product-links", headers=reader).status_code == 404


class TestSetManual:
    def test_without_the_vincular_permission_is_403_and_nothing_is_written(self, client, links_on, reader) -> None:
        add_product(links_on, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)
        before = counts(links_on)

        response = put_manual(client, reader)

        assert response.status_code == 403
        assert counts(links_on) == before

    def test_is_409_while_linking_is_off_and_nothing_is_written(self, client, pg, writer) -> None:
        add_product(pg, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)
        before = counts(pg)

        response = put_manual(client, writer)

        assert response.status_code == 409
        assert counts(pg) == before

    def test_links_by_hand_and_records_the_authenticated_user_as_the_author(
        self, client, links_on, writer, admin_user
    ) -> None:
        add_product(links_on, 41, SKU_A)
        add_product(links_on, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)

        response = put_manual(client, writer, 42, note="  checked by hand  ")

        assert response.status_code == 200
        body = response.json()
        assert body["changed"] is True
        assert body["unit"]["link"]["source"] == "manual"
        assert body["unit"]["link"]["producto"]["item_id"] == 42
        assert body["unit"]["link"]["note"] == "checked by hand"
        assert body["unit"]["suggestion"]["differs"] is True
        (link,) = rows(links_on, "SELECT * FROM ml_item_product_links")
        assert (link["source"], link["producto_item_id"], link["linked_by"]) == ("manual", 42, admin_user.id)
        assert counts(links_on) == {"links": 1, "log": 1, "audit": 1}
        (audit,) = rows(links_on, "SELECT * FROM auditoria")
        assert (audit["tipo_accion"], audit["usuario_id"], audit["item_id"]) == (
            "ML_VINCULO_MANUAL",
            admin_user.id,
            42,
        )

    def test_the_event_is_written_only_with_the_events_flag(self, client, links_on, writer) -> None:
        add_product(links_on, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)
        put_manual(client, writer, 42)
        assert rows(links_on, "SELECT 1 FROM ml_item_events") == []

        set_setting("events.enabled", True, "test")
        apply(sample_item("MLA874027718"), "MLA874027718")
        put_manual(client, writer, 42, item_id="MLA874027718")

        events = rows(links_on, "SELECT * FROM ml_item_events")
        assert [(e["event_type"], e["item_id"]) for e in events] == [("product_link_changed", "MLA874027718")]

    def test_the_author_can_never_come_from_the_body(self, client, links_on, writer) -> None:
        add_product(links_on, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)
        before = counts(links_on)

        response = put_manual(client, writer, 42, linked_by=999)

        assert response.status_code == 422
        assert counts(links_on) == before

    def test_a_missing_product_is_422_and_nothing_is_written(self, client, links_on, writer) -> None:
        apply(sample_item(ITEM), ITEM)
        before = counts(links_on)

        response = put_manual(client, writer, 999)

        assert response.status_code == 422
        assert "999" in response.json()["error"]["message"]
        assert counts(links_on) == before

    def test_a_variation_that_is_not_part_of_the_item_is_422(self, client, links_on, writer) -> None:
        add_product(links_on, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)
        before = counts(links_on)

        response = put_manual(client, writer, 42, variation_id=123)

        assert response.status_code == 422
        assert counts(links_on) == before

    def test_a_variation_of_an_item_with_variations_is_addressed_by_its_id(self, client, links_on, writer) -> None:
        add_product(links_on, 42, "OTHER")
        body = item_with_variations()
        apply(body, body["id"])

        response = put_manual(client, writer, 42, variation_id=175550253196, item_id=body["id"])

        assert response.status_code == 200
        sources = {r["variation_id"]: r["source"] for r in rows(links_on, "SELECT * FROM ml_item_product_links")}
        assert sources[175550253196] == "manual" and sources[175550253195] == "sku_auto"

    def test_an_unknown_item_is_404(self, client, links_on, writer) -> None:
        add_product(links_on, 42, "OTHER")
        assert put_manual(client, writer, 42, item_id="MLA1").status_code == 404

    @pytest.mark.parametrize(
        "body", [{"producto_item_id": 0}, {"producto_item_id": "x"}, {}, {"producto_item_id": 4, "note": "n" * 501}]
    )
    def test_a_malformed_body_is_422(self, client, links_on, writer, body) -> None:
        apply(sample_item(ITEM), ITEM)
        response = client.put(f"{BASE}/items/{ITEM}/product-links/0", json=body, headers=writer)
        assert response.status_code == 422

    def test_a_negative_variation_id_is_422(self, client, links_on, writer) -> None:
        assert put_manual(client, writer, 42, variation_id=-1).status_code == 422

    def test_repeating_the_same_request_changes_nothing(self, client, links_on, writer) -> None:
        add_product(links_on, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)
        put_manual(client, writer, 42, note="n")
        before = counts(links_on)

        response = put_manual(client, writer, 42, note="n")

        assert response.status_code == 200 and response.json()["changed"] is False
        assert counts(links_on) == before


class TestNoneAndRevert:
    def test_none_needs_the_vincular_permission(self, client, links_on, reader) -> None:
        apply(sample_item(ITEM), ITEM)
        before = counts(links_on)
        response = client.put(f"{BASE}/items/{ITEM}/product-links/0/none", json={}, headers=reader)
        assert response.status_code == 403
        assert counts(links_on) == before

    def test_none_is_409_while_linking_is_off(self, client, pg, writer) -> None:
        apply(sample_item(ITEM), ITEM)
        assert client.put(f"{BASE}/items/{ITEM}/product-links/0/none", json={}, headers=writer).status_code == 409

    def test_none_marks_the_unit_as_explicitly_without_product(self, client, links_on, writer, admin_user) -> None:
        apply(sample_item(ITEM), ITEM)

        response = client.put(
            f"{BASE}/items/{ITEM}/product-links/0/none", json={"note": "it is a bundle"}, headers=writer
        )

        assert response.status_code == 200
        link = response.json()["unit"]["link"]
        assert (link["source"], link["match_status"], link["producto"]) == ("manual_none", "no_product", None)
        (audit,) = rows(links_on, "SELECT * FROM auditoria")
        assert (audit["tipo_accion"], audit["usuario_id"]) == ("ML_VINCULO_SIN_PRODUCTO", admin_user.id)

    def test_none_accepts_an_empty_body_and_unknown_unit_is_422(self, client, links_on, writer) -> None:
        apply(sample_item(ITEM), ITEM)
        assert client.put(f"{BASE}/items/{ITEM}/product-links/0/none", headers=writer).status_code == 200
        assert client.put(f"{BASE}/items/{ITEM}/product-links/9/none", json={}, headers=writer).status_code == 422

    def test_revert_returns_the_unit_to_the_automatic_suggestion(self, client, links_on, writer, admin_user) -> None:
        add_product(links_on, 41, SKU_A)
        add_product(links_on, 42, "OTHER")
        apply(sample_item(ITEM), ITEM)
        put_manual(client, writer, 42)

        response = client.post(f"{BASE}/items/{ITEM}/product-links/0/revert-auto", headers=writer)

        assert response.status_code == 200
        body = response.json()
        assert body["changed"] is True
        assert (body["unit"]["link"]["source"], body["unit"]["link"]["producto"]["item_id"]) == ("sku_auto", 41)
        assert [r["tipo_accion"] for r in rows(links_on, "SELECT * FROM auditoria ORDER BY id")] == [
            "ML_VINCULO_MANUAL",
            "ML_VINCULO_AUTOMATICO",
        ]

    def test_revert_needs_permission_and_the_flag(self, client, links_on, reader) -> None:
        apply(sample_item(ITEM), ITEM)
        assert client.post(f"{BASE}/items/{ITEM}/product-links/0/revert-auto", headers=reader).status_code == 403

    def test_revert_is_409_while_linking_is_off(self, client, pg, writer) -> None:
        apply(sample_item(ITEM), ITEM)
        assert client.post(f"{BASE}/items/{ITEM}/product-links/0/revert-auto", headers=writer).status_code == 409

    def test_revert_of_an_unknown_item_is_404(self, client, links_on, writer) -> None:
        assert client.post(f"{BASE}/items/MLA1/product-links/0/revert-auto", headers=writer).status_code == 404


def seed_links(engine, count: int) -> None:
    from datetime import datetime, timezone

    with engine.begin() as conn:
        for n in range(count):
            conn.execute(
                text(
                    "INSERT INTO ml_item_product_links (item_id, variation_id, source, match_status, matched_sku, "
                    "evaluated_at, linked_at) VALUES (:i, 0, 'sku_auto', 'unmatched', 'X', :t, :t)"
                ),
                {"i": f"MLA{n:04d}", "t": datetime(2026, 10, 6, tzinfo=timezone.utc)},
            )


class TestLists:
    def test_without_ml_ops_ver_is_403(self, client, pg, auth_headers) -> None:
        assert client.get(f"{BASE}/product-links?class=unmatched", headers=auth_headers).status_code == 403

    def test_lists_a_class_with_keyset_pages(self, client, pg, reader) -> None:
        seed_links(pg, 5)

        first = client.get(f"{BASE}/product-links?class=unmatched&limit=2", headers=reader)
        assert first.status_code == 200
        page = first.json()
        assert [i["item_id"] for i in page["items"]] == ["MLA0000", "MLA0001"] and page["next_cursor"]
        second = client.get(
            f"{BASE}/product-links",
            params={"class": "unmatched", "limit": 2, "cursor": page["next_cursor"]},
            headers=reader,
        ).json()
        assert [i["item_id"] for i in second["items"]] == ["MLA0002", "MLA0003"]
        last = client.get(
            f"{BASE}/product-links",
            params={"class": "unmatched", "limit": 2, "cursor": second["next_cursor"]},
            headers=reader,
        ).json()
        assert [i["item_id"] for i in last["items"]] == ["MLA0004"] and last["next_cursor"] is None

    @pytest.mark.parametrize("cls", ["conflict", "manual_differs", "dangling"])
    def test_the_other_classes_answer_even_when_empty(self, client, pg, reader, cls) -> None:
        response = client.get(f"{BASE}/product-links?class={cls}", headers=reader)
        assert response.status_code == 200 and response.json()["items"] == []

    @pytest.mark.parametrize(
        "query",
        [
            "class=everything",
            "",
            "class=unmatched&limit=201",
            "class=unmatched&limit=0",
            "class=unmatched&cursor=nonsense",
        ],
    )
    def test_bad_parameters_are_422(self, client, pg, reader, query) -> None:
        assert client.get(f"{BASE}/product-links?{query}", headers=reader).status_code == 422


class TestCoverage:
    def test_without_ml_ops_ver_is_403(self, client, pg, auth_headers) -> None:
        assert client.get(f"{BASE}/product-links/coverage", headers=auth_headers).status_code == 403

    def test_reports_counts_by_class_and_status_with_bounded_samples(self, client, pg, reader) -> None:
        apply(sample_item(ITEM), ITEM)
        seed_links(pg, 3)

        response = client.get(f"{BASE}/product-links/coverage?samples=2", headers=reader)

        assert response.status_code == 200
        body = response.json()
        assert body["classes"]["unmatched_key_not_found"] == 3
        assert body["classes"]["never_evaluated"] == 1  # the stored item has no link row yet
        assert body["total_units"] == sum(body["classes"].values())
        assert len(body["samples"]["unmatched_key_not_found"]) == 2
        assert "by_status" in body and "manual_differs" in body

    def test_the_samples_parameter_is_bounded(self, client, pg, reader) -> None:
        assert client.get(f"{BASE}/product-links/coverage?samples=51", headers=reader).status_code == 422
