"""Categories, subcategories and brands masters (abm-productos delivery 2+3, S11, L10): seeded from GBP with the same
ids, renamed with the GBP value kept underneath, deactivated without deleting, own ones created above GBP's ids, and
each category/subcategory linked to a Tienda Nube category, a subcategory without its own link inheriting its
category's. Reading needs `productos.ver`; editing needs `productos.editar_categorias`."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.producto_categoria import PRIMER_ID_PROPIO
from app.models.tn_category_embedding import TnCategoryEmbedding
from app.services import producto_categorias as service
from tests.routers.test_ml_publications_links import grant

VER = "productos.ver"
EDITAR = "productos.editar_categorias"
CATS = "/api/producto-categorias"
MARCAS = "/api/producto-marcas"


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def editor(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR)
    return admin_auth_headers


@pytest.fixture()
def gbp(db):
    """A small GBP tree: CONECTIVIDAD (46) with ROUTERS (300) and SWITCHES (301), NOTEBOOKS (47) with no subcategory,
    brands TP-LINK (10) and LENOVO (11); three items to count."""
    for sql in (
        "INSERT INTO tb_category (comp_id, cat_id, cat_desc) VALUES (1, 46, 'CONECTIVIDAD'), (1, 47, 'NOTEBOOKS')",
        "INSERT INTO tb_subcategory (comp_id, cat_id, subcat_id, subcat_desc) "
        "VALUES (1, 46, 300, 'ROUTERS'), (1, 46, 301, 'SWITCHES')",
        "INSERT INTO tb_brand (comp_id, brand_id, brand_desc) VALUES (1, 10, 'TP-LINK'), (1, 11, 'LENOVO')",
        "INSERT INTO tb_item (comp_id, item_id, item_code, item_desc, cat_id, subcat_id, brand_id) VALUES "
        "(1, 1, 'A', 'RE200', 46, 300, 10), (1, 2, 'B', 'ARCHER', 46, 300, 10), (1, 3, 'C', 'V15', 47, NULL, 11)",
    ):
        db.execute(text(sql))
    service.sembrar_desde_gbp(db)
    db.flush()
    return db


@pytest.fixture()
def tn(db):
    for tn_id, path in ((900, "Redes"), (901, "Redes > Routers"), (902, "Redes > Switches"), (950, "Computación")):
        db.add(TnCategoryEmbedding(tn_category_id=tn_id, category_path_text=path, embedding=[0.0] * 3))
    db.flush()


def _cat(body: list[dict], cat_id: int) -> dict:
    return next(c for c in body if c["id"] == cat_id)


def _sub(cat: dict, sub_id: int) -> dict:
    return next(s for s in cat["subcategorias"] if s["id"] == sub_id)


def test_the_seed_inserts_gbp_ids_once_and_only_the_missing_ones(gbp) -> None:
    db = gbp
    db.execute(text("UPDATE producto_categorias SET nombre = 'REDES' WHERE id = 46"))
    db.execute(text("INSERT INTO tb_category (comp_id, cat_id, cat_desc) VALUES (1, 48, 'PROCESADORES')"))

    counts = service.sembrar_desde_gbp(db)

    assert counts == {"categorias": 1, "subcategorias": 0, "marcas": 0}
    assert db.execute(text("SELECT nombre FROM producto_categorias WHERE id = 46")).scalar_one() == "REDES"
    ids = db.execute(text("SELECT id FROM producto_categorias ORDER BY id")).scalars().all()
    assert ids == [46, 47, 48]
    subs = db.execute(text("SELECT id, categoria_id FROM producto_subcategorias ORDER BY id")).all()
    assert [tuple(r) for r in subs] == [(300, 46), (301, 46)]
    assert db.execute(text("SELECT count(*) FROM producto_marcas")).scalar_one() == 2


def test_the_list_shows_gbp_names_counts_and_no_override(client, reader, gbp) -> None:
    resp = client.get(CATS, headers=reader)

    assert resp.status_code == 200, resp.text
    conectividad = _cat(resp.json(), 46)
    assert conectividad["nombre"] == "CONECTIVIDAD"
    assert conectividad["nombre_gbp"] == "CONECTIVIDAD"
    assert conectividad["overrideado"] is False and conectividad["propia"] is False and conectividad["activa"] is True
    assert conectividad["productos"] == 2
    assert _sub(conectividad, 300)["productos"] == 2 and _sub(conectividad, 301)["productos"] == 0
    assert conectividad["vinculo_tn"] == "ninguno"


def test_a_rename_is_an_override_that_follows_gbp_again_on_revert(client, editor, gbp) -> None:
    resp = client.patch(f"{CATS}/46", json={"nombre": "  Redes y conectividad "}, headers=editor)

    assert resp.status_code == 200, resp.text
    assert resp.json()["nombre"] == "Redes y conectividad"
    assert resp.json()["nombre_gbp"] == "CONECTIVIDAD" and resp.json()["overrideado"] is True

    gbp.execute(text("UPDATE tb_category SET cat_desc = 'CONECTIVIDAD Y REDES' WHERE cat_id = 46"))
    reverted = client.patch(f"{CATS}/46", json={"nombre": None}, headers=editor)

    assert reverted.json()["nombre"] == "CONECTIVIDAD Y REDES"
    assert reverted.json()["overrideado"] is False


def test_renaming_to_the_gbp_value_is_not_an_override(client, editor, gbp) -> None:
    resp = client.patch(f"{CATS}/46", json={"nombre": "CONECTIVIDAD"}, headers=editor)

    assert resp.json()["overrideado"] is False
    assert gbp.execute(text("SELECT nombre FROM producto_categorias WHERE id = 46")).scalar_one() is None


def test_deactivating_keeps_the_row_and_its_subcategories(client, editor, gbp) -> None:
    resp = client.patch(f"{CATS}/46", json={"activa": False}, headers=editor)

    assert resp.status_code == 200
    listed = _cat(client.get(CATS, headers=editor).json(), 46)
    assert listed["activa"] is False and len(listed["subcategorias"]) == 2
    assert listed["productos"] == 2


def test_own_category_and_subcategory_get_ids_above_gbp(client, editor, gbp) -> None:
    created = client.post(CATS, json={"nombre": "Gaming"}, headers=editor)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["id"] == PRIMER_ID_PROPIO and body["propia"] is True and body["nombre_gbp"] is None
    second = client.post(CATS, json={"nombre": "Audio"}, headers=editor).json()
    assert second["id"] == PRIMER_ID_PROPIO + 1

    sub = client.post(f"{CATS}/{body['id']}/subcategorias", json={"nombre": "Sillas"}, headers=editor)

    assert sub.status_code == 201, sub.text
    assert sub.json()["id"] == PRIMER_ID_PROPIO and sub.json()["categoria_id"] == body["id"]


def test_an_own_category_cannot_revert_to_gbp_nor_have_an_empty_name(client, editor, gbp) -> None:
    own = client.post(CATS, json={"nombre": "Gaming"}, headers=editor).json()

    assert client.patch(f"{CATS}/{own['id']}", json={"nombre": None}, headers=editor).status_code == 422
    assert client.post(CATS, json={"nombre": "   "}, headers=editor).status_code == 422


def test_only_an_own_subcategory_moves_to_another_category(client, editor, gbp) -> None:
    gbp_move = client.patch(f"{CATS}/subcategorias/300", json={"categoria_id": 47}, headers=editor)
    assert gbp_move.status_code == 422

    own = client.post(f"{CATS}/46/subcategorias", json={"nombre": "Antenas"}, headers=editor).json()
    moved = client.patch(f"{CATS}/subcategorias/{own['id']}", json={"categoria_id": 47}, headers=editor)

    assert moved.status_code == 200, moved.text
    assert moved.json()["categoria_id"] == 47
    assert [s["id"] for s in _cat(client.get(CATS, headers=editor).json(), 47)["subcategorias"]] == [own["id"]]


def test_a_subcategory_without_its_own_link_inherits_its_category(client, editor, gbp, tn) -> None:
    resp = client.patch(f"{CATS}/46", json={"tn_category_id": 900}, headers=editor)

    assert resp.status_code == 200, resp.text
    cat = resp.json()
    assert cat["tn_categoria"] == "Redes" and cat["vinculo_tn"] == "completo"
    routers = _sub(cat, 300)
    assert routers["tn_category_id"] is None and routers["tn_heredada"] is True
    assert routers["tn_category_id_efectiva"] == 900 and routers["tn_categoria_efectiva"] == "Redes"

    own = client.patch(f"{CATS}/subcategorias/300", json={"tn_category_id": 901}, headers=editor).json()

    assert own["tn_heredada"] is False and own["tn_categoria_efectiva"] == "Redes > Routers"
    assert service.tn_category_efectiva(gbp, 46, 300) == 901
    assert service.tn_category_efectiva(gbp, 46, 301) == 900


def test_link_state_is_partial_when_only_some_subcategories_are_linked(client, editor, gbp, tn) -> None:
    client.patch(f"{CATS}/subcategorias/300", json={"tn_category_id": 901}, headers=editor)
    assert _cat(client.get(CATS, headers=editor).json(), 46)["vinculo_tn"] == "parcial"

    client.patch(f"{CATS}/subcategorias/301", json={"tn_category_id": 902}, headers=editor)
    assert _cat(client.get(CATS, headers=editor).json(), 46)["vinculo_tn"] == "completo"

    unlinked = client.patch(f"{CATS}/subcategorias/301", json={"tn_category_id": None}, headers=editor)
    assert unlinked.json()["tn_category_id"] is None
    assert _cat(client.get(CATS, headers=editor).json(), 46)["vinculo_tn"] == "parcial"


def test_an_unknown_tn_category_is_rejected(client, editor, gbp, tn) -> None:
    resp = client.patch(f"{CATS}/46", json={"tn_category_id": 12345}, headers=editor)

    assert resp.status_code == 422
    assert gbp.execute(text("SELECT tn_category_id FROM producto_categorias WHERE id = 46")).scalar_one() is None


def test_the_tn_picker_lists_the_mirrored_tree(client, reader, gbp, tn) -> None:
    resp = client.get(f"{CATS}/tn-categorias", params={"q": "redes"}, headers=reader)

    assert resp.status_code == 200
    assert [c["category_path"] for c in resp.json()] == ["Redes", "Redes > Routers", "Redes > Switches"]


def test_the_subcategory_suggestion_stays_in_the_category_branch(client, editor, gbp, tn, monkeypatch) -> None:
    seen: list[str] = []

    def fake_suggest(_db, category_text: str, top_n: int = 5) -> dict:
        seen.append(category_text)
        rows = [
            {"tn_category_id": 950, "category_path_text": "Computación", "similarity": 0.9},
            {"tn_category_id": 901, "category_path_text": "Redes > Routers", "similarity": 0.8},
        ]
        return {"suggestions": rows, "top": rows[0]}

    monkeypatch.setattr(service, "suggest_category", fake_suggest)
    client.patch(f"{CATS}/46", json={"tn_category_id": 900}, headers=editor)

    resp = client.get(f"{CATS}/subcategorias/300/sugerencia-tn", headers=editor)

    assert resp.status_code == 200, resp.text
    assert seen == ["CONECTIVIDAD > ROUTERS"]
    assert [s["tn_category_id"] for s in resp.json()["sugerencias"]] == [901]
    assert resp.json()["top"]["category_path_text"] == "Redes > Routers"


def test_editing_needs_the_permission(client, reader, gbp) -> None:
    assert client.patch(f"{CATS}/46", json={"activa": False}, headers=reader).status_code == 403
    assert client.post(CATS, json={"nombre": "X"}, headers=reader).status_code == 403
    assert client.patch(f"{MARCAS}/10", json={"activa": False}, headers=reader).status_code == 403
    assert client.post(f"{CATS}/tn-categorias/sync", headers=reader).status_code == 403


def test_reading_needs_productos_ver(client, admin_auth_headers, gbp) -> None:
    assert client.get(CATS, headers=admin_auth_headers).status_code == 403
    assert client.get(MARCAS, headers=admin_auth_headers).status_code == 403


def test_brands_rename_deactivate_and_create_like_categories(client, editor, gbp) -> None:
    listed = {m["id"]: m for m in client.get(MARCAS, headers=editor).json()}
    assert listed[10]["nombre"] == "TP-LINK" and listed[10]["productos"] == 2

    renamed = client.patch(f"{MARCAS}/10", json={"nombre": "TP-Link", "activa": False}, headers=editor).json()
    assert renamed["nombre"] == "TP-Link" and renamed["nombre_gbp"] == "TP-LINK"
    assert renamed["overrideado"] is True and renamed["activa"] is False

    own = client.post(MARCAS, json={"nombre": "Marca propia"}, headers=editor)
    assert own.status_code == 201 and own.json()["id"] == PRIMER_ID_PROPIO and own.json()["propia"] is True
    assert client.patch(f"{MARCAS}/999", json={"activa": False}, headers=editor).status_code == 404


def test_the_seed_follows_gbp_when_it_moves_one_of_its_subcategories(client, editor, gbp) -> None:
    own = client.post(f"{CATS}/46/subcategorias", json={"nombre": "Antenas"}, headers=editor).json()
    gbp.execute(text("UPDATE tb_subcategory SET cat_id = 47 WHERE subcat_id = 301"))

    service.sembrar_desde_gbp(gbp)

    rows = gbp.execute(text("SELECT id, categoria_id FROM producto_subcategorias ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(300, 46), (301, 47), (own["id"], 46)]


def test_a_concurrent_id_clash_answers_409(client, editor, gbp, monkeypatch) -> None:
    client.post(CATS, json={"nombre": "Gaming"}, headers=editor)
    monkeypatch.setattr(service, "_nuevo_id", lambda _db, _model: PRIMER_ID_PROPIO)

    assert client.post(CATS, json={"nombre": "Audio"}, headers=editor).status_code == 409
