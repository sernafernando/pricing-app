"""Regression test: dashboard_ml.py's pm_ids override must be role-gated
identically to rentabilidad_shared.py (sub-pm-scope-marcas PR1, D2).

Before the fix, dashboard_ml.aplicar_filtro_marcas_pm honored an explicit
pm_ids param for ANY caller, letting a non-privileged user view another
user's PM-scoped metrics. After rewiring both sites to the shared
app.services.pm_scope.aplicar_filtro_marcas_pm, the gate is unified.
"""

from __future__ import annotations

from app.api.endpoints import dashboard_ml
from app.api.endpoints import rentabilidad_shared
from app.core.security import get_password_hash
from app.models.marca_pm import MarcaPM
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _make_user(db, rol_ventas, username: str, rol=RolUsuario.VENTAS) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=rol,
        rol_id=rol_ventas.id if rol == RolUsuario.VENTAS else None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def test_dashboard_ml_pm_ids_is_same_function_object_as_pm_scope() -> None:
    """Both modules must import (not re-implement) the shared resolver."""
    from app.services.pm_scope import aplicar_filtro_marcas_pm as shared_fn

    assert dashboard_ml.aplicar_filtro_marcas_pm is shared_fn
    assert rentabilidad_shared.aplicar_filtro_marcas_pm is shared_fn


def test_dashboard_ml_non_privileged_pm_ids_rejected_like_rentabilidad(db, rol_ventas) -> None:
    caller = _make_user(db, rol_ventas, "dash_gate_caller")
    other = _make_user(db, rol_ventas, "dash_gate_other")
    db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=other.id))
    db.flush()

    dash_query = dashboard_ml.aplicar_filtro_marcas_pm(db.query(MLVentaMetrica), caller, db, pm_ids=str(other.id))
    rent_query = rentabilidad_shared.aplicar_filtro_marcas_pm(
        db.query(MLVentaMetrica), caller, db, pm_ids=str(other.id)
    )

    # Both must fall back to caller's own (empty) scope — the __NINGUNA__ sentinel —
    # identical behavior between the two sites.
    assert dash_query.all() == []
    assert rent_query.all() == []
    dash_sql = str(dash_query.statement.compile(compile_kwargs={"literal_binds": True}))
    rent_sql = str(rent_query.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "NINGUNA" in dash_sql
    assert "NINGUNA" in rent_sql
    assert dash_sql == rent_sql
