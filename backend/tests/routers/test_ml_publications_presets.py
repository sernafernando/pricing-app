"""Publicaciones ML column layouts and presets (S2 storage, S3 permission, S4).

`/api/ml-publications/layouts/{vista}` keeps one column layout (visibility + order) and the remembered preset per
user and view; `/api/ml-publications/presets` holds the personal presets of each user and the shared ones. Every
endpoint needs the screen's access; the Auditoría view also needs `ml_publicaciones.ver_auditoria_stock`; shared
presets are written only with `ml_publicaciones.presets_compartidos`. Each test asserts the status code AND what
the tables hold afterwards.

Cast: `admin` (ADMIN: screen, shared presets, auditoría), `ana` and `beto` (VENTAS: screen only), `nadie` (no
screen access).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.security import get_password_hash
from app.models.ml_publicaciones_preset import MlPublicacionesLayout, MlPublicacionesPreset
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from tests.conftest import make_access_token

LAYOUTS = "/api/ml-publications/layouts"
PRESETS = "/api/ml-publications/presets"
VER = "productos.ver"
COMPARTIDOS = "ml_publicaciones.presets_compartidos"
AUDITORIA = "ml_publicaciones.ver_auditoria_stock"

COLUMNS = {"visibility": {"ventas_30d": True, "markup": False}, "order": ["markup", "ventas_30d"]}
PAYLOAD = {"columns": COLUMNS, "params": {"estado": "active", "orden": "facturado_30d", "dir": "desc"}}


def _user(db, rol, username: str) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username.title(),
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _headers(user: Usuario) -> dict:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


@pytest.fixture()
def cast(db, rol_admin, rol_ventas, admin_user, grant_permiso):
    """The four users of these tests, with their headers and ids."""
    from app.models.rol import Rol

    for codigo in (VER, COMPARTIDOS, AUDITORIA):
        grant_permiso(rol_admin, codigo)
    grant_permiso(rol_ventas, VER)
    rol_nada = Rol(codigo="NADA", nombre="Nada", es_sistema=False, orden=99, activo=True)
    db.add(rol_nada)
    db.flush()
    ana = _user(db, rol_ventas, "ana")
    beto = _user(db, rol_ventas, "beto")
    nadie = _user(db, rol_nada, "nadie")
    db.commit()
    return {
        "admin": _headers(admin_user),
        "ana": _headers(ana),
        "beto": _headers(beto),
        "nadie": _headers(nadie),
        "ids": {"admin": admin_user.id, "ana": ana.id, "beto": beto.id},
    }


def _count(db, model) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def _preset(db, preset_id: int) -> MlPublicacionesPreset | None:
    db.expire_all()
    return db.get(MlPublicacionesPreset, preset_id)


def _layout(db, usuario_id: int, vista: str) -> MlPublicacionesLayout | None:
    db.expire_all()
    return db.execute(
        select(MlPublicacionesLayout).where(
            MlPublicacionesLayout.usuario_id == usuario_id, MlPublicacionesLayout.vista == vista
        )
    ).scalar_one_or_none()


def _create(client, headers, *, vista="publicacion", nombre="Mi preset", compartido=False, payload=None):
    body = {"vista": vista, "nombre": nombre, "compartido": compartido, "payload": payload or PAYLOAD}
    return client.post(PRESETS, headers=headers, json=body)


def _created(client, headers, **kwargs) -> dict:
    response = _create(client, headers, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def _list(client, headers, vista="publicacion") -> list[dict]:
    response = client.get(PRESETS, headers=headers, params={"vista": vista})
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------------------------------------------


class TestAccess:
    def test_every_endpoint_needs_the_screen_access(self, client, db, cast):
        h = cast["nadie"]
        assert client.get(f"{LAYOUTS}/publicacion", headers=h).status_code == 403
        assert client.put(f"{LAYOUTS}/publicacion", headers=h, json={"columns": COLUMNS}).status_code == 403
        assert client.get(PRESETS, headers=h, params={"vista": "publicacion"}).status_code == 403
        assert _create(client, h).status_code == 403
        assert _count(db, MlPublicacionesPreset) == 0
        assert _count(db, MlPublicacionesLayout) == 0

    def test_auditoria_needs_its_permission(self, client, db, cast):
        h = cast["ana"]
        assert client.get(f"{LAYOUTS}/auditoria", headers=h).status_code == 403
        assert client.put(f"{LAYOUTS}/auditoria", headers=h, json={"columns": COLUMNS}).status_code == 403
        assert client.get(PRESETS, headers=h, params={"vista": "auditoria"}).status_code == 403
        assert _create(client, h, vista="auditoria").status_code == 403
        assert _count(db, MlPublicacionesPreset) == 0
        assert _count(db, MlPublicacionesLayout) == 0

    def test_auditoria_works_with_its_permission(self, client, db, cast):
        created = _created(client, cast["admin"], vista="auditoria")
        assert created["vista"] == "auditoria"
        assert client.put(f"{LAYOUTS}/auditoria", headers=cast["admin"], json={"columns": COLUMNS}).status_code == 200
        assert _layout(db, cast["ids"]["admin"], "auditoria").column_layout == COLUMNS

    def test_an_unknown_vista_is_422(self, client, db, cast):
        h = cast["ana"]
        assert client.get(f"{LAYOUTS}/otra", headers=h).status_code == 422
        assert client.put(f"{LAYOUTS}/otra", headers=h, json={"columns": COLUMNS}).status_code == 422
        assert client.get(PRESETS, headers=h, params={"vista": "otra"}).status_code == 422
        assert _create(client, h, vista="otra").status_code == 422
        assert _count(db, MlPublicacionesPreset) == 0
        assert _count(db, MlPublicacionesLayout) == 0


# --------------------------------------------------------------------------------------------------------------
# Layouts
# --------------------------------------------------------------------------------------------------------------


class TestLayouts:
    def test_nothing_saved_reads_nulls(self, client, db, cast):
        response = client.get(f"{LAYOUTS}/producto", headers=cast["ana"])
        assert response.status_code == 200
        assert response.json() == {"columns": None, "preset_activo_id": None}
        assert _count(db, MlPublicacionesLayout) == 0

    def test_put_then_get_roundtrips_per_user_and_view(self, client, db, cast):
        preset = _created(client, cast["ana"])
        body = {"columns": COLUMNS, "preset_activo_id": preset["id"]}

        response = client.put(f"{LAYOUTS}/publicacion", headers=cast["ana"], json=body)

        assert response.status_code == 200
        assert response.json() == body
        assert client.get(f"{LAYOUTS}/publicacion", headers=cast["ana"]).json() == body
        stored = _layout(db, cast["ids"]["ana"], "publicacion")
        assert stored.column_layout == COLUMNS
        assert stored.preset_activo_id == preset["id"]
        # Another view and another user stay empty.
        assert client.get(f"{LAYOUTS}/precios", headers=cast["ana"]).json() == {
            "columns": None,
            "preset_activo_id": None,
        }
        assert client.get(f"{LAYOUTS}/publicacion", headers=cast["beto"]).json() == {
            "columns": None,
            "preset_activo_id": None,
        }

    def test_a_second_put_overwrites_the_same_row(self, client, db, cast):
        client.put(f"{LAYOUTS}/precios", headers=cast["ana"], json={"columns": COLUMNS, "preset_activo_id": None})
        other = {"visibility": {"markup": True}, "order": ["markup"]}

        response = client.put(
            f"{LAYOUTS}/precios", headers=cast["ana"], json={"columns": other, "preset_activo_id": None}
        )

        assert response.status_code == 200
        assert _count(db, MlPublicacionesLayout) == 1
        assert _layout(db, cast["ids"]["ana"], "precios").column_layout == other

    def test_restablecer_stores_nulls(self, client, db, cast):
        preset = _created(client, cast["ana"])
        client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": COLUMNS, "preset_activo_id": preset["id"]}
        )

        response = client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": None, "preset_activo_id": None}
        )

        assert response.status_code == 200
        assert response.json() == {"columns": None, "preset_activo_id": None}
        stored = _layout(db, cast["ids"]["ana"], "publicacion")
        assert stored is None or (stored.column_layout is None and stored.preset_activo_id is None)
        assert client.get(f"{LAYOUTS}/publicacion", headers=cast["ana"]).json() == {
            "columns": None,
            "preset_activo_id": None,
        }

    def test_another_users_personal_preset_is_404_and_nothing_stored(self, client, db, cast):
        preset = _created(client, cast["beto"])

        response = client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": COLUMNS, "preset_activo_id": preset["id"]}
        )

        assert response.status_code == 404
        assert _layout(db, cast["ids"]["ana"], "publicacion") is None

    def test_a_preset_of_another_vista_is_404(self, client, db, cast):
        preset = _created(client, cast["ana"], vista="precios")

        response = client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": None, "preset_activo_id": preset["id"]}
        )

        assert response.status_code == 404
        assert _layout(db, cast["ids"]["ana"], "publicacion") is None

    def test_an_unknown_preset_is_404(self, client, db, cast):
        response = client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": None, "preset_activo_id": 999999}
        )
        assert response.status_code == 404
        assert _count(db, MlPublicacionesLayout) == 0

    def test_a_shared_preset_can_be_remembered_by_anyone(self, client, db, cast):
        shared = _created(client, cast["admin"], compartido=True, nombre="Equipo")

        response = client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": None, "preset_activo_id": shared["id"]}
        )

        assert response.status_code == 200
        assert _layout(db, cast["ids"]["ana"], "publicacion").preset_activo_id == shared["id"]

    def test_deleting_the_preset_nulls_the_remembered_one(self, client, db, cast):
        preset = _created(client, cast["ana"])
        client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": COLUMNS, "preset_activo_id": preset["id"]}
        )

        assert client.delete(f"{PRESETS}/{preset['id']}", headers=cast["ana"]).status_code == 204

        stored = _layout(db, cast["ids"]["ana"], "publicacion")
        assert stored.preset_activo_id is None
        assert stored.column_layout == COLUMNS
        assert client.get(f"{LAYOUTS}/publicacion", headers=cast["ana"]).json() == {
            "columns": COLUMNS,
            "preset_activo_id": None,
        }

    def test_a_remembered_preset_no_longer_visible_reads_null(self, client, db, cast):
        preset = _created(client, cast["beto"])
        # Planted directly: a row pointing at a preset this user cannot see (the API never stores one).
        db.add(MlPublicacionesLayout(usuario_id=cast["ids"]["ana"], vista="publicacion", preset_activo_id=preset["id"]))
        db.commit()

        response = client.get(f"{LAYOUTS}/publicacion", headers=cast["ana"])

        assert response.status_code == 200
        assert response.json() == {"columns": None, "preset_activo_id": None}

    @pytest.mark.parametrize(
        "columns",
        [
            {"visibility": {"Markup": True}, "order": []},  # bad key
            {"visibility": {}, "order": ["a-b"]},  # bad key
            {"visibility": {}, "order": ["markup", "markup"]},  # duplicate order
            {"visibility": {}, "order": [], "extra": 1},  # extra field
            {"visibility": {f"c{i}": True for i in range(201)}, "order": []},  # too many entries
        ],
    )
    def test_an_invalid_layout_is_422_and_nothing_stored(self, client, db, cast, columns):
        response = client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": columns, "preset_activo_id": None}
        )
        assert response.status_code == 422
        assert _count(db, MlPublicacionesLayout) == 0

    def test_an_extra_body_field_is_422(self, client, db, cast):
        response = client.put(
            f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": None, "preset_activo_id": None, "x": 1}
        )
        assert response.status_code == 422
        assert _count(db, MlPublicacionesLayout) == 0


# --------------------------------------------------------------------------------------------------------------
# Presets: visibility and ownership
# --------------------------------------------------------------------------------------------------------------


class TestPresetVisibility:
    def test_create_personal_returns_the_item_and_stores_it(self, client, db, cast):
        response = _create(client, cast["ana"], nombre="  Ventas fuertes  ")

        assert response.status_code == 201
        body = response.json()
        assert body["vista"] == "publicacion"
        assert body["nombre"] == "Ventas fuertes"
        assert body["compartido"] is False
        assert body["editable"] is True
        assert body["payload"] == PAYLOAD
        assert body["updated_at"]
        stored = _preset(db, body["id"])
        assert stored.usuario_id == cast["ids"]["ana"]
        assert stored.created_by == cast["ids"]["ana"]
        assert stored.nombre == "Ventas fuertes"
        assert stored.payload == PAYLOAD

    def test_another_users_personal_preset_is_not_listed(self, client, db, cast):
        _created(client, cast["beto"], nombre="De Beto")
        mine = _created(client, cast["ana"], nombre="De Ana")

        listed = _list(client, cast["ana"])

        assert [p["id"] for p in listed] == [mine["id"]]

    def test_another_users_personal_preset_is_404_on_put_and_delete(self, client, db, cast):
        preset = _created(client, cast["beto"], nombre="De Beto")

        put = client.put(
            f"{PRESETS}/{preset['id']}",
            headers=cast["ana"],
            json={"nombre": "Robado", "payload": {"columns": COLUMNS, "params": {}}},
        )
        delete = client.delete(f"{PRESETS}/{preset['id']}", headers=cast["ana"])

        assert put.status_code == 404
        assert delete.status_code == 404
        stored = _preset(db, preset["id"])
        assert stored.nombre == "De Beto"
        assert stored.payload == PAYLOAD

    def test_another_users_personal_preset_is_404_even_for_an_admin(self, client, db, cast):
        preset = _created(client, cast["beto"], nombre="De Beto")
        assert client.delete(f"{PRESETS}/{preset['id']}", headers=cast["admin"]).status_code == 404
        assert _preset(db, preset["id"]) is not None

    def test_shared_preset_is_visible_but_not_editable_without_permission(self, client, db, cast):
        shared = _created(client, cast["admin"], nombre="Equipo", compartido=True)

        listed = _list(client, cast["ana"])

        assert [(p["id"], p["compartido"], p["editable"]) for p in listed] == [(shared["id"], True, False)]
        assert _list(client, cast["admin"])[0]["editable"] is True

    def test_listing_is_shared_first_then_by_name_and_per_vista(self, client, db, cast):
        _created(client, cast["admin"], nombre="zeta", compartido=True)
        _created(client, cast["admin"], nombre="Alfa", compartido=True)
        _created(client, cast["ana"], nombre="beta")
        _created(client, cast["ana"], nombre="Aaa")
        _created(client, cast["ana"], nombre="Otra vista", vista="precios")

        listed = _list(client, cast["ana"])

        assert [p["nombre"] for p in listed] == ["Alfa", "zeta", "Aaa", "beta"]

    def test_unknown_preset_is_404(self, client, db, cast):
        assert client.put(f"{PRESETS}/999999", headers=cast["ana"], json={"nombre": "x"}).status_code == 404
        assert client.delete(f"{PRESETS}/999999", headers=cast["ana"]).status_code == 404


# --------------------------------------------------------------------------------------------------------------
# Presets: writes and permission
# --------------------------------------------------------------------------------------------------------------


class TestPresetWrites:
    def test_owner_renames_and_overwrites(self, client, db, cast):
        preset = _created(client, cast["ana"])
        new_payload = {"columns": {"visibility": {}, "order": ["markup"]}, "params": {"modo": "cuotas"}}

        response = client.put(
            f"{PRESETS}/{preset['id']}", headers=cast["ana"], json={"nombre": "Nuevo", "payload": new_payload}
        )

        assert response.status_code == 200
        assert response.json()["nombre"] == "Nuevo"
        assert response.json()["payload"] == new_payload
        stored = _preset(db, preset["id"])
        assert stored.nombre == "Nuevo"
        assert stored.payload == new_payload

    def test_owner_deletes(self, client, db, cast):
        preset = _created(client, cast["ana"])
        assert client.delete(f"{PRESETS}/{preset['id']}", headers=cast["ana"]).status_code == 204
        assert _preset(db, preset["id"]) is None

    def test_shared_create_needs_the_permission(self, client, db, cast):
        response = _create(client, cast["ana"], compartido=True)
        assert response.status_code == 403
        assert _count(db, MlPublicacionesPreset) == 0

    def test_shared_create_with_the_permission(self, client, db, cast):
        body = _created(client, cast["admin"], compartido=True, nombre="Equipo")
        assert body["compartido"] is True
        assert body["editable"] is True
        stored = _preset(db, body["id"])
        assert stored.usuario_id is None
        assert stored.created_by == cast["ids"]["admin"]

    def test_shared_edit_and_delete_need_the_permission(self, client, db, cast):
        shared = _created(client, cast["admin"], compartido=True, nombre="Equipo")

        put = client.put(f"{PRESETS}/{shared['id']}", headers=cast["ana"], json={"nombre": "Mío"})
        delete = client.delete(f"{PRESETS}/{shared['id']}", headers=cast["ana"])

        assert put.status_code == 403
        assert delete.status_code == 403
        assert _preset(db, shared["id"]).nombre == "Equipo"

    def test_shared_edit_and_delete_with_the_permission(self, client, db, cast):
        shared = _created(client, cast["admin"], compartido=True, nombre="Equipo")

        put = client.put(f"{PRESETS}/{shared['id']}", headers=cast["admin"], json={"nombre": "Equipo 2"})
        assert put.status_code == 200
        assert _preset(db, shared["id"]).nombre == "Equipo 2"

        assert client.delete(f"{PRESETS}/{shared['id']}", headers=cast["admin"]).status_code == 204
        assert _preset(db, shared["id"]) is None

    def test_duplicate_personal_name_is_409_case_insensitive(self, client, db, cast):
        _created(client, cast["ana"], nombre="Ventas")
        response = _create(client, cast["ana"], nombre="  vENTAS ")
        assert response.status_code == 409
        assert _count(db, MlPublicacionesPreset) == 1

    def test_same_name_for_another_user_or_another_vista_is_fine(self, client, db, cast):
        _created(client, cast["ana"], nombre="Ventas")
        _created(client, cast["beto"], nombre="Ventas")
        _created(client, cast["ana"], nombre="Ventas", vista="precios")
        assert _count(db, MlPublicacionesPreset) == 3

    def test_duplicate_shared_name_is_409(self, client, db, cast):
        _created(client, cast["admin"], nombre="Equipo", compartido=True)
        response = _create(client, cast["admin"], nombre="equipo", compartido=True)
        assert response.status_code == 409
        assert _count(db, MlPublicacionesPreset) == 1

    def test_rename_to_a_taken_name_is_409(self, client, db, cast):
        _created(client, cast["ana"], nombre="Uno")
        dos = _created(client, cast["ana"], nombre="Dos")

        response = client.put(f"{PRESETS}/{dos['id']}", headers=cast["ana"], json={"nombre": "UNO"})

        assert response.status_code == 409
        assert _preset(db, dos["id"]).nombre == "Dos"

    def test_renaming_to_its_own_name_in_other_case_is_fine(self, client, db, cast):
        uno = _created(client, cast["ana"], nombre="Uno")
        response = client.put(f"{PRESETS}/{uno['id']}", headers=cast["ana"], json={"nombre": "UNO"})
        assert response.status_code == 200
        assert _preset(db, uno["id"]).nombre == "UNO"

    @pytest.mark.parametrize("nombre", ["Predeterminado", " predeterminado "])
    def test_predeterminado_is_reserved(self, client, db, cast, nombre):
        assert _create(client, cast["ana"], nombre=nombre).status_code == 409
        assert _create(client, cast["admin"], nombre=nombre, compartido=True).status_code == 409
        assert _count(db, MlPublicacionesPreset) == 0
        uno = _created(client, cast["ana"], nombre="Uno")
        assert client.put(f"{PRESETS}/{uno['id']}", headers=cast["ana"], json={"nombre": nombre}).status_code == 409
        assert _preset(db, uno["id"]).nombre == "Uno"


# --------------------------------------------------------------------------------------------------------------
# Presets: payload validation (422 and nothing stored)
# --------------------------------------------------------------------------------------------------------------


def _big_params() -> dict[str, str]:
    """20 keys of 2000 chars each: every value is valid, the whole payload is over 32 KB."""
    return {f"p{i}": "x" * 2000 for i in range(20)}


INVALID_PAYLOADS = [
    pytest.param({"columns": {"visibility": {"Bad-Key": True}, "order": []}, "params": {}}, id="bad-column-key"),
    pytest.param({"columns": COLUMNS, "params": {"Estado": "x"}}, id="bad-param-key"),
    pytest.param({"columns": {"visibility": {}, "order": ["a", "a"]}, "params": {}}, id="duplicate-order"),
    pytest.param({"columns": COLUMNS, "params": {}, "extra": True}, id="extra-payload-field"),
    pytest.param({"columns": {**COLUMNS, "width": {}}, "params": {}}, id="extra-columns-field"),
    pytest.param({"columns": COLUMNS, "params": _big_params()}, id="oversized"),
    pytest.param({"columns": COLUMNS, "params": {"q": "x" * 2001}}, id="long-param-value"),
    pytest.param({"columns": COLUMNS, "params": {f"k{i}": "1" for i in range(81)}}, id="too-many-params"),
    pytest.param({"columns": COLUMNS, "params": {"estado": 1}}, id="non-string-param"),
    pytest.param({"columns": COLUMNS}, id="missing-params"),
]


class TestPresetValidation:
    @pytest.mark.parametrize("payload", INVALID_PAYLOADS)
    def test_invalid_payload_on_create_is_422_and_nothing_stored(self, client, db, cast, payload):
        response = _create(client, cast["ana"], payload=payload)
        assert response.status_code == 422, response.text
        assert _count(db, MlPublicacionesPreset) == 0

    @pytest.mark.parametrize("payload", INVALID_PAYLOADS)
    def test_invalid_payload_on_update_is_422_and_nothing_changes(self, client, db, cast, payload):
        preset = _created(client, cast["ana"])
        response = client.put(f"{PRESETS}/{preset['id']}", headers=cast["ana"], json={"payload": payload})
        assert response.status_code == 422, response.text
        assert _preset(db, preset["id"]).payload == PAYLOAD

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                {"vista": "publicacion", "nombre": "x", "compartido": False, "payload": PAYLOAD, "y": 1},
                id="extra-field",
            ),
            pytest.param({"vista": "otra", "nombre": "x", "compartido": False, "payload": PAYLOAD}, id="bad-vista"),
            pytest.param(
                {"vista": "publicacion", "nombre": "   ", "compartido": False, "payload": PAYLOAD}, id="blank-name"
            ),
            pytest.param(
                {"vista": "publicacion", "nombre": "x" * 61, "compartido": False, "payload": PAYLOAD}, id="long-name"
            ),
        ],
    )
    def test_invalid_create_body_is_422_and_nothing_stored(self, client, db, cast, body):
        response = client.post(PRESETS, headers=cast["ana"], json=body)
        assert response.status_code == 422, response.text
        assert _count(db, MlPublicacionesPreset) == 0

    def test_extra_field_on_update_is_422(self, client, db, cast):
        preset = _created(client, cast["ana"])
        response = client.put(
            f"{PRESETS}/{preset['id']}", headers=cast["ana"], json={"nombre": "Otro", "vista": "precios"}
        )
        assert response.status_code == 422
        stored = _preset(db, preset["id"])
        assert (stored.nombre, stored.vista) == ("Mi preset", "publicacion")


def test_put_layout_that_loses_the_insert_race_updates_the_row_instead_of_failing(client, db, cast, monkeypatch):
    """Two first saves of the same view at once: the one that finds no row, inserts and hits the unique
    (usuario, vista) constraint must update the row the other one wrote, not answer 500."""
    from app.routers import ml_publications_presets as router_module

    db.add(MlPublicacionesLayout(usuario_id=cast["ids"]["ana"], vista="publicacion", column_layout=None))
    db.commit()
    real = router_module._layout_row
    calls = {"n": 0}

    def stale_first_read(*args, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*args, **kwargs)

    monkeypatch.setattr(router_module, "_layout_row", stale_first_read)

    response = client.put(
        f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": COLUMNS, "preset_activo_id": None}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"columns": COLUMNS, "preset_activo_id": None}
    assert _count(db, MlPublicacionesLayout) == 1
    assert _layout(db, cast["ids"]["ana"], "publicacion").column_layout == COLUMNS


def _delete_after_validation(db, monkeypatch) -> None:
    """The remembered preset is deleted by another request right after `put_layout` checked it."""
    from sqlalchemy import delete

    from app.routers import ml_publications_presets as router_module

    real = router_module._visible_preset

    def checked_then_deleted(session, preset_id, user):
        preset = real(session, preset_id, user)
        session.execute(delete(MlPublicacionesPreset).where(MlPublicacionesPreset.id == preset_id))
        session.commit()
        return preset

    monkeypatch.setattr(router_module, "_visible_preset", checked_then_deleted)


def test_first_layout_save_with_a_preset_deleted_meanwhile_is_404_and_stores_nothing(client, db, cast, monkeypatch):
    preset = _created(client, cast["ana"])
    _delete_after_validation(db, monkeypatch)

    response = client.put(
        f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": COLUMNS, "preset_activo_id": preset["id"]}
    )

    assert response.status_code == 404, response.text
    assert _count(db, MlPublicacionesLayout) == 0
    assert _preset(db, preset["id"]) is None


def test_layout_update_with_a_preset_deleted_meanwhile_is_404_and_keeps_the_saved_layout(client, db, cast, monkeypatch):
    preset = _created(client, cast["ana"])
    saved = {"visibility": {"markup": True}, "order": ["markup"]}
    first = client.put(f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": saved, "preset_activo_id": None})
    assert first.status_code == 200, first.text
    _delete_after_validation(db, monkeypatch)

    response = client.put(
        f"{LAYOUTS}/publicacion", headers=cast["ana"], json={"columns": COLUMNS, "preset_activo_id": preset["id"]}
    )

    assert response.status_code == 404, response.text
    layout = _layout(db, cast["ids"]["ana"], "publicacion")
    assert layout.column_layout == saved
    assert layout.preset_activo_id is None
    assert _count(db, MlPublicacionesLayout) == 1
