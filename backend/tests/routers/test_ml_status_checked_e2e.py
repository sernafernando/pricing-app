"""Pause/activate the checked rows end to end on Postgres (seleccion-por-publicacion S2): the checked set resolves
through `POST /status-item-ids/checked` and goes to the real `status-bulk` write, with only the HTTP call to ML faked.
Only the checked MLAs (or every live MLA of a checked product) reach ML; malformed bodies never write and never 500."""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy import event, text

from app.core.config import settings
from app.services import ml_item_status_write_service as write_service
from app.services.ml_publication_status_service import _classify
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

CHECKED = "/api/ml-publications/view/status-item-ids/checked"
BULK = "/api/ml-publications/items/status-bulk"
PAUSAR = "ml_publicaciones.pausar"
INT4_MAX = 2**31 - 1


def fill(conn) -> None:
    """Product 77 has three active MLAs, a paused one, a deleted one, a gone one, a ghost and a variation link;
    product 78 has one; MLA8 has no status at all."""
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_product(conn, 78, "R78", "Otro", marca="TP-Link", stock=4)
    for mla in ("MLA1", "MLA2", "MLA3"):
        seed.add_item(conn, mla, status="active", title=mla)
        seed.add_link(conn, mla, 77)
    seed.add_item(conn, "MLA4", status="paused", title="paused sibling")
    seed.add_link(conn, "MLA4", 77)
    seed.add_item(conn, "MLA5", status="active", sub_status=["deleted"], title="deleted sibling")
    seed.add_link(conn, "MLA5", 77)
    seed.add_item(conn, "MLA6", status="active", title="gone sibling", gone_at=seed.NOW)
    seed.add_link(conn, "MLA6", 77)
    seed.add_item(conn, "MLA7", status="active", title="ghost sibling", never_existed=True)
    seed.add_link(conn, "MLA7", 77)
    seed.add_item(conn, "MLA8", status=None, title="no status")
    seed.add_item(conn, "MLA9", status="active", title="other product")
    seed.add_link(conn, "MLA9", 78)
    seed.add_item(conn, "MLA10", status="active", title="variation link")
    seed.add_variation(conn, "MLA10", 111)
    seed.add_link(conn, "MLA10", 77, variation_id=111)


@pytest.fixture()
def rows(pg) -> None:
    seed_rows(pg, fill)


@pytest.fixture()
def hdr(db, rol_admin, admin_auth_headers) -> dict:
    grant(db, rol_admin, VER, PAUSAR)
    return admin_auth_headers


@pytest.fixture()
def ml(pg, monkeypatch) -> list[tuple[str, str]]:
    """The MLAs the real write sends to ML, in order. The status read goes to the seeded `ml_items`; the write log
    and the refresh queue are out of this test's scope."""
    calls: list[tuple[str, str]] = []

    class FakeClient:
        async def put_item_status(self, item_id: str, status: str) -> dict:
            calls.append((item_id, status))
            return {"ok": True, "status_code": 200, "ambiguous": False, "body": {"id": item_id}}

    def read(mla: str):
        with pg.connect() as conn:
            row = conn.execute(
                text("select status, sub_status, gone_at, never_existed from ml_items where item_id = :m"), {"m": mla}
            ).first()
        return None if row is None else _classify(row.status, row.sub_status, row.gone_at, row.never_existed)

    monkeypatch.setattr(settings, "ML_ITEM_STATUS_WRITE_ENABLED", True)
    monkeypatch.setattr(write_service, "MLWebhookClient", FakeClient)
    monkeypatch.setattr(write_service, "_read_status", read)
    monkeypatch.setattr(write_service, "_record_write_log", lambda *args: None)
    monkeypatch.setattr(write_service, "_enqueue_refresh", lambda *args: None)
    return calls


def resolve_and_write(client, hdr: dict, target: str, **payload) -> dict:
    """What the page does: resolve the checked set, then write what came back (nothing when it is empty)."""
    resolved = client.post(CHECKED, headers=hdr, json={"target": target, **payload})
    assert resolved.status_code == 200, resolved.text
    item_ids = resolved.json()["item_ids"]
    if item_ids:
        written = client.post(BULK, headers=hdr, json={"status": target, "item_ids": item_ids})
        assert written.status_code == 200, written.text
    return resolved.json()


@pytest.mark.postgres
class TestCheckedRowsReachMl:
    def test_one_checked_publication_of_many_is_the_only_write(self, client, rows, hdr, ml):
        got = resolve_and_write(client, hdr, "paused", item_ids=["MLA2"])
        assert got == {"item_ids": ["MLA2"], "count": 1, "no_aplican": 0}
        assert ml == [("MLA2", "paused")]

    def test_activating_one_paused_publication(self, client, rows, hdr, ml):
        resolve_and_write(client, hdr, "active", item_ids=["MLA4"])
        assert ml == [("MLA4", "active")]

    def test_two_checked_publications(self, client, rows, hdr, ml):
        resolve_and_write(client, hdr, "paused", item_ids=["MLA3", "MLA1"])
        assert sorted(ml) == [("MLA1", "paused"), ("MLA3", "paused")]

    def test_a_checked_product_sends_its_live_publications_only(self, client, rows, hdr, ml):
        got = resolve_and_write(client, hdr, "paused", producto_ids=[77])
        assert {"MLA1", "MLA2", "MLA3", "MLA10"} <= set(got["item_ids"])
        assert not {"MLA5", "MLA6", "MLA9"} & set(got["item_ids"])
        assert "MLA7" not in got["item_ids"]
        assert {mla for mla, _ in ml} == set(got["item_ids"])

    def test_a_checked_ghost_counts_as_not_applying(self, client, rows, hdr, ml):
        """ML says it never existed: as on the filter path, it is never named, only counted."""
        got = resolve_and_write(client, hdr, "paused", item_ids=["MLA7"])
        assert got == {"item_ids": [], "count": 0, "no_aplican": 1}
        assert ml == []

    def test_a_checked_publication_without_status_counts_as_not_applying(self, client, rows, hdr, ml):
        got = resolve_and_write(client, hdr, "paused", item_ids=["MLA8"])
        assert got == {"item_ids": [], "count": 0, "no_aplican": 1}
        assert ml == []

    def test_deleted_gone_and_unknown_are_counted_never_sent(self, client, rows, hdr, ml):
        got = resolve_and_write(client, hdr, "paused", item_ids=["MLA5", "MLA6", "MLA999"])
        assert got == {"item_ids": [], "count": 0, "no_aplican": 3}
        assert ml == []

    def test_duplicates_count_once(self, client, rows, hdr, ml):
        got = resolve_and_write(client, hdr, "paused", item_ids=["MLA1", "MLA1"], producto_ids=[78, 78])
        assert got == {"item_ids": ["MLA1", "MLA9"], "count": 2, "no_aplican": 0}

    def test_without_a_token_it_is_refused(self, client, rows):
        assert client.post(CHECKED, json={"target": "paused", "item_ids": ["MLA1"]}).status_code in (401, 403)

    def test_without_the_view_permission_it_answers_as_the_get(self, client, rows, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, PAUSAR)
        posted = client.post(CHECKED, headers=admin_auth_headers, json={"target": "paused", "item_ids": ["MLA1"]})
        got = client.get(
            "/api/ml-publications/view/status-item-ids", headers=admin_auth_headers, params={"target": "paused"}
        )
        assert posted.status_code == got.status_code

    def test_it_writes_nothing_at_all(self, client, rows, hdr, pg):
        def snapshot():
            with pg.connect() as conn:
                return conn.execute(
                    text("select md5(string_agg(t::text, '|' order by item_id)) from ml_items t")
                ).scalar()

        before = snapshot()
        statements: list[str] = []

        def record(conn, cursor, statement, *args) -> None:
            statements.append(statement)

        event.listen(pg, "before_cursor_execute", record)
        try:
            resolved = client.post(
                CHECKED, headers=hdr, json={"target": "paused", "producto_ids": [77], "item_ids": ["MLA9"]}
            )
        finally:
            event.remove(pg, "before_cursor_execute", record)
        assert resolved.status_code == 200
        assert snapshot() == before
        verbs = {statement.lstrip().split(None, 1)[0].upper() for statement in statements}
        assert verbs <= {"SELECT", "SET", "SAVEPOINT", "RELEASE", "ROLLBACK", "BEGIN", "WITH"}


@pytest.mark.postgres
class TestMalformedBodies:
    @pytest.mark.parametrize(
        "raw,content_type",
        [
            (b"", "application/json"),
            (b"{", "application/json"),
            (b"null", "application/json"),
            (b"[]", "application/json"),
            (b'"x"', "application/json"),
            (b"target=paused", "application/x-www-form-urlencoded"),
        ],
    )
    def test_a_body_that_is_not_the_object_is_a_422(self, client, rows, hdr, raw, content_type, ml):
        resolved = client.post(CHECKED, headers={**hdr, "content-type": content_type}, content=raw)
        assert resolved.status_code == 422
        assert ml == []

    @pytest.mark.parametrize("producto_id", [INT4_MAX + 1, 2**63, 10**40, 0, -1, -(2**31) - 1, -(10**40)])
    def test_a_product_id_outside_the_positive_int4_range_is_a_422(self, client, rows, hdr, producto_id, ml):
        resolved = client.post(CHECKED, headers=hdr, json={"target": "paused", "producto_ids": [producto_id]})
        assert resolved.status_code == 422, resolved.text
        assert ml == []

    def test_the_largest_int4_product_id_resolves(self, client, rows, hdr):
        resolved = client.post(CHECKED, headers=hdr, json={"target": "paused", "producto_ids": [INT4_MAX]})
        assert resolved.json() == {"item_ids": [], "count": 0, "no_aplican": 0}

    @pytest.mark.parametrize(
        "payload",
        [
            {"target": "paused", "item_ids": None},
            {"target": "paused", "item_ids": "MLA1"},
            {"target": "paused", "item_ids": [1]},
            {"target": "paused", "item_ids": [None]},
            {"target": "paused", "item_ids": ["mla1"]},
            {"target": "paused", "item_ids": ["MLA1\n"]},
            {"target": "paused", "item_ids": ["MLA1' OR 1=1--"]},
            {"target": "paused", "item_ids": ["MLA" + "9" * 5000]},
            {"target": "paused", "producto_ids": [None]},
            {"target": "paused", "producto_ids": ["x"]},
            {"target": "paused", "producto_ids": ["77"]},
            {"target": "paused", "producto_ids": [True]},
            {"target": "paused", "producto_ids": [77.0]},
            {"target": "paused", "producto_ids": [77.5]},
            {"target": "paused", "producto_ids": [77], "item_ids": ["x"]},
            {"target": None, "item_ids": ["MLA1"]},
            {"item_ids": ["MLA1"]},
            {"target": "paused", "item_ids": ["MLA1"], "estado": "active"},
        ],
    )
    def test_an_odd_body_never_500s_and_never_writes(self, client, rows, hdr, payload, ml):
        resolved = client.post(CHECKED, headers=hdr, json=payload)
        assert resolved.status_code < 500, resolved.text
        assert ml == []


@pytest.mark.postgres
class TestCap:
    def test_500_are_named_and_501_refused_never_truncated(self, client, pg, hdr):
        def fill_many(conn) -> None:
            for i in range(501):
                seed.add_item(conn, f"MLA{1000 + i}", status="active", title="x")

        seed_rows(pg, fill_many)
        item_ids = [f"MLA{1000 + i}" for i in range(501)]
        over = client.post(CHECKED, headers=hdr, json={"target": "paused", "item_ids": item_ids})
        assert over.status_code == 422
        error = over.json()["error"]
        assert (error["code"], error["count"], error["max"]) == ("demasiadas_publicaciones", 501, 500)
        at_cap = client.post(CHECKED, headers=hdr, json={"target": "paused", "item_ids": item_ids[:500]})
        assert at_cap.status_code == 200 and at_cap.json()["count"] == 500
