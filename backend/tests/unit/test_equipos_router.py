"""
Unit tests — equipos router (PR4 of productos-color-teams).

Verifies:
- Team creation (creator becomes admin, appears in GET /equipos).
- GET /equipos includes the global ("U") team plus the caller's teams only.
- Membership management (add/change-rol/remove) is admin-only, rejects
  non-members and non-admin members with 403.
- Last-admin guard on rol-demotion and member-removal.
- Rename/delete are admin-only.
- The global ("U") team rejects every membership/rename/delete mutation
  (implicit membership).
- Non-existent usuario_id / equipo_id -> 404.
"""

from __future__ import annotations


from app.core.security import get_password_hash
from app.models.equipo import Equipo, EquipoMiembro, RolEquipo
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _make_usuario(db, username: str, rol_id: int) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_equipo(db, nombre: str, es_global: bool = False) -> Equipo:
    equipo = Equipo(nombre=nombre, es_global=es_global)
    db.add(equipo)
    db.flush()
    return equipo


def _add_member(db, equipo_id: int, usuario_id: int, rol: RolEquipo = RolEquipo.MIEMBRO) -> EquipoMiembro:
    miembro = EquipoMiembro(equipo_id=equipo_id, usuario_id=usuario_id, rol=rol.value)
    db.add(miembro)
    db.flush()
    return miembro


def _global_equipo(db) -> Equipo:
    equipo = db.query(Equipo).filter(Equipo.es_global.is_(True)).first()
    if equipo is None:
        equipo = _make_equipo(db, "Global", es_global=True)
    return equipo


def auth_headers_for(user: Usuario) -> dict:
    from tests.conftest import make_access_token

    token = make_access_token(user)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Creation + listing
# ---------------------------------------------------------------------------


class TestCrearYListarEquipos:
    def test_crear_equipo_creador_es_admin_y_aparece_en_listado(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        user = _make_usuario(db, "creator1", rol_ventas.id)
        db.commit()

        resp = client.post("/api/equipos", json={"nombre": "Equipo Ventas"}, headers=auth_headers_for(user))
        assert resp.status_code == 201
        equipo_id = resp.json()["id"]
        assert resp.json()["es_global"] is False

        miembro = (
            db.query(EquipoMiembro)
            .filter(EquipoMiembro.equipo_id == equipo_id, EquipoMiembro.usuario_id == user.id)
            .first()
        )
        assert miembro is not None
        assert miembro.rol == RolEquipo.ADMIN.value

        resp_list = client.get("/api/equipos", headers=auth_headers_for(user))
        assert resp_list.status_code == 200
        ids = {e["id"] for e in resp_list.json()}
        assert equipo_id in ids

    def test_listar_incluye_global_y_excluye_equipos_ajenos(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        propio = _make_equipo(db, "Mi equipo")
        ajeno = _make_equipo(db, "Equipo ajeno")
        user = _make_usuario(db, "listuser", rol_ventas.id)
        _add_member(db, propio.id, user.id, RolEquipo.ADMIN)
        other = _make_usuario(db, "otheruser", rol_ventas.id)
        _add_member(db, ajeno.id, other.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.get("/api/equipos", headers=auth_headers_for(user))
        assert resp.status_code == 200
        ids = {e["id"] for e in resp.json()}
        assert propio.id in ids
        assert equipo_global.id in ids
        assert ajeno.id not in ids

        global_entry = next(e for e in resp.json() if e["id"] == equipo_global.id)
        assert global_entry["es_global"] is True


# ---------------------------------------------------------------------------
# Membership management
# ---------------------------------------------------------------------------


class TestGestionMiembros:
    def test_admin_agrega_miembro(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo A")
        admin = _make_usuario(db, "admin_a", rol_ventas.id)
        nuevo = _make_usuario(db, "nuevo_a", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.post(
            f"/api/equipos/{equipo.id}/miembros",
            json={"usuario_id": nuevo.id, "rol": "miembro"},
            headers=auth_headers_for(admin),
        )
        assert resp.status_code == 201
        assert resp.json()["usuario_id"] == nuevo.id

    def test_no_admin_no_puede_agregar_miembro(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo B")
        admin = _make_usuario(db, "admin_b", rol_ventas.id)
        miembro_user = _make_usuario(db, "miembro_b", rol_ventas.id)
        nuevo = _make_usuario(db, "nuevo_b", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        _add_member(db, equipo.id, miembro_user.id, RolEquipo.MIEMBRO)
        db.commit()

        resp = client.post(
            f"/api/equipos/{equipo.id}/miembros",
            json={"usuario_id": nuevo.id},
            headers=auth_headers_for(miembro_user),
        )
        assert resp.status_code == 403

    def test_no_miembro_no_puede_agregar_miembro(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo C")
        admin = _make_usuario(db, "admin_c", rol_ventas.id)
        outsider = _make_usuario(db, "outsider_c", rol_ventas.id)
        nuevo = _make_usuario(db, "nuevo_c", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.post(
            f"/api/equipos/{equipo.id}/miembros",
            json={"usuario_id": nuevo.id},
            headers=auth_headers_for(outsider),
        )
        assert resp.status_code == 403

    def test_listar_miembros_requiere_ser_miembro(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo D")
        admin = _make_usuario(db, "admin_d", rol_ventas.id)
        outsider = _make_usuario(db, "outsider_d", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp_ok = client.get(f"/api/equipos/{equipo.id}/miembros", headers=auth_headers_for(admin))
        assert resp_ok.status_code == 200

        resp_forbidden = client.get(f"/api/equipos/{equipo.id}/miembros", headers=auth_headers_for(outsider))
        assert resp_forbidden.status_code == 403

    def test_admin_cambia_rol_de_miembro(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo E")
        admin = _make_usuario(db, "admin_e", rol_ventas.id)
        miembro_user = _make_usuario(db, "miembro_e", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        _add_member(db, equipo.id, miembro_user.id, RolEquipo.MIEMBRO)
        db.commit()

        resp = client.patch(
            f"/api/equipos/{equipo.id}/miembros/{miembro_user.id}",
            json={"rol": "admin"},
            headers=auth_headers_for(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["rol"] == "admin"

    def test_no_se_puede_quitar_al_ultimo_admin_por_democion(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo F")
        admin = _make_usuario(db, "admin_f", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.patch(
            f"/api/equipos/{equipo.id}/miembros/{admin.id}",
            json={"rol": "miembro"},
            headers=auth_headers_for(admin),
        )
        assert resp.status_code == 400

    def test_no_se_puede_eliminar_al_ultimo_admin(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo G")
        admin = _make_usuario(db, "admin_g", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.delete(f"/api/equipos/{equipo.id}/miembros/{admin.id}", headers=auth_headers_for(admin))
        assert resp.status_code == 400

    def test_no_se_puede_degradar_al_ultimo_admin_por_reagregado(self, client, db, rol_ventas) -> None:
        # The idempotent POST upsert must enforce the same last-admin guard as
        # PATCH/DELETE: the sole admin re-adding themselves (rol defaults to
        # miembro) would otherwise orphan the team with zero admins.
        equipo = _make_equipo(db, "Equipo G2")
        admin = _make_usuario(db, "admin_g2", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.post(
            f"/api/equipos/{equipo.id}/miembros",
            json={"usuario_id": admin.id},
            headers=auth_headers_for(admin),
        )
        assert resp.status_code == 400
        # The admin must still be admin — team not orphaned.
        db.expire_all()
        miembro = db.query(EquipoMiembro).filter_by(equipo_id=equipo.id, usuario_id=admin.id).first()
        assert miembro.rol == RolEquipo.ADMIN.value

    def test_admin_elimina_miembro(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo H")
        admin = _make_usuario(db, "admin_h", rol_ventas.id)
        miembro_user = _make_usuario(db, "miembro_h", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        _add_member(db, equipo.id, miembro_user.id, RolEquipo.MIEMBRO)
        db.commit()

        resp = client.delete(f"/api/equipos/{equipo.id}/miembros/{miembro_user.id}", headers=auth_headers_for(admin))
        assert resp.status_code == 200
        assert db.query(EquipoMiembro).filter(EquipoMiembro.equipo_id == equipo.id, EquipoMiembro.usuario_id == miembro_user.id).first() is None

    def test_usuario_inexistente_404(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo I")
        admin = _make_usuario(db, "admin_i", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.post(
            f"/api/equipos/{equipo.id}/miembros",
            json={"usuario_id": 999999},
            headers=auth_headers_for(admin),
        )
        assert resp.status_code == 404

    def test_equipo_inexistente_404(self, client, db, rol_ventas) -> None:
        user = _make_usuario(db, "u_missing_equipo", rol_ventas.id)
        db.commit()

        resp = client.get("/api/equipos/999999/miembros", headers=auth_headers_for(user))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Rename / delete
# ---------------------------------------------------------------------------


class TestRenombrarYEliminar:
    def test_admin_renombra_equipo(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Nombre viejo")
        admin = _make_usuario(db, "admin_rename", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.patch(f"/api/equipos/{equipo.id}", json={"nombre": "Nombre nuevo"}, headers=auth_headers_for(admin))
        assert resp.status_code == 200
        assert resp.json()["nombre"] == "Nombre nuevo"

    def test_no_admin_no_puede_renombrar(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Nombre X")
        admin = _make_usuario(db, "admin_rename2", rol_ventas.id)
        miembro_user = _make_usuario(db, "miembro_rename2", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        _add_member(db, equipo.id, miembro_user.id, RolEquipo.MIEMBRO)
        db.commit()

        resp = client.patch(f"/api/equipos/{equipo.id}", json={"nombre": "Hackeado"}, headers=auth_headers_for(miembro_user))
        assert resp.status_code == 403

    def test_admin_elimina_equipo_sin_colores(self, client, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Para borrar")
        admin = _make_usuario(db, "admin_delete", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        db.commit()

        resp = client.delete(f"/api/equipos/{equipo.id}", headers=auth_headers_for(admin))
        assert resp.status_code == 200
        assert db.query(Equipo).filter(Equipo.id == equipo.id).first() is None

    def test_no_se_puede_eliminar_equipo_con_colores(self, client, db, rol_ventas) -> None:
        from app.models.equipo import ProductoColor
        from app.models.producto import ProductoERP

        equipo = _make_equipo(db, "Con colores")
        admin = _make_usuario(db, "admin_delete_colors", rol_ventas.id)
        _add_member(db, equipo.id, admin.id, RolEquipo.ADMIN)
        producto = ProductoERP(item_id=555, codigo="C555", descripcion="Prod")
        db.add(producto)
        db.flush()
        db.add(ProductoColor(equipo_id=equipo.id, item_id=555, color_ml="rojo"))
        db.commit()

        resp = client.delete(f"/api/equipos/{equipo.id}", headers=auth_headers_for(admin))
        assert resp.status_code == 400
        assert db.query(Equipo).filter(Equipo.id == equipo.id).first() is not None


# ---------------------------------------------------------------------------
# Global ("U") team — implicit membership, mutations rejected
# ---------------------------------------------------------------------------


class TestEquipoGlobalRechazaMutaciones:
    def test_listar_miembros_global_rechazado(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "global_list", rol_ventas.id)
        db.commit()

        resp = client.get(f"/api/equipos/{equipo_global.id}/miembros", headers=auth_headers_for(user))
        assert resp.status_code == 400

    def test_agregar_miembro_global_rechazado(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "global_add", rol_ventas.id)
        otro = _make_usuario(db, "global_add_target", rol_ventas.id)
        db.commit()

        resp = client.post(
            f"/api/equipos/{equipo_global.id}/miembros",
            json={"usuario_id": otro.id},
            headers=auth_headers_for(user),
        )
        assert resp.status_code == 400

    def test_eliminar_miembro_global_rechazado(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "global_remove", rol_ventas.id)
        db.commit()

        resp = client.delete(f"/api/equipos/{equipo_global.id}/miembros/{user.id}", headers=auth_headers_for(user))
        assert resp.status_code == 400

    def test_renombrar_global_rechazado(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "global_rename", rol_ventas.id)
        db.commit()

        resp = client.patch(f"/api/equipos/{equipo_global.id}", json={"nombre": "Nuevo"}, headers=auth_headers_for(user))
        assert resp.status_code == 400

    def test_eliminar_global_rechazado(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "global_delete", rol_ventas.id)
        db.commit()

        resp = client.delete(f"/api/equipos/{equipo_global.id}", headers=auth_headers_for(user))
        assert resp.status_code == 400
