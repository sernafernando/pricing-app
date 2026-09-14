"""RED/GREEN -- "% de varios" versioned CRUD (ml-ventas-modo-logistico,
PR5, obs #2064 decision). Mirrors `pricing_constants`'s date-range PATTERN,
not its row -- see `app/models/varios_venta_pct.py`'s docstring.

Calls the endpoint functions directly (bypassing HTTP/auth) -- the
permission gate itself is `require_role`, already covered elsewhere in
this codebase's auth test suite.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.api.endpoints import configuracion
from app.models.usuario import Usuario
from app.models.varios_venta_pct import VariosVentaPct


@pytest.fixture()
def admin(db) -> Usuario:
    user = Usuario(nombre="Admin", username="admin_varios_test")
    db.add(user)
    db.flush()
    return user


class TestCrearVariosVentaPct:
    def test_first_version_created(self, db, admin) -> None:
        payload = configuracion.VariosVentaPctCreate(porcentaje=2.5, fecha_desde=date(2026, 1, 1))

        result = configuracion.crear_varios_venta_pct(payload, db=db, current_user=admin)

        assert "id" in result
        row = db.query(VariosVentaPct).filter(VariosVentaPct.id == result["id"]).first()
        assert row.porcentaje == 2.5
        assert row.fecha_hasta is None

    def test_new_version_closes_the_previous_one(self, db, admin) -> None:
        """Same rule `pricing_constants` already applies (task: the
        endpoint closes the previous version when a new one is created)."""
        first = configuracion.crear_varios_venta_pct(
            configuracion.VariosVentaPctCreate(porcentaje=2.0, fecha_desde=date(2026, 1, 1)),
            db=db,
            current_user=admin,
        )
        configuracion.crear_varios_venta_pct(
            configuracion.VariosVentaPctCreate(porcentaje=3.0, fecha_desde=date(2026, 6, 1)),
            db=db,
            current_user=admin,
        )

        primera = db.query(VariosVentaPct).filter(VariosVentaPct.id == first["id"]).first()
        assert primera.fecha_hasta == date(2026, 6, 1)

    def test_duplicate_fecha_desde_is_rejected(self, db, admin) -> None:
        configuracion.crear_varios_venta_pct(
            configuracion.VariosVentaPctCreate(porcentaje=2.0, fecha_desde=date(2026, 1, 1)),
            db=db,
            current_user=admin,
        )

        with pytest.raises(HTTPException) as exc_info:
            configuracion.crear_varios_venta_pct(
                configuracion.VariosVentaPctCreate(porcentaje=5.0, fecha_desde=date(2026, 1, 1)),
                db=db,
                current_user=admin,
            )
        assert exc_info.value.status_code == 400


class TestObtenerVariosVentaPctActual:
    def test_returns_the_version_in_force_today(self, db, admin) -> None:
        db.add(VariosVentaPct(porcentaje=2.5, fecha_desde=date(2020, 1, 1), fecha_hasta=None))
        db.commit()

        result = configuracion.obtener_varios_venta_pct_actual(db=db, current_user=admin)

        assert float(result.porcentaje) == 2.5

    def test_no_version_configured_is_404(self, db, admin) -> None:
        with pytest.raises(HTTPException) as exc_info:
            configuracion.obtener_varios_venta_pct_actual(db=db, current_user=admin)
        assert exc_info.value.status_code == 404
