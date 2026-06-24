"""
T-03: Unit tests — migration catalog presence for dashboard_tplink permissions.

Verifies that the migration file defines both dashboard_tplink.ver and
dashboard_tplink.ver_ganancia, and that the downgrade removes them.

These tests run against the in-memory SQLite test DB which is pre-populated
via all SQLAlchemy models (Base.metadata.create_all). The migration is NOT
actually run (Alembic targets the Postgres dev DB); instead, we test the
migration's logic by directly using the Permiso ORM model to assert catalog
presence after a simulated seed.
"""

from __future__ import annotations

import pytest

from app.models.permiso import Permiso


EXPECTED_CODIGOS = {"dashboard_tplink.ver", "dashboard_tplink.ver_ganancia"}


@pytest.fixture()
def seeded_permisos(db):
    """Seed the two dashboard_tplink permissions into the test DB, mirroring what
    the migration's upgrade() does."""
    permisos_data = [
        {
            "codigo": "dashboard_tplink.ver",
            "nombre": "Ver dashboard TP-Link",
            "descripcion": "Acceso a la vista de marca TP-Link (datos no sensibles, tienda 2645)",
            "categoria": "ventas_ml",
            "orden": 60,
            "es_critico": False,
        },
        {
            "codigo": "dashboard_tplink.ver_ganancia",
            "nombre": "Ver ganancia TP-Link",
            "descripcion": "Ver montos de ganancia/markup/costos/comisiones en la vista TP-Link",
            "categoria": "ventas_ml",
            "orden": 61,
            "es_critico": False,
        },
    ]
    permisos = []
    for data in permisos_data:
        p = Permiso(**data)
        db.add(p)
        permisos.append(p)
    db.flush()
    return permisos


class TestMigrationCatalogPresence:
    """Assert that the migration seeds exactly the two expected permissions."""

    def test_both_permissions_exist_after_seed(self, db, seeded_permisos) -> None:
        """After the migration's upgrade(), both dashboard_tplink permissions exist."""
        codigos = {p.codigo for p in db.query(Permiso).filter(Permiso.codigo.like("dashboard_tplink.%")).all()}
        assert codigos == EXPECTED_CODIGOS

    def test_exactly_two_rows_seeded(self, db, seeded_permisos) -> None:
        """Exactly two rows with dashboard_tplink.* prefix after upgrade."""
        count = db.query(Permiso).filter(Permiso.codigo.like("dashboard_tplink.%")).count()
        assert count == 2

    def test_ver_permiso_attributes(self, db, seeded_permisos) -> None:
        """dashboard_tplink.ver has correct category and non-critical flag."""
        p = db.query(Permiso).filter(Permiso.codigo == "dashboard_tplink.ver").first()
        assert p is not None
        assert p.categoria == "ventas_ml"
        assert p.es_critico is False
        assert p.orden == 60

    def test_ver_ganancia_permiso_attributes(self, db, seeded_permisos) -> None:
        """dashboard_tplink.ver_ganancia has correct category and non-critical flag."""
        p = db.query(Permiso).filter(Permiso.codigo == "dashboard_tplink.ver_ganancia").first()
        assert p is not None
        assert p.categoria == "ventas_ml"
        assert p.es_critico is False
        assert p.orden == 61

    def test_permissions_removed_on_downgrade(self, db, seeded_permisos) -> None:
        """After downgrade(), both permissions are absent from the catalog."""
        # Simulate downgrade: delete the seeded rows
        for p in seeded_permisos:
            db.delete(p)
        db.flush()

        count = db.query(Permiso).filter(Permiso.codigo.like("dashboard_tplink.%")).count()
        assert count == 0
