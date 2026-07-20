"""
Unit tests — equipo-scoped color write endpoints (PR2 of productos-color-teams).

Verifies:
- `puede_escribir_layer` matrix (membership vs. global-permiso rule).
- The single PATCH endpoints (/color, /color-tienda): default-to-global
  behavior, legacy dual-write for the global layer, team-scoped writes
  leaving legacy untouched, and 403 for non-members.
- Backward compatibility: existing request shape (no equipo_id) still works.
- Batch endpoints (`actualizar-color-lote`, `actualizar-color-tienda-lote`):
  happy path for a member / global-with-permiso, and — the RED-first
  security regression — a non-member/non-permiso caller gets 403 and causes
  ZERO writes (this closes a real gap: the pre-PR2 batch endpoints ignored
  `current_user` entirely).
"""

from __future__ import annotations

import pytest

from app.api.endpoints.productos_shared import puede_escribir_layer
from app.models.equipo import Equipo, EquipoMiembro, ProductoColor, RolEquipo
from app.models.permiso import Permiso, RolPermisoBase
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.core.security import get_password_hash
from fastapi import HTTPException


PERMISO_MARCAR_COLOR = "productos.marcar_color"


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


def _make_producto(db, item_id: int) -> ProductoERP:
    producto = ProductoERP(item_id=item_id, codigo=f"COD{item_id}", descripcion="Producto de prueba")
    db.add(producto)
    db.flush()
    return producto


def _grant_marcar_color(db, rol_id: int) -> Permiso:
    permiso = db.query(Permiso).filter(Permiso.codigo == PERMISO_MARCAR_COLOR).first()
    if permiso is None:
        permiso = Permiso(
            codigo=PERMISO_MARCAR_COLOR,
            nombre="Marcar color",
            categoria="productos",
        )
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_id, permiso_id=permiso.id))
    db.flush()
    return permiso


def _make_equipo(db, nombre: str, es_global: bool = False) -> Equipo:
    equipo = Equipo(nombre=nombre, es_global=es_global)
    db.add(equipo)
    db.flush()
    return equipo


def _add_member(db, equipo_id: int, usuario_id: int, rol: RolEquipo = RolEquipo.MIEMBRO) -> EquipoMiembro:
    miembro = EquipoMiembro(equipo_id=equipo_id, usuario_id=usuario_id, rol=rol)
    db.add(miembro)
    db.flush()
    return miembro


def _global_equipo(db) -> Equipo:
    """Some other test module (equipo migration/model tests) may not seed the
    singleton global equipo since PR2 endpoints require it to exist. Create it
    on demand, matching what the PR1 migration guarantees in real DBs."""
    equipo = db.query(Equipo).filter(Equipo.es_global.is_(True)).first()
    if equipo is None:
        equipo = _make_equipo(db, "Global", es_global=True)
    return equipo


def auth_headers_for(user: Usuario) -> dict:
    from tests.conftest import make_access_token

    token = make_access_token(user)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# puede_escribir_layer matrix
# ---------------------------------------------------------------------------


class TestPuedeEscribirLayer:
    def test_member_of_team_can_write(self, db, rol_ventas) -> None:
        equipo = _make_equipo(db, "Equipo A")
        user = _make_usuario(db, "member_a", rol_ventas.id)
        _add_member(db, equipo.id, user.id)

        puede_escribir_layer(db, user, equipo.id)  # no raise

    def test_non_member_of_team_forbidden(self, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo B")
        user = _make_usuario(db, "outsider", rol_ventas.id)

        with pytest.raises(HTTPException) as exc:
            puede_escribir_layer(db, user, equipo.id)
        assert exc.value.status_code == 403

    def test_global_with_permiso_can_write(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _grant_marcar_color(db, rol_ventas.id)
        user = _make_usuario(db, "global_ok", rol_ventas.id)

        puede_escribir_layer(db, user, equipo_global.id)  # no raise

    def test_global_without_permiso_forbidden(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "global_no_permiso", rol_ventas.id)

        with pytest.raises(HTTPException) as exc:
            puede_escribir_layer(db, user, equipo_global.id)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Single PATCH endpoints
# ---------------------------------------------------------------------------


class TestPatchColorSingle:
    def test_default_no_equipo_id_writes_global_and_mirrors_legacy(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _grant_marcar_color(db, rol_ventas.id)
        user = _make_usuario(db, "u1", rol_ventas.id)
        _make_producto(db, 111)
        db.commit()

        resp = client.patch("/api/productos/111/color", json={"color": "rojo"}, headers=auth_headers_for(user))
        assert resp.status_code == 200

        row = (
            db.query(ProductoColor)
            .filter(ProductoColor.equipo_id == equipo_global.id, ProductoColor.item_id == 111)
            .first()
        )
        assert row is not None
        assert row.color_ml == "rojo"

        pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == 111).first()
        assert pricing is not None
        assert pricing.color_marcado == "rojo"

    def test_color_tienda_default_mirrors_legacy(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _grant_marcar_color(db, rol_ventas.id)
        user = _make_usuario(db, "u2", rol_ventas.id)
        _make_producto(db, 112)
        db.commit()

        resp = client.patch("/api/productos/112/color-tienda", json={"color": "verde"}, headers=auth_headers_for(user))
        assert resp.status_code == 200

        row = (
            db.query(ProductoColor)
            .filter(ProductoColor.equipo_id == equipo_global.id, ProductoColor.item_id == 112)
            .first()
        )
        assert row is not None
        assert row.color_tienda == "verde"

        pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == 112).first()
        assert pricing is not None
        assert pricing.color_marcado_tienda == "verde"

    def test_explicit_team_writes_producto_color_only_legacy_untouched(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo C")
        user = _make_usuario(db, "member_c", rol_ventas.id)
        _add_member(db, equipo.id, user.id)
        _make_producto(db, 113)
        db.commit()

        resp = client.patch(
            f"/api/productos/113/color?equipo_id={equipo.id}",
            json={"color": "azul"},
            headers=auth_headers_for(user),
        )
        assert resp.status_code == 200

        row = db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo.id, ProductoColor.item_id == 113).first()
        assert row is not None
        assert row.color_ml == "azul"

        pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == 113).first()
        assert pricing is None  # legacy untouched for non-global teams

    def test_non_member_forbidden(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo D")
        user = _make_usuario(db, "outsider_d", rol_ventas.id)
        _make_producto(db, 114)
        db.commit()

        resp = client.patch(
            f"/api/productos/114/color?equipo_id={equipo.id}",
            json={"color": "azul"},
            headers=auth_headers_for(user),
        )
        assert resp.status_code == 403

        row = db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo.id, ProductoColor.item_id == 114).first()
        assert row is None

    def test_backward_compat_no_equipo_id_body_only(self, client, db, rol_ventas) -> None:
        """Existing frontend shape: PATCH body {color}, no equipo_id query param."""
        _global_equipo(db)
        _grant_marcar_color(db, rol_ventas.id)
        user = _make_usuario(db, "legacy_caller", rol_ventas.id)
        _make_producto(db, 115)
        db.commit()

        resp = client.patch("/api/productos/115/color", json={"color": "gris"}, headers=auth_headers_for(user))
        assert resp.status_code == 200
        assert resp.json()["color_nuevo"] == "gris"


# ---------------------------------------------------------------------------
# Batch endpoints — RED-first security regression + happy paths
# ---------------------------------------------------------------------------


class TestBatchColorSecurity:
    """Pre-PR2, these two endpoints ignored `current_user` entirely (zero
    permission check). These tests encode the closed gap: a caller with
    neither team membership nor the global permiso must be rejected and
    must cause ZERO writes.
    """

    def test_lote_ml_forbidden_for_outsider_and_writes_nothing(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo E")
        outsider = _make_usuario(db, "outsider_e", rol_ventas.id)
        _make_producto(db, 201)
        _make_producto(db, 202)
        db.commit()

        resp = client.post(
            "/api/productos/actualizar-color-lote",
            json={"item_ids": [201, 202], "color": "rojo", "equipo_id": equipo.id},
            headers=auth_headers_for(outsider),
        )
        assert resp.status_code == 403

        assert db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo.id).count() == 0

    def test_lote_ml_forbidden_default_global_without_permiso(self, client, db, rol_ventas) -> None:
        """Same gap, but hitting the default (no equipo_id -> global) path."""
        _global_equipo(db)
        outsider = _make_usuario(db, "outsider_f", rol_ventas.id)
        _make_producto(db, 203)
        db.commit()

        resp = client.post(
            "/api/productos/actualizar-color-lote",
            json={"item_ids": [203], "color": "rojo"},
            headers=auth_headers_for(outsider),
        )
        assert resp.status_code == 403

        pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == 203).first()
        assert pricing is None

    def test_lote_tienda_forbidden_for_outsider_and_writes_nothing(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo G")
        outsider = _make_usuario(db, "outsider_g", rol_ventas.id)
        _make_producto(db, 204)
        db.commit()

        resp = client.post(
            "/api/productos/actualizar-color-tienda-lote",
            json={"item_ids": [204], "color": "rojo", "equipo_id": equipo.id},
            headers=auth_headers_for(outsider),
        )
        assert resp.status_code == 403

        assert db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo.id).count() == 0

    def test_lote_ml_happy_path_member(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo H")
        member = _make_usuario(db, "member_h", rol_ventas.id)
        _add_member(db, equipo.id, member.id)
        _make_producto(db, 205)
        _make_producto(db, 206)
        db.commit()

        resp = client.post(
            "/api/productos/actualizar-color-lote",
            json={"item_ids": [205, 206], "color": "naranja", "equipo_id": equipo.id},
            headers=auth_headers_for(member),
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

        rows = db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo.id).all()
        assert {r.item_id for r in rows} == {205, 206}
        assert all(r.color_ml == "naranja" for r in rows)

    def test_lote_ml_happy_path_global_with_permiso_dual_writes_legacy(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _grant_marcar_color(db, rol_ventas.id)
        user = _make_usuario(db, "global_batch", rol_ventas.id)
        _make_producto(db, 207)
        db.commit()

        resp = client.post(
            "/api/productos/actualizar-color-lote",
            json={"item_ids": [207], "color": "amarillo"},
            headers=auth_headers_for(user),
        )
        assert resp.status_code == 200

        row = (
            db.query(ProductoColor)
            .filter(ProductoColor.equipo_id == equipo_global.id, ProductoColor.item_id == 207)
            .first()
        )
        assert row is not None and row.color_ml == "amarillo"

        pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == 207).first()
        assert pricing is not None and pricing.color_marcado == "amarillo"

    def test_lote_tienda_happy_path_member(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo I")
        member = _make_usuario(db, "member_i", rol_ventas.id)
        _add_member(db, equipo.id, member.id)
        _make_producto(db, 208)
        db.commit()

        resp = client.post(
            "/api/productos/actualizar-color-tienda-lote",
            json={"item_ids": [208], "color": "purpura", "equipo_id": equipo.id},
            headers=auth_headers_for(member),
        )
        assert resp.status_code == 200

        row = db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo.id, ProductoColor.item_id == 208).first()
        assert row is not None and row.color_tienda == "purpura"
