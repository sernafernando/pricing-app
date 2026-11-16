"""abm-productos T4 (delivery 1, S9 + S13): the product master over `productos_propios`.

Every overridable field is NULL = follow GBP; a stored value is an override, shown next to the GBP value; a value
equal to GBP is not stored; nothing is ever written to the ERP tables. The four texts follow a chosen source live
(ML winning publication, Tienda Nube name, GBP, the product name) or keep an own text fixed. Units per box are the
Gestión Full row, written through its audited service and its permission.

Same harness as the productos propios router tests: permissions in the SQLite test database, the store in a
throwaway Postgres schema (the ML store built from the real migrations).
"""

# ruff: noqa: F811 -- the fixtures are imported from the conftest modules and used by name

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.auditoria import Auditoria
from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.models.producto import ProductoERP
from app.models.producto_propio import ProductoPropio
from app.models.producto_spec import ProductoSpec
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_item import TBItem
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_supplier import TBSupplier
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tienda_nube_producto_texto import TiendaNubeProductoTexto
from app.routers import productos_propios
from tests.routers.test_ml_publications_links import grant
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

VER = "productos.ver"
EDITAR = "productos.editar_maestro"
DEPOSITOS = "gestion_full.depositos"
BASE = "/api/productos-propios"

UB500 = "BLUETOOTH TPLINK NANO USB UB500 BT 5.0"
GBP_TITULO = "Adaptador Bluetooth Usb Nano Tp-link Ub400 Para Notebook Pc"


@pytest.fixture()
def pg(client, request, admin_user):
    engine = request.getfixturevalue("mlpub_pg")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE usuarios (id integer PRIMARY KEY, nombre varchar(100))"))
        conn.execute(text("INSERT INTO usuarios (id, nombre) VALUES (:i, 'admin')"), {"i": admin_user.id})
        conn.execute(text(seed.PRICING_DDL))
    for model in (
        ProductoERP,
        ProductoPropio,
        TBItem,
        TBBrand,
        TBCategory,
        TBSubCategory,
        TBSupplier,
        TiendaNubeProducto,
        TiendaNubeProductoTexto,
        ProductoSpec,
        GestionFullUnidadesCaja,
        Auditoria,
    ):
        model.__table__.create(bind=engine, checkfirst=True)
    with engine.begin() as conn:
        for brand_id, name in ((10, "TP-LINK"), (11, "ASUS")):
            conn.execute(
                text("INSERT INTO tb_brand (comp_id, brand_id, brand_desc) VALUES (1, :b, :n)"),
                {"b": brand_id, "n": name},
            )
        for cat_id, name in ((5, "CONECTIVIDAD"), (46, "NOTEBOOK")):
            conn.execute(
                text("INSERT INTO tb_category (comp_id, cat_id, cat_desc) VALUES (1, :c, :n)"), {"c": cat_id, "n": name}
            )
        for cat_id, subcat_id, name in ((5, 50, "ANTENAS WIFI"), (5, 51, "ROUTERS"), (46, 460, "OFICINA")):
            conn.execute(
                text("INSERT INTO tb_subcategory (comp_id, cat_id, subcat_id, subcat_desc) VALUES (1, :c, :s, :n)"),
                {"c": cat_id, "s": subcat_id, "n": name},
            )
        conn.execute(
            text("INSERT INTO tb_supplier (comp_id, supp_id, supp_name) VALUES (1, 3, 'PC-ARTS ARGENTINA S.A.')")
        )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _store_db():
        session: Session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[productos_propios.get_productos_propios_db] = _store_db
    yield engine
    app.dependency_overrides.pop(productos_propios.get_productos_propios_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def editor(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR)
    return admin_auth_headers


@pytest.fixture()
def deposito(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR, DEPOSITOS)
    return admin_auth_headers


def product(
    conn,
    item_id: int = 455,
    name: str = UB500,
    *,
    cat_id: int = 5,
    subcat_id: int = 50,
    brand_id: int = 10,
    marca: str = "TP-LINK",
    stock: int = 964,
    weight=35,
    raw: str = '{"item_vendorCode": "UB500", "item_guarantee": 180, "supp_id": 3, '
    '"item_ML_title": "' + GBP_TITULO + '", "item_ML_desc": "ADAPTADOR BLUETOOTH UB400"}',
) -> None:
    seed.add_product(conn, item_id, "4897098683446", name, marca=marca, stock=stock)
    seed.add_cost(conn, item_id, 4.6606, moneda_costo="USD", iva=10.5)
    conn.execute(
        text(
            "INSERT INTO tb_item (comp_id, item_id, item_code, item_desc, cat_id, subcat_id, brand_id, raw, "
            "item_weight, item_wide, item_large, item_higth) "
            "VALUES (1, :i, :c, :d, :cat, :sub, :b, CAST(:raw AS jsonb), :w, 14, 9, 3)"
        ),
        {
            "i": item_id,
            "c": f"C{item_id}",
            "d": name,
            "cat": cat_id,
            "sub": subcat_id,
            "b": brand_id,
            "raw": raw,
            "w": weight,
        },
    )


def publication(conn, mla: str, producto: int = 455, *, title: str, desc: str | None = None, **item) -> None:
    seed.add_item(conn, mla, title=title, **item)
    seed.add_link(conn, mla, producto)
    if desc is not None:
        conn.execute(
            text("INSERT INTO ml_item_descriptions (item_id, raw) VALUES (:m, CAST(:r AS jsonb))"),
            {"m": mla, "r": '{"plain_text": "' + desc + '"}'},
        )


def tn(conn, item_id: int = 455, name: str = "Adaptador TP-Link Nano USB Bluetooth 5.0 UB500", **columns) -> None:
    seed.add_tn_variant(conn, item_id, 1, product_name=name, variant_sku="UB500", activo=True, **columns)


def read(client, headers, item_id: int = 455) -> dict:
    response = client.get(f"{BASE}/{item_id}/maestro", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def patch(client, headers, body: dict, item_id: int = 455):
    return client.patch(f"{BASE}/{item_id}/maestro", headers=headers, json=body)


def stored(engine, column: str, item_id: int = 455):
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT {column} FROM productos_propios WHERE item_id = :i"), {"i": item_id}).scalar()


class TestRead:
    def test_without_overrides_every_field_shows_its_gbp_value(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            seed.add_pricing(conn, 455, precio_lista_ml=11999)

        body = read(client, reader)

        campos = body["campos"]
        assert campos["nombre"] == {"valor": UB500, "gbp": UB500, "overrideado": False}
        assert campos["ean"]["valor"] == "4897098683446"
        assert campos["codigo_fabricante"]["valor"] == "UB500"
        assert campos["marca_id"] == {
            "valor": 10,
            "gbp": 10,
            "overrideado": False,
            "nombre": "TP-LINK",
            "gbp_nombre": "TP-LINK",
        }
        assert campos["categoria_id"]["nombre"] == "CONECTIVIDAD"
        assert campos["subcategoria_id"]["nombre"] == "ANTENAS WIFI"
        assert campos["garantia_dias"]["valor"] == 180
        assert [campos[c]["valor"] for c in ("peso_g", "ancho_cm", "largo_cm", "alto_cm")] == [35, 14, 9, 3]
        assert body["unidades_caja"] is None
        lectura = body["lectura"]
        assert lectura["costo"] == 4.6606 and lectura["moneda_costo"] == "USD" and lectura["iva"] == 10.5
        assert lectura["stock"] == 964 and lectura["precio_lista_ml"] == 11999
        assert lectura["proveedor"] == "PC-ARTS ARGENTINA S.A."
        assert lectura["publicaciones_ml"] == 0 and lectura["tn_publicado"] is None
        assert body["can_edit"] is False and body["can_edit_unidades"] is False

    def test_an_unknown_product_is_404(self, client, pg, reader):
        assert client.get(f"{BASE}/999/maestro", headers=reader).status_code == 404

    def test_reading_needs_productos_ver(self, client, pg, admin_auth_headers):
        with pg.begin() as conn:
            product(conn)
        assert client.get(f"{BASE}/455/maestro", headers=admin_auth_headers).status_code == 403


class TestOverrides:
    def test_an_override_is_stored_shown_next_to_gbp_and_never_written_to_the_erp(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)

        response = patch(client, editor, {"nombre": "Adaptador UB500", "ean": "0000000000017", "peso_g": 40})

        assert response.status_code == 200, response.text
        campos = response.json()["campos"]
        assert campos["nombre"] == {"valor": "Adaptador UB500", "gbp": UB500, "overrideado": True}
        assert campos["ean"]["overrideado"] is True and campos["ean"]["gbp"] == "4897098683446"
        assert campos["peso_g"] == {"valor": 40, "gbp": 35, "overrideado": True}
        with pg.connect() as conn:
            erp = conn.execute(text("SELECT descripcion, codigo FROM productos_erp WHERE item_id = 455")).one()
            weight = conn.execute(text("SELECT item_weight FROM tb_item WHERE item_id = 455")).scalar()
        assert tuple(erp) == (UB500, "4897098683446") and weight == 35

    def test_null_goes_back_to_the_gbp_value(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
        patch(client, editor, {"nombre": "Adaptador UB500"})

        campos = patch(client, editor, {"nombre": None}).json()["campos"]

        assert campos["nombre"] == {"valor": UB500, "gbp": UB500, "overrideado": False}
        assert stored(pg, "nombre") is None

    def test_a_value_equal_to_gbp_is_not_stored(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)

        campos = patch(client, editor, {"nombre": f"  {UB500} ", "peso_g": 35.0}).json()["campos"]

        assert campos["nombre"]["overrideado"] is False and campos["peso_g"]["overrideado"] is False
        assert stored(pg, "nombre") is None and stored(pg, "peso_g") is None

    def test_fields_left_out_of_the_patch_are_kept(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
        patch(client, editor, {"nombre": "Adaptador UB500"})

        patch(client, editor, {"garantia_dias": 365})

        assert stored(pg, "nombre") == "Adaptador UB500" and stored(pg, "garantia_dias") == 365

    def test_brand_and_category_are_picked_by_id_and_the_subcategory_must_belong_to_the_category(
        self, client, pg, editor
    ):
        with pg.begin() as conn:
            product(conn)

        moved = patch(client, editor, {"marca_id": 11, "subcategoria_id": 51})
        assert moved.status_code == 200, moved.text
        assert moved.json()["campos"]["marca_id"]["nombre"] == "ASUS"
        assert moved.json()["campos"]["subcategoria_id"]["nombre"] == "ROUTERS"

        wrong = patch(client, editor, {"categoria_id": 46})  # ROUTERS is not a NOTEBOOK subcategory
        assert wrong.status_code == 422
        assert "subcategoría" in wrong.json()["error"]["message"]
        assert stored(pg, "categoria_id") is None  # nothing written
        assert patch(client, editor, {"categoria_id": 46, "subcategoria_id": 460}).status_code == 200
        assert patch(client, editor, {"marca_id": 999}).status_code == 422

    def test_editing_needs_productos_editar_maestro(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
        assert patch(client, reader, {"nombre": "X"}).status_code == 403

    def test_an_unknown_product_is_404(self, client, pg, editor):
        assert patch(client, editor, {"nombre": "X"}, item_id=999).status_code == 404


class TestTextos:
    def test_by_default_each_text_takes_its_first_source_with_a_value(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            publication(
                conn, "MLA1824169308", title="Adaptador Bluetooth 5.0 Usb Nano Tp-link Ub500", desc="Nano UB500"
            )
            tn(conn)

        textos = read(client, reader)["textos"]

        assert textos["titulo_ml"]["fuente"] == "ml" and textos["titulo_ml"]["elegida"] is False
        assert textos["titulo_ml"]["valor"] == "Adaptador Bluetooth 5.0 Usb Nano Tp-link Ub500"
        assert textos["titulo_ml"]["fuentes"]["gbp"] == GBP_TITULO
        assert textos["titulo_web"]["fuente"] == "tn"
        assert textos["titulo_web"]["valor"] == "Adaptador TP-Link Nano USB Bluetooth 5.0 UB500"
        assert textos["descripcion_ml"]["valor"] == "Nano UB500"
        assert textos["descripcion_web"]["fuente"] == "ml"  # the TN product has no stored texts
        assert read(client, reader)["mla_ganadora"] == "MLA1824169308"

    def test_the_tn_description_is_a_source_html_for_web_and_plain_text_for_ml(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            tn(conn)
            conn.execute(
                text(
                    "INSERT INTO tienda_nube_producto_textos (product_id, nombre, descripcion_html, descripcion_texto)"
                    " VALUES (266589695, 'UB500', '<p>Nano <b>UB500</b></p>', 'Nano UB500')"
                )
            )

        textos = read(client, reader)["textos"]

        assert textos["descripcion_web"]["fuentes"]["tn"] == "<p>Nano <b>UB500</b></p>"
        assert (textos["descripcion_web"]["fuente"], textos["descripcion_web"]["valor"]) == (
            "tn",
            "<p>Nano <b>UB500</b></p>",
        )
        assert textos["descripcion_ml"]["fuentes"]["tn"] == "Nano UB500"

    def test_without_tn_texts_the_tn_description_source_is_empty(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)
            tn(conn)

        textos = read(client, reader)["textos"]

        assert textos["descripcion_web"]["fuentes"]["tn"] is None
        assert textos["descripcion_ml"]["fuentes"]["tn"] is None

    def test_without_publication_the_ml_title_falls_back_to_tn_then_gbp(self, client, pg, reader):
        with pg.begin() as conn:
            product(conn)

        titulo = read(client, reader)["textos"]["titulo_ml"]

        assert (titulo["fuente"], titulo["valor"]) == ("gbp", GBP_TITULO)

    def test_the_winning_publication_is_active_first_then_the_most_recently_updated(self, client, pg, reader):
        older = datetime(2026, 10, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 11, 1, tzinfo=timezone.utc)
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", title="Pausada nueva", status="paused", ml_last_updated=newer)
            publication(conn, "MLA2", title="Activa vieja", status="active", ml_last_updated=older)
            publication(conn, "MLA3", title="Activa nueva", status="active", ml_last_updated=newer)
            publication(conn, "MLA4", title="Borrada", status="active", ml_last_updated=newer, gone_at=seed.NOW)

        body = read(client, reader)

        assert body["mla_ganadora"] == "MLA3"
        assert body["lectura"]["publicaciones_ml"] == 4

    def test_a_chosen_source_is_followed_live(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", title="Titulo ML")

        chosen = patch(client, editor, {"textos": {"titulo_ml": {"fuente": "gbp"}}}).json()["textos"]["titulo_ml"]
        assert chosen["fuente"] == "gbp" and chosen["elegida"] is True and chosen["valor"] == GBP_TITULO
        with pg.begin() as conn:  # GBP's next sync changes the title
            conn.execute(text("""UPDATE tb_item SET raw = '{"item_ML_title": "Nuevo GBP"}'"""))

        assert read(client, editor)["textos"]["titulo_ml"]["valor"] == "Nuevo GBP"

    def test_an_own_text_stays_fixed(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", title="Titulo ML")

        own = patch(client, editor, {"textos": {"titulo_web": {"fuente": "propio", "texto": " Mi titulo "}}})
        assert own.status_code == 200, own.text
        with pg.begin() as conn:
            conn.execute(text("UPDATE ml_items SET title = 'Otro'"))

        texto = read(client, editor)["textos"]["titulo_web"]
        assert texto == texto | {"fuente": "propio", "elegida": True, "valor": "Mi titulo"}
        assert stored(pg, "fuente_titulo_web") == "propio"

    def test_an_own_text_cannot_be_blank_and_a_source_must_belong_to_the_text(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)

        blank = patch(client, editor, {"textos": {"descripcion_ml": {"fuente": "propio", "texto": "  "}}})
        foreign = patch(client, editor, {"textos": {"titulo_ml": {"fuente": "nombre"}}})

        assert blank.status_code == 422 and foreign.status_code == 422

    def test_an_own_title_is_capped_like_the_publicaciones_ml_title(self, client, pg, editor):
        """`titulo` is also the Publicaciones ML copy, whose own endpoint caps it at MAX_TITULO_LENGTH."""
        with pg.begin() as conn:
            product(conn)

        for clave, columna in (("titulo_ml", "titulo"), ("titulo_web", "titulo_web")):
            too_long = patch(client, editor, {"textos": {clave: {"fuente": "propio", "texto": "x" * 256}}})
            assert too_long.status_code == 422, too_long.text
            assert stored(pg, columna) is None  # nothing written
        fits = patch(client, editor, {"textos": {"titulo_ml": {"fuente": "propio", "texto": "x" * 255}}})
        assert fits.status_code == 200, fits.text
        assert stored(pg, "titulo") == "x" * 255

    def test_a_null_source_goes_back_to_the_default(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
        patch(client, editor, {"textos": {"titulo_ml": {"fuente": "propio", "texto": "Mio"}}})

        texto = patch(client, editor, {"textos": {"titulo_ml": {"fuente": None}}}).json()["textos"]["titulo_ml"]

        assert texto["fuente"] == "gbp" and texto["elegida"] is False
        assert stored(pg, "fuente_titulo_ml") is None

    def test_copying_from_a_publication_keeps_an_own_text(self, client, pg, editor, db, rol_admin):
        """Copying a publication's data (T7) never replaces an own ML text (L17 b); the others are copied."""
        grant(db, rol_admin, "ml_publicaciones.editar_producto")
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", title="Titulo de la publicacion", desc="Descripcion de la publicacion")
        patch(client, editor, {"textos": {"titulo_ml": {"fuente": "propio", "texto": "Mi titulo"}}})

        copied = client.post(f"{BASE}/455/fuente", headers=editor, json={"mla": "MLA1"})

        assert copied.status_code == 200, copied.text
        assert (stored(pg, "titulo"), stored(pg, "descripcion")) == ("Mi titulo", "Descripcion de la publicacion")
        assert read(client, editor)["textos"]["titulo_ml"]["valor"] == "Mi titulo"

    def test_choosing_a_source_keeps_the_publicaciones_ml_copy(self, client, pg, editor):
        """`titulo` / `descripcion` are also the copy of the chosen publication (T7): a source never clears them."""
        with pg.begin() as conn:
            product(conn)
            publication(conn, "MLA1", title="Titulo ML", desc="Descripcion ML")
            conn.execute(
                text(
                    "INSERT INTO productos_propios (item_id, fuente_mla, titulo, descripcion) "
                    "VALUES (455, 'MLA1', 'Copia', 'Desc')"
                )
            )

        patch(client, editor, {"textos": {"titulo_ml": {"fuente": "gbp"}, "descripcion_ml": {"fuente": None}}})

        assert (stored(pg, "titulo"), stored(pg, "descripcion")) == ("Copia", "Desc")


class TestUnidadesCaja:
    def test_units_per_box_are_written_to_the_gestion_full_row_with_its_audit(self, client, pg, deposito, admin_user):
        with pg.begin() as conn:
            product(conn)

        body = patch(client, deposito, {"unidades_caja": 20, "nombre": "Adaptador UB500"}).json()

        assert body["unidades_caja"] == 20 and body["can_edit_unidades"] is True
        assert stored(pg, "nombre") == "Adaptador UB500"
        with pg.connect() as conn:
            row = conn.execute(text("SELECT unidades, updated_by_id FROM gestion_full_unidades_caja")).one()
            audit = conn.execute(text("SELECT item_id, tipo_accion FROM auditoria")).one()
        assert tuple(row) == (20, admin_user.id)
        assert tuple(audit) == (455, "GESTION_FULL_CAJA")

        assert patch(client, deposito, {"unidades_caja": None}).json()["unidades_caja"] is None
        with pg.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM gestion_full_unidades_caja")).scalar() == 0

    def test_units_per_box_need_the_gestion_full_permission_and_are_at_least_one(
        self, client, pg, editor, db, rol_admin
    ):
        with pg.begin() as conn:
            product(conn)

        denied = patch(client, editor, {"unidades_caja": 20, "nombre": "X"})
        assert denied.status_code == 403
        assert stored(pg, "nombre") is None  # nothing written
        grant(db, rol_admin, DEPOSITOS)
        assert patch(client, editor, {"unidades_caja": 0}).status_code == 422

    def test_an_unchanged_units_per_box_needs_no_gestion_full_permission(self, client, pg, editor):
        """The screen sends the whole form: the value it read back must not be refused (L17 a)."""
        with pg.begin() as conn:
            product(conn)

        assert patch(client, editor, {"unidades_caja": None, "nombre": "Sin caja"}).status_code == 200
        with pg.begin() as conn:
            conn.execute(text("INSERT INTO gestion_full_unidades_caja (producto_item_id, unidades) VALUES (455, 20)"))
        same = patch(client, editor, {"unidades_caja": 20, "nombre": "Con caja"})
        assert same.status_code == 200, same.text
        assert stored(pg, "nombre") == "Con caja"
        assert patch(client, editor, {"unidades_caja": 21}).status_code == 403
        assert patch(client, editor, {"unidades_caja": None}).status_code == 403
        with pg.connect() as conn:
            assert conn.execute(text("SELECT unidades FROM gestion_full_unidades_caja")).scalar() == 20

    def test_an_unchanged_units_per_box_is_not_rewritten_nor_audited(self, client, pg, editor):
        """Resending the stored units per box leaves Gestión Full untouched: same editor, no audit row."""
        with pg.begin() as conn:
            product(conn)
            conn.execute(text("INSERT INTO gestion_full_unidades_caja (producto_item_id, unidades) VALUES (455, 20)"))

        same = patch(client, editor, {"unidades_caja": 20, "nombre": "Con caja"})

        assert same.status_code == 200, same.text
        with pg.connect() as conn:
            row = conn.execute(text("SELECT unidades, updated_by_id FROM gestion_full_unidades_caja")).one()
            audits = conn.execute(
                text("SELECT count(*) FROM auditoria WHERE tipo_accion = 'GESTION_FULL_CAJA'")
            ).scalar()
        assert tuple(row) == (20, None)
        assert audits == 0


class TestListado:
    def test_lists_every_product_with_its_effective_name_ordered_by_stock(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            product(
                conn,
                4874,
                'NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  FDOS (9921)',
                cat_id=46,
                subcat_id=460,
                brand_id=11,
                stock=131,
            )
        patch(client, editor, {"nombre": "Adaptador UB500"})

        body = client.get(f"{BASE}/maestro", headers=editor).json()

        assert body["total"] == 2
        assert [(r["item_id"], r["nombre"], r["tipo"]) for r in body["items"]] == [
            (455, "Adaptador UB500", None),
            (4874, 'NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  FDOS (9921)', "notebook"),
        ]
        notebook = body["items"][1]
        assert notebook["specs_completos"] == 0 and notebook["specs_total"] > 0
        assert body["items"][0]["specs_total"] is None

    def test_filters_by_type_brand_text_and_incomplete_specs(self, client, pg, editor):
        with pg.begin() as conn:
            product(conn)
            product(conn, 4874, "NB ASUS E1504FA", cat_id=46, subcat_id=460, brand_id=11, marca="ASUS", stock=131)
        patch(client, editor, {"nombre": "Adaptador UB500"})

        def ids(**params):
            response = client.get(f"{BASE}/maestro", headers=editor, params=params)
            assert response.status_code == 200, response.text
            return [r["item_id"] for r in response.json()["items"]]

        assert ids(tipo="notebook") == [4874]
        assert ids(marca="asus") == [4874]
        assert ids(q="adaptador") == [455]  # the overridden name is searched
        assert ids(q="4874") == [4874]
        assert ids(incompletos=True) == [4874]

    def test_listing_needs_productos_ver(self, client, pg, admin_auth_headers):
        assert client.get(f"{BASE}/maestro", headers=admin_auth_headers).status_code == 403
