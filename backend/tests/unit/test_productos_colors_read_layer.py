"""
Unit tests — read-side color layer refactor (PR3 of productos-color-teams).

Verifies:
- `resolver_layer_activo`: None -> U, explicit U allowed, team member allowed,
  non-member forbidden (403).
- `filtro_colores` parity on both slots (ml/tienda), including the
  `sin_color` sentinel — behavior-identical to the legacy
  `productos_pricing.color_marcado[_tienda]` filter.
- Listing endpoint (`GET /api/productos`) parity: default (no equipo_id)
  reads/filters equal today's legacy-column behavior, since producto_color@U
  is kept in sync with legacy by the PR2 dual-write.
- Read-scoping: a team member requesting `equipo_id=T` sees the team color +
  `color_hint_global`; the default request sees the U (global) color.
- Hint fields present in the listing payload with correct values, including
  `color_hint_equipo_inicial`.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints.productos_shared import (
    color_slot,
    filtro_colores,
    resolver_layer_activo,
)
from app.models.equipo import Equipo, EquipoMiembro, ProductoColor
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.core.security import get_password_hash


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


def _make_producto(db, item_id: int, **kwargs) -> ProductoERP:
    kwargs.setdefault("costo", 100.0)
    kwargs.setdefault("iva", 21.0)
    producto = ProductoERP(
        item_id=item_id,
        codigo=f"COD{item_id}",
        descripcion=kwargs.pop("descripcion", "Producto de prueba"),
        **kwargs,
    )
    db.add(producto)
    db.flush()
    return producto


def _make_equipo(db, nombre: str, es_global: bool = False) -> Equipo:
    equipo = Equipo(nombre=nombre, es_global=es_global)
    db.add(equipo)
    db.flush()
    return equipo


def _add_member(db, equipo_id: int, usuario_id: int) -> EquipoMiembro:
    miembro = EquipoMiembro(equipo_id=equipo_id, usuario_id=usuario_id, rol="miembro")
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


def _set_legacy_color(db, item_id: int, color: str | None = None, color_tienda: str | None = None) -> None:
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    if pricing is None:
        pricing = ProductoPricing(item_id=item_id)
        db.add(pricing)
    if color is not None:
        pricing.color_marcado = color
    if color_tienda is not None:
        pricing.color_marcado_tienda = color_tienda


def _set_producto_color(
    db, equipo_id: int, item_id: int, color_ml: str | None = None, color_tienda: str | None = None
) -> ProductoColor:
    row = db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo_id, ProductoColor.item_id == item_id).first()
    if row is None:
        row = ProductoColor(equipo_id=equipo_id, item_id=item_id)
        db.add(row)
    if color_ml is not None:
        row.color_ml = color_ml
    if color_tienda is not None:
        row.color_tienda = color_tienda
    db.flush()
    return row


# ---------------------------------------------------------------------------
# resolver_layer_activo
# ---------------------------------------------------------------------------


class TestResolverLayerActivo:
    def test_none_resolves_to_global(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "r1", rol_ventas.id)

        assert resolver_layer_activo(None, user, db) == equipo_global.id

    def test_explicit_global_allowed(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "r2", rol_ventas.id)

        assert resolver_layer_activo(equipo_global.id, user, db) == equipo_global.id

    def test_member_of_team_allowed(self, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo R")
        user = _make_usuario(db, "r3", rol_ventas.id)
        _add_member(db, equipo.id, user.id)

        assert resolver_layer_activo(equipo.id, user, db) == equipo.id

    def test_non_member_forbidden(self, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo S")
        user = _make_usuario(db, "r4", rol_ventas.id)

        with pytest.raises(HTTPException) as exc:
            resolver_layer_activo(equipo.id, user, db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# filtro_colores parity (unit-level, direct query building)
# ---------------------------------------------------------------------------


class TestFiltroColoresParity:
    def _query(self, db):
        return db.query(ProductoERP, ProductoPricing).outerjoin(
            ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
        )

    def test_ml_slot_specific_colors(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _make_producto(db, 301)
        _make_producto(db, 302)
        _set_producto_color(db, equipo_global.id, 301, color_ml="rojo")
        _set_producto_color(db, equipo_global.id, 302, color_ml="verde")
        db.commit()

        from app.api.endpoints.productos_shared import join_color_layer

        query = join_color_layer(self._query(db), equipo_global.id)
        query = filtro_colores(query, "rojo", color_slot(None))
        results = query.all()

        assert {p.item_id for p, _ in results} == {301}

    def test_ml_slot_sin_color_sentinel(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _make_producto(db, 303)
        _make_producto(db, 304)
        _set_producto_color(db, equipo_global.id, 303, color_ml="rojo")
        # 304 has no ProductoColor row -> outerjoin gives NULL -> matches sin_color
        db.commit()

        from app.api.endpoints.productos_shared import join_color_layer

        query = join_color_layer(self._query(db), equipo_global.id)
        query = filtro_colores(query, "sin_color", color_slot(None))
        results = query.all()

        assert {p.item_id for p, _ in results} == {304}

    def test_ml_slot_sin_color_plus_specific(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _make_producto(db, 305)
        _make_producto(db, 306)
        _make_producto(db, 307)
        _set_producto_color(db, equipo_global.id, 305, color_ml="rojo")
        _set_producto_color(db, equipo_global.id, 306, color_ml="verde")
        # 307: no color
        db.commit()

        from app.api.endpoints.productos_shared import join_color_layer

        query = join_color_layer(self._query(db), equipo_global.id)
        query = filtro_colores(query, "sin_color,rojo", color_slot(None))
        results = query.all()

        assert {p.item_id for p, _ in results} == {305, 307}

    def test_tienda_slot(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _make_producto(db, 308)
        _make_producto(db, 309)
        _set_producto_color(db, equipo_global.id, 308, color_tienda="azul")
        _set_producto_color(db, equipo_global.id, 309, color_tienda="gris")
        db.commit()

        from app.api.endpoints.productos_shared import join_color_layer

        query = join_color_layer(self._query(db), equipo_global.id)
        query = filtro_colores(query, "azul", color_slot("tienda"))
        results = query.all()

        assert {p.item_id for p, _ in results} == {308}

    def test_no_filter_returns_query_unchanged(self, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        _make_producto(db, 310)
        db.commit()

        from app.api.endpoints.productos_shared import join_color_layer

        query = join_color_layer(self._query(db), equipo_global.id)
        query = filtro_colores(query, None, color_slot(None))
        results = query.all()

        assert {p.item_id for p, _ in results} == {310}


# ---------------------------------------------------------------------------
# Listing endpoint parity (default = U layer, must equal today's legacy
# column behavior since producto_color@U is kept in sync by PR2 dual-write)
# ---------------------------------------------------------------------------


class TestListingParityDefaultLayer:
    def test_detail_color_field_matches_legacy_for_default_layer(self, client, db, rol_ventas) -> None:
        """Uses GET /api/productos/{item_id} (single-item detail), which shares
        the same color-layer helpers as the paginated listing endpoints but
        avoids the listing's Tienda Nube batch-fetch raw SQL (`= ANY(:ids)`,
        Postgres-only syntax unsupported by the SQLite test DB)."""
        equipo_global = _global_equipo(db)
        user = _make_usuario(db, "parity1", rol_ventas.id)
        _make_producto(db, 401, stock=5)
        _set_legacy_color(db, 401, color="rojo")
        _set_producto_color(db, equipo_global.id, 401, color_ml="rojo")
        db.commit()

        resp = client.get("/api/productos/401", headers=auth_headers_for(user))
        assert resp.status_code == 200
        item = resp.json()
        assert item["color_marcado"] == "rojo"
        # No team scope requested -> global hint equals the active color.
        assert item["color_hint_global"] == "rojo"
        assert item["color_hint_equipo_inicial"] is None

    def test_listing_filter_by_color_matches_legacy_filter_default_layer(self, db, rol_ventas) -> None:
        """Parity is verified at the query-construction level (same helper the
        `/api/productos` listing endpoint calls): filtro_colores against the
        default (global) layer must select exactly the items whose legacy
        `color_marcado` matched, matching today's behavior. (Full end-to-end
        HTTP coverage of the listing endpoint isn't possible under the SQLite
        test DB — see TestListingParityDefaultLayer docstring above.)"""
        equipo_global = _global_equipo(db)
        _make_producto(db, 402, stock=1)
        _make_producto(db, 403, stock=1)
        _set_legacy_color(db, 402, color="verde")
        _set_producto_color(db, equipo_global.id, 402, color_ml="verde")
        _set_legacy_color(db, 403, color="azul")
        _set_producto_color(db, equipo_global.id, 403, color_ml="azul")
        db.commit()

        from app.api.endpoints.productos_shared import join_color_layer

        query = db.query(ProductoERP, ProductoPricing).outerjoin(
            ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
        )
        query = join_color_layer(query, equipo_global.id)
        query = filtro_colores(query, "verde", color_slot(None))
        item_ids = {p.item_id for p, _ in query.all()}
        assert 402 in item_ids
        assert 403 not in item_ids


# ---------------------------------------------------------------------------
# Read-scoping across teams
# ---------------------------------------------------------------------------


class TestReadScopingAcrossTeams:
    def test_member_sees_team_color_and_global_hint(self, client, db, rol_ventas) -> None:
        equipo_global = _global_equipo(db)
        equipo = _make_equipo(db, "Equipo Ventas")
        user = _make_usuario(db, "scoped1", rol_ventas.id)
        _add_member(db, equipo.id, user.id)
        _make_producto(db, 501, stock=1)
        _set_producto_color(db, equipo.id, 501, color_ml="violeta")
        _set_producto_color(db, equipo_global.id, 501, color_ml="verde")
        db.commit()

        # Requesting the team scope -> sees team color + global hint.
        resp = client.get(f"/api/productos/501?equipo_id={equipo.id}", headers=auth_headers_for(user))
        assert resp.status_code == 200
        item = resp.json()
        assert item["color_marcado"] == "violeta"
        assert item["color_hint_global"] == "verde"
        assert item["color_hint_equipo_inicial"] == "Equipo Ventas"[0]

        # Default request (no equipo_id) -> sees the global color.
        resp_default = client.get("/api/productos/501", headers=auth_headers_for(user))
        assert resp_default.status_code == 200
        assert resp_default.json()["color_marcado"] == "verde"

    def test_non_member_forbidden_via_listing_endpoint(self, client, db, rol_ventas) -> None:
        _global_equipo(db)
        equipo = _make_equipo(db, "Equipo Aislado")
        user = _make_usuario(db, "scoped2", rol_ventas.id)
        db.commit()

        resp = client.get(f"/api/productos?equipo_id={equipo.id}", headers=auth_headers_for(user))
        assert resp.status_code == 403
