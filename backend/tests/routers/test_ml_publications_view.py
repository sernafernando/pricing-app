"""P5.T5: `GET /api/ml-publications/view/items` (permission, contract, timeouts, constant statements, honest state).

Authentication, permission and the user table live in the SQLite test database; the store tables live in a
throwaway Postgres schema, reached through the router's own `get_view_db` seam. The report behind the
honest-state block is the real `status.build_status` over that schema.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.main import app
from app.models.marca_pm import MarcaPM
from app.routers import ml_publications_view
from app.services.ml_publications import settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.view import listing, status_block
from tests.routers.test_ml_publications_links import grant
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.test_status import WORKER_STATE_DDL
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import STORES_DDL

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/items"
VER = "ml_ops.ver"
GANANCIA = "ml_metricas.ver_ganancia"


@pytest.fixture()
def pg(client, request, monkeypatch):
    """The store behind the router. `client` goes first so the shared column types are restored to Postgres'
    after the SQLite engine patched them."""
    from app.models.producto import ProductoERP

    engine = request.getfixturevalue("mlpub_pg")
    ProductoERP.__table__.create(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(WORKER_STATE_DDL))
        conn.execute(text(STORES_DDL))
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(MlHttpClient, "get", lambda *args, **kwargs: pytest.fail("the view endpoints must not call ML"))
    status_block.REPORT.reset()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    sessions: list[Session] = []

    def _view_db():
        session = factory()
        sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[ml_publications_view.get_view_db] = _view_db
    yield engine
    app.dependency_overrides.pop(ml_publications_view.get_view_db, None)
    status_block.REPORT.reset()


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


def seed_rows(engine, fill) -> None:
    with engine.begin() as conn:
        fill(conn)


def get(client, headers, **params):
    return client.get(URL, headers=headers, params=params)


class TestPermission:
    def test_the_permission_code_is_the_catalog_one(self) -> None:
        assert ml_publications_view.PERMISO_VER == VER

    def test_authentication_is_required(self, client, pg) -> None:
        assert client.get(URL).status_code in (401, 403)

    def test_a_user_without_ml_ops_ver_gets_403(self, client, pg, auth_headers) -> None:
        response = get(client, auth_headers)
        assert response.status_code == 403
        assert VER in response.json()["error"]["message"]

    def test_the_view_router_only_reads(self) -> None:
        verbs = {m for route in ml_publications_view.router.routes for m in getattr(route, "methods", set())}
        assert verbs == {"GET"}

    def test_a_pm_whose_scope_excludes_a_product_still_sees_its_publications(
        self, client, pg, db, active_user, rol_ventas, auth_headers
    ) -> None:
        grant(db, rol_ventas, VER)
        db.add(MarcaPM(marca="OTRA", categoria="OTRA", usuario_id=active_user.id))
        db.flush()

        def fill(conn) -> None:
            seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", categoria="Redes")
            seed.add_item(conn, "MLA1", title="Router")
            seed.add_link(conn, "MLA1", 70)

        seed_rows(pg, fill)
        response = get(client, auth_headers)
        assert response.status_code == 200
        assert [i["item_id"] for i in response.json()["items"]] == ["MLA1"]


class TestContract:
    def fill(self, conn) -> None:
        seed.add_product(conn, 70, "7790001", "Router AC1200", marca="TP-Link", categoria="Redes")
        conn.execute(text("INSERT INTO ml_tiendas_oficiales (store_id, nombre) VALUES (2645, 'TP-Link')"))
        seed.add_item(
            conn,
            "MLA1",
            title="Router",
            status="active",
            official_store_id=2645,
            price=1000,
            available_quantity=4,
            user_product_id="MLAU1",
            last_trigger_received_at=seed.NOW,
        )
        seed.add_link(conn, "MLA1", 70)
        seed.add_stock(conn, "MLAU1", full=3, own=1)
        seed.add_item(conn, "MLA2", title="Sin vincular", status="paused")

    def test_the_response_shape(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        body = get(client, reader).json()
        assert set(body) == {"items", "total", "limit", "offset", "can_see_margin", "events_enabled", "data_state"}
        assert (body["total"], body["limit"], body["offset"]) == (2, 50, 0)
        assert body["can_see_margin"] is False and body["events_enabled"] is False
        first, second = body["items"]
        assert first["item_id"] == "MLA1" and second["item_id"] == "MLA2"  # activity desc, no activity last
        assert first["price"] == {
            "amount": 1000.0,
            "source": "item_price",
            "regular_amount": None,
            "promotion_type": None,
            "campaign": None,
            "pricelist_id": None,
        }
        assert first["stock"]["full"] == 3 and first["stock"]["own"] == 1 and first["stock"]["available"] == 4
        assert first["link"] == {
            "state": "auto",
            "producto_item_id": 70,
            "codigo": "7790001",
            "descripcion": "Router AC1200",
            "marca": "TP-Link",
        }
        assert first["store_label"] == "TP-Link" and first["gone"] is False
        assert second["link"]["state"] == "no_evaluado" and second["stock"]["full"] is None
        assert "markup" not in first and "facets" not in body

    def test_filters_sort_and_paging_reach_the_query(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        body = get(client, reader, q="router", estado="active", orden="titulo", limit=1, offset=0).json()
        assert [i["item_id"] for i in body["items"]] == ["MLA1"]
        assert (body["total"], body["limit"]) == (1, 1)
        assert get(client, reader, estado="paused", limit=10).json()["total"] == 1

    def test_the_margin_permission_is_reported_not_applied(self, client, pg, db, rol_admin, reader) -> None:
        assert get(client, reader).json()["can_see_margin"] is False
        grant(db, rol_admin, GANANCIA)
        assert get(client, reader).json()["can_see_margin"] is True

    def test_facets_are_computed_only_on_request_and_carry_the_total(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        assert "facets" not in get(client, reader).json()
        facets = get(client, reader, facets="true", estado="paused").json()["facets"]
        assert facets["status"] == {"active": 1, "paused": 1}
        assert facets["total"] == 1  # the filtered list total, as the screen's counter

    def test_the_timing_is_reported_in_a_header_and_in_the_log(self, client, pg, reader, caplog) -> None:
        seed_rows(pg, self.fill)
        with caplog.at_level(logging.INFO, logger="pubml.view"):
            response = get(client, reader)
        timing = response.headers["server-timing"]
        assert all(stage in timing for stage in ("list;dur=", "status;dur="))
        (line,) = [r.getMessage() for r in caplog.records if r.name == "pubml.view"]
        assert line.startswith("pubml.view endpoint=items total_ms=") and "rows=2" in line and "total=2" in line


class TestInvalidParams:
    @pytest.mark.parametrize(
        "params, field",
        [
            ({"estado": "active,bogus"}, "estado"),
            ({"tiendas": "x"}, "tiendas"),
            ({"orden": "markup"}, "orden"),
            ({"dir": "up"}, "dir"),
            ({"q": "x" * 101}, "q"),
            ({"evento_desde": "7d"}, "evento_desde"),
        ],
    )
    def test_a_value_outside_the_vocabulary_is_422_naming_the_param(self, client, pg, reader, params, field) -> None:
        response = get(client, reader, **params)
        assert response.status_code == 422
        assert response.json()["error"]["field"] == field

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}])
    def test_the_page_size_is_bounded_by_the_framework(self, client, pg, reader, params) -> None:
        assert get(client, reader, **params).status_code == 422

    def test_the_event_filter_with_the_events_flag_off_is_422(self, client, pg, reader) -> None:
        response = get(client, reader, evento="price_changed")
        assert response.status_code == 422 and response.json()["error"]["field"] == "evento"


class TestEvents:
    def fill(self, conn) -> None:
        for n in range(1, 4):
            seed.add_item(conn, f"MLA{n}", last_trigger_received_at=seed.hours_ago(n))
        seed.add_event(conn, "MLA1", "price_changed", seed.hours_ago(5))
        seed.add_event(conn, "MLA1", "status_paused", seed.hours_ago(1))
        seed.add_event(conn, "MLA2", "stock_depleted", seed.hours_ago(2))

    def test_the_last_event_is_absent_while_the_flag_is_off(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        body = get(client, reader).json()
        assert body["events_enabled"] is False
        assert all("last_event" not in item for item in body["items"])

    def test_the_last_event_is_the_newest_per_item_while_the_flag_is_on(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        settings_store.set_setting("events.enabled", True, "test")
        body = get(client, reader).json()
        assert body["events_enabled"] is True
        by_id = {item["item_id"]: item["last_event"] for item in body["items"]}
        assert by_id["MLA1"]["event_type"] == "status_paused"
        assert by_id["MLA2"]["event_type"] == "stock_depleted"
        assert by_id["MLA3"] is None  # no event: null, not missing
        assert get(client, reader, evento="stock_depleted").json()["total"] == 1


class TestStatementCount:
    def fill(self, conn) -> None:
        for n in range(120):
            seed.add_item(conn, f"MLA{n:04d}", last_trigger_received_at=seed.hours_ago(n), official_store_id=n % 3)
            seed.add_event(conn, f"MLA{n:04d}", "price_changed", seed.hours_ago(n))
        for variation in range(3):
            seed.add_variation(conn, "MLA0001", variation + 1)

    def statements(self, client, pg, reader, **params) -> list[str]:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(pg, "before_cursor_execute", record)
        try:
            assert get(client, reader, **params).status_code == 200
        finally:
            event.remove(pg, "before_cursor_execute", record)
        return recorded

    def test_the_count_does_not_depend_on_the_page_size(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        settings_store.set_setting("events.enabled", True, "test")
        get(client, reader)  # warm: the status block is built once and then served from its cache
        small = self.statements(client, pg, reader, limit=10)
        large = self.statements(client, pg, reader, limit=100)
        assert len(small) == len(large) and len(small) <= 9
        assert sum("ml_item_events" in s for s in large) == 1  # the last events of the page: one statement

    def test_the_event_statement_exists_only_while_the_flag_is_on(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        get(client, reader)
        off = self.statements(client, pg, reader, limit=100)
        assert sum("ml_item_events" in s for s in off) == 0

    def test_facets_add_a_fixed_number_of_statements(self, client, pg, reader) -> None:
        seed_rows(pg, self.fill)
        get(client, reader)
        without = self.statements(client, pg, reader, limit=10)
        with_facets = self.statements(client, pg, reader, limit=10, facets="true")
        assert len(with_facets) - len(without) == len(listing.FACET_AXES)


class TestSlowQuery:
    def test_a_statement_timeout_is_a_controlled_503_and_the_connection_goes_back(
        self, client, pg, reader, monkeypatch
    ) -> None:
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA1"))
        real = listing.build_base_select

        def slow(f, *columns, **kwargs):
            from sqlalchemy import func

            return real(f, *columns, func.pg_sleep(1), **kwargs)

        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "50ms")
        monkeypatch.setattr(listing, "build_base_select", slow)
        response = get(client, reader)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "consulta_lenta"
        assert pg.pool.checkedout() == 0
        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "8s")
        monkeypatch.setattr(listing, "build_base_select", real)  # the next request is served normally
        status_block.REPORT.reset()
        assert get(client, reader).status_code == 200

    def test_an_error_that_is_not_a_timeout_is_not_swallowed(self, client, pg, reader, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("not a timeout")

        monkeypatch.setattr(listing, "list_items", boom)
        assert get(client, reader).status_code == 500


class TestHonestState:
    def test_events_and_prices_disabled_are_named_in_the_response(self, client, pg, reader) -> None:
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA1"))
        state = get(client, reader).json()["data_state"]
        assert state["available"] is True and state["degraded"] is True
        flags = {d["flag"] for d in state["degradations"] if d["code"] == "flag_disabled"}
        resources = {d["resource"] for d in state["degradations"] if d["code"] == "resource_not_collected"}
        assert "events" in flags
        assert resources == {"sale_price", "stock"}

    def test_every_flag_on_and_fresh_data_is_no_degradation(self, client, pg, reader) -> None:
        for flag in ("refresh", "intake", "events", "links"):
            settings_store.set_setting(f"{flag}.enabled", True, "test")
        settings_store.set_setting("bundle_resources", ["core", "sale_price", "stock"], "test")
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA1", last_checked_at=seed.NOW))
        with pg.begin() as conn:
            conn.execute(text("UPDATE ml_items SET last_checked_at = now()"))
        state = get(client, reader).json()["data_state"]
        assert state["degradations"] == [] and state["degraded"] is False
        assert state["store_empty"] is False

    def test_an_empty_store_answers_an_empty_page_and_says_so(self, client, pg, reader) -> None:
        body = get(client, reader).json()
        assert body["items"] == [] and body["total"] == 0
        assert body["data_state"]["store_empty"] is True

    def test_a_report_that_cannot_be_built_does_not_fail_the_list(self, client, pg, reader, monkeypatch) -> None:
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA1"))
        monkeypatch.setattr(status_block.status, "build_status", lambda db: (_ for _ in ()).throw(RuntimeError("x")))
        body = get(client, reader).json()
        assert [i["item_id"] for i in body["items"]] == ["MLA1"]
        assert body["data_state"]["available"] is False and body["data_state"]["reason"] == "status_unavailable"
