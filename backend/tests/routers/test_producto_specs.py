"""Product specs ABM (abm-specs-productos T1: S3, S4, S6, S8): pre-load from ML, the ERP name and the combo, keep each
field's origin, never overwrite a manual field, reject garbage, and check permissions.

Same harness as the productos propios router tests: permissions in the SQLite test database, the spec tables and their
sources in a throwaway Postgres schema (the ML store built from the real migrations).
"""

# ruff: noqa: F811 -- the fixtures are imported from the conftest modules and used by name

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.combo_componente import ComboComponente
from app.models.producto import ProductoERP
from app.models.producto_spec import ProductoSpec, ProductoSpecValor
from app.models.tb_item import TBItem
from app.routers import producto_specs
from app.services.producto_specs import store
from app.services.producto_specs.campos import VALORES_INICIALES
from app.workers.context import WorkerContext
from app.workers.handlers.producto_specs_preload import preload
from tests.routers.test_ml_publications_links import grant
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

VER = "productos.ver"
EDITAR = "productos.editar_specs"
BASE = "/api/producto-specs"

NB_NAME = 'NB LENOVO V15 G5 IRL I7-13620H 16GB D5 1T SSD 15.6" FHD FDOS (7425)'


@pytest.fixture()
def pg(client, request):
    engine = request.getfixturevalue("mlpub_pg")
    for model in (ProductoERP, TBItem, ComboComponente, ProductoSpec, ProductoSpecValor):
        model.__table__.create(bind=engine, checkfirst=True)
    with engine.begin() as conn:
        for campo, valores in VALORES_INICIALES.items():
            for valor in valores:
                conn.execute(
                    text("INSERT INTO producto_spec_valores (campo, clave, valor) VALUES (:c, :k, :v)"),
                    {"c": campo, "k": valor.casefold(), "v": valor},
                )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _store_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[producto_specs.get_producto_specs_db] = _store_db
    yield engine
    app.dependency_overrides.pop(producto_specs.get_producto_specs_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def editor(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR)
    return admin_auth_headers


def product(conn, item_id: int, name: str, *, cat_id: int = 46, subcat_id: int = 1, marca: str = "LENOVO", stock=5):
    seed.add_product(conn, item_id, f"C{item_id}", name, marca=marca, stock=stock)
    conn.execute(
        text(
            "INSERT INTO tb_item (comp_id, item_id, item_code, item_desc, cat_id, subcat_id) "
            "VALUES (1, :i, :c, :d, :cat, :sub)"
        ),
        {"i": item_id, "c": f"C{item_id}", "d": name, "cat": cat_id, "sub": subcat_id},
    )


def publication(conn, mla: str, producto: int, attributes: list[dict], *, updated: datetime | None = None):
    seed.add_item(
        conn,
        mla,
        raw=json.dumps({"id": mla, "attributes": attributes}),
        ml_last_updated=updated or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    seed.add_link(conn, mla, producto)


def a(attr_id, value):
    return {"id": attr_id, "value_name": value}


def component(conn, combo: int, comp: int, cat_id: int, name: str, marca: str, cantidad=1):
    product(conn, comp, name, cat_id=cat_id, marca=marca)
    conn.execute(
        text("INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :i, :q)"),
        {"c": combo, "i": comp, "q": cantidad},
    )


def preload_all(engine) -> dict:
    with Session(engine) as session:
        counts = store.precargar(session)
        session.commit()
    return counts


def fields(body: dict) -> dict:
    return {c["campo"]: (c["valor"], c["origen"]) for c in body["campos"]}


def read(client, headers, item_id: int) -> dict:
    response = client.get(f"{BASE}/{item_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestPreload:
    def test_ml_first_then_the_erp_name_for_what_ml_left_empty_each_with_its_origin(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME)
            publication(
                conn,
                "MLA1",
                10,
                [
                    a("RAM_MEMORY_MODULE_TOTAL_CAPACITY", "24 GB"),
                    a("DISPLAY_SIZE", "2491679"),
                    a("DISPLAY_TYPE", "IPS LCD"),
                ],
            )
        preload_all(pg)

        body = fields(read(client, reader, 10))

        assert body["ram_gb"] == (24, "ml")  # ML wins over the name's 16GB
        assert body["pantalla_panel"] == ("IPS", "ml")
        assert body["pantalla_pulgadas"] == (15.6, "erp_name")  # the ML garbage id is rejected, the name fills it
        assert body["cpu_modelo"] == ("13620H", "erp_name")
        assert body["so_nombre"] == ("FreeDOS", "erp_name")
        assert body["gpu_tipo"] == (None, None)  # nothing names a GPU: left empty, not guessed

    def test_the_most_complete_publication_wins(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 10, "NB SIN DATOS")
            publication(conn, "MLA1", 10, [a("RAM_MEMORY_MODULE_TOTAL_CAPACITY", "8 GB")])
            publication(
                conn, "MLA2", 10, [a("RAM_MEMORY_MODULE_TOTAL_CAPACITY", "16 GB"), a("RAM_MEMORY_TYPE", "DDR5")]
            )
        preload_all(pg)

        body = read(client, reader, 10)

        assert fields(body)["ram_gb"] == (16, "ml")
        assert body["fuente_mla"] == "MLA2"

    def test_a_pc_takes_its_parts_from_the_combo(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 20, "PC ARMADA GAMER RYZEN 7 5700G A520 32GB 480GB", cat_id=47, marca="GAUSS")
            component(conn, 20, 201, 50, "MOTHER BIOSTAR AM4 B450M HP BOX M-ATX", "BIOSTAR")
            component(conn, 20, 202, 55, "FUENTE LNZ SX600-TS 600W", "LNZ")
        preload_all(pg)

        body = fields(read(client, reader, 20))

        assert body["mother_marca"] == ("BIOSTAR", "combo")
        assert body["fuente_watts"] == (600, "combo")
        assert body["ram_gb"] == (32, "erp_name")
        assert "pantalla_pulgadas" not in body  # a PC has no screen fields

    def test_categorical_values_are_stored_as_the_list_spells_them(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 10, "NB X")
            publication(conn, "MLA1", 10, [a("DISK_TYPE", "híbrido"), a("TOTAL_DISK_CAPACITY", "1 TB")])
        preload_all(pg)

        assert fields(read(client, reader, 10))["disco_tipo"] == ("Híbrido", "ml")

    def test_it_is_idempotent(self, pg):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME)
            product(conn, 20, "PC ARMADA ATHLON 3000G AM4 8GB 128GB SSD KIT W11H", cat_id=47)
            publication(conn, "MLA1", 10, [a("RAM_MEMORY_TYPE", "DDR5")])

        first = preload_all(pg)
        with pg.connect() as conn:
            before = conn.execute(text("SELECT * FROM producto_specs ORDER BY item_id")).all()
        second = preload_all(pg)
        with pg.connect() as conn:
            after = conn.execute(text("SELECT * FROM producto_specs ORDER BY item_id")).all()

        assert (first["creados"], second["creados"], second["actualizados"], second["sin_cambios"]) == (2, 0, 0, 2)
        assert before == after

    def test_notebook_accessories_are_not_notebooks(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 30, "FUNDA NB 15.6", subcat_id=3908)
        assert preload_all(pg)["productos"] == 0
        assert client.get(f"{BASE}/30", headers=reader).status_code == 404

    def test_the_worker_handler_runs_the_backfill(self, pg):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME)
        ctx = WorkerContext(deadline=datetime(2100, 1, 1, tzinfo=timezone.utc), worker_name="w")

        result = preload.run(ctx)

        assert result.success, result.error
        assert result.detail["creados"] == 1
        assert (preload.name, preload.run_at_local is not None, preload.interval) == (
            "producto_specs.preload",
            True,
            None,
        )


class TestManual:
    def test_a_manual_value_is_never_overwritten_by_a_re_preload(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME)

        response = client.put(f"{BASE}/10", headers=editor, json={"valores": {"ram_gb": 32, "so_nombre": None}})
        assert response.status_code == 200, response.text
        assert fields(response.json())["ram_gb"] == (32, "manual")
        assert fields(response.json())["so_nombre"] == (None, "manual")  # emptied by hand stays empty
        assert fields(response.json())["cpu_modelo"] == (
            "13620H",
            "erp_name",
        )  # the first edit starts from the pre-load

        response = client.post(f"{BASE}/10/precargar", headers=editor)
        assert response.status_code == 200, response.text
        preload_all(pg)

        body = fields(read(client, editor, 10))
        assert body["ram_gb"] == (32, "manual")
        assert body["so_nombre"] == (None, "manual")

    def test_an_out_of_range_number_is_rejected(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME)

        response = client.put(f"{BASE}/10", headers=editor, json={"valores": {"pantalla_hz": 7873264}})

        assert response.status_code == 422
        assert "pantalla_hz" in response.text

    def test_a_categorical_value_must_be_in_the_list_and_adding_one_reuses_its_spelling(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn, 20, "PC ARMADA", cat_id=47)

        assert (
            client.put(f"{BASE}/20", headers=editor, json={"valores": {"gabinete_marca": "Sentey"}}).status_code == 422
        )

        added = client.post(f"{BASE}/valores/gabinete_marca", headers=editor, json={"valor": "  Sentey "})
        assert added.status_code == 201, added.text
        again = client.post(f"{BASE}/valores/gabinete_marca", headers=editor, json={"valor": "SENTEY"})
        assert again.json()["valor"] == "Sentey"  # "16 GB" once, not "16GB"/"16 gb"
        assert client.get(f"{BASE}/valores/gabinete_marca", headers=editor).json() == ["Sentey"]

        response = client.put(f"{BASE}/20", headers=editor, json={"valores": {"gabinete_marca": "sentey"}})
        assert response.status_code == 200, response.text
        assert fields(response.json())["gabinete_marca"] == ("Sentey", "manual")

    def test_a_field_that_does_not_apply_is_rejected(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn, 20, "PC ARMADA", cat_id=47)
        response = client.put(f"{BASE}/20", headers=editor, json={"valores": {"pantalla_hz": 144}})
        assert response.status_code == 422


class TestPermissions:
    def test_editing_needs_the_edit_permission(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME)
        assert client.put(f"{BASE}/10", headers=reader, json={"valores": {"ram_gb": 8}}).status_code == 403
        assert client.post(f"{BASE}/10/precargar", headers=reader).status_code == 403
        assert client.post(f"{BASE}/valores/gpu_marca", headers=reader, json={"valor": "X"}).status_code == 403
        assert read(client, reader, 10)["can_edit"] is False

    def test_reading_needs_productos_ver(self, client, pg, admin_auth_headers):
        assert client.get(BASE, headers=admin_auth_headers).status_code == 403


class TestList:
    def test_filters_by_type_brand_incomplete_and_text(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME, stock=9)
            product(conn, 11, 'NB HP 255 G10 R3 7335U 8GB D5 512GB 15" W11H', marca="HP", stock=1)
            product(conn, 20, "PC ARMADA GAMER", cat_id=47, marca="GAUSS", stock=0)
        preload_all(pg)

        def ids(**params):
            response = client.get(BASE, headers=reader, params=params)
            assert response.status_code == 200, response.text
            return [row["item_id"] for row in response.json()["items"]]

        assert ids() == [10, 11, 20]  # by stock
        assert ids(tipo="pc") == [20]
        assert ids(marca="hp") == [11]
        assert ids(q="7335U") == [11]
        assert ids(incompletos="true") == [10, 11, 20]
        row = client.get(BASE, headers=reader, params={"tipo": "notebook"}).json()["items"][0]
        assert row["completos"] == 10 and row["total"] == 17

    def test_numeric_values_list_the_stored_numbers(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn, 10, NB_NAME)
            product(conn, 11, "NB HP 8GB D5 512GB", marca="HP")
        preload_all(pg)
        assert client.get(f"{BASE}/valores/ram_gb", headers=reader).json() == [8, 16]
        assert client.get(f"{BASE}/valores/nope", headers=reader).status_code == 404
