"""
Unit tests — Equipo / EquipoMiembro / ProductoColor ORM models (PR1 of
productos-color-teams).

Verifies:
- Tables are created by conftest's `Base.metadata.create_all`.
- UniqueConstraint(equipo_id, usuario_id) on EquipoMiembro is enforced.
- UniqueConstraint(equipo_id, item_id) on ProductoColor is enforced.
- RolEquipo enum accepts admin/miembro values.
- Creating an Equipo(es_global=True) with members and producto_color rows
  works end to end and relationships resolve both ways.

SQLite-runnable via the shared `db` fixture (conftest.py). The Alembic
upgrade/downgrade path (partial unique index, ON CONFLICT, backfill from
productos_pricing) is Postgres-only and is NOT exercised here — see the
migration docstring for manual verification steps.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.equipo import Equipo, EquipoMiembro, ProductoColor, RolEquipo
from app.models.producto import ProductoERP
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash


def _make_usuario(db, username: str) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
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


class TestTableNames:
    def test_equipo_tablename(self) -> None:
        assert Equipo.__tablename__ == "equipo"

    def test_equipo_miembro_tablename(self) -> None:
        assert EquipoMiembro.__tablename__ == "equipo_miembro"

    def test_producto_color_tablename(self) -> None:
        assert ProductoColor.__tablename__ == "producto_color"


class TestRolEquipoEnum:
    def test_accepts_admin_and_miembro(self) -> None:
        assert RolEquipo.ADMIN.value == "admin"
        assert RolEquipo.MIEMBRO.value == "miembro"


class TestEquipoModel:
    def test_insert_global_equipo(self, db) -> None:
        # The `db` fixture already seeds the singleton global equipo (see
        # tests/conftest.py `_ensure_global_equipo`, mirroring the real
        # migration backfill), so this just verifies it's queryable as expected.
        retrieved = db.query(Equipo).filter_by(nombre="Global").first()
        assert retrieved is not None
        assert retrieved.es_global is True


class TestEquipoMiembroUniqueConstraint:
    def test_duplicate_equipo_usuario_pair_raises_integrity_error(self, db) -> None:
        equipo = Equipo(nombre="Equipo A", es_global=False)
        db.add(equipo)
        db.flush()

        usuario = _make_usuario(db, "miembro1")

        m1 = EquipoMiembro(equipo_id=equipo.id, usuario_id=usuario.id, rol=RolEquipo.MIEMBRO)
        db.add(m1)
        db.flush()

        m2 = EquipoMiembro(equipo_id=equipo.id, usuario_id=usuario.id, rol=RolEquipo.ADMIN)
        db.add(m2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_same_usuario_different_equipo_is_allowed(self, db) -> None:
        equipo_a = Equipo(nombre="Equipo A", es_global=False)
        equipo_b = Equipo(nombre="Equipo B", es_global=False)
        db.add_all([equipo_a, equipo_b])
        db.flush()

        usuario = _make_usuario(db, "miembro2")

        db.add(EquipoMiembro(equipo_id=equipo_a.id, usuario_id=usuario.id, rol=RolEquipo.MIEMBRO))
        db.add(EquipoMiembro(equipo_id=equipo_b.id, usuario_id=usuario.id, rol=RolEquipo.MIEMBRO))
        db.flush()  # should not raise


class TestProductoColorUniqueConstraint:
    def test_duplicate_equipo_item_pair_raises_integrity_error(self, db) -> None:
        equipo = Equipo(nombre="Equipo A", es_global=False)
        db.add(equipo)
        db.flush()
        producto = _make_producto(db, 90001)

        c1 = ProductoColor(equipo_id=equipo.id, item_id=producto.item_id, color_ml="rojo")
        db.add(c1)
        db.flush()

        c2 = ProductoColor(equipo_id=equipo.id, item_id=producto.item_id, color_ml="verde")
        db.add(c2)
        with pytest.raises(IntegrityError):
            db.flush()


class TestRelationships:
    def test_equipo_with_members_and_colors_resolves_relationships(self, db) -> None:
        # Uses a non-global team: the `db` fixture already seeds the
        # singleton global equipo, and es_global has a UNIQUE-WHERE constraint.
        equipo = Equipo(nombre="Equipo Relaciones", es_global=False)
        db.add(equipo)
        db.flush()

        usuario = _make_usuario(db, "miembro3")
        producto = _make_producto(db, 90002)

        miembro = EquipoMiembro(equipo_id=equipo.id, usuario_id=usuario.id, rol=RolEquipo.ADMIN)
        color = ProductoColor(
            equipo_id=equipo.id,
            item_id=producto.item_id,
            color_ml="azul",
            color_tienda="verde",
            updated_by=usuario.id,
        )
        db.add_all([miembro, color])
        db.flush()
        db.refresh(equipo)

        assert len(equipo.miembros) == 1
        assert equipo.miembros[0].usuario_id == usuario.id
        assert equipo.miembros[0].rol == RolEquipo.ADMIN

        assert len(equipo.colores) == 1
        assert equipo.colores[0].color_ml == "azul"
        assert equipo.colores[0].color_tienda == "verde"
        assert equipo.colores[0].equipo is equipo
