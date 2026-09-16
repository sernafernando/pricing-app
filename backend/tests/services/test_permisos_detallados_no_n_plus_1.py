"""`obtener_permisos_detallados_usuario` must not issue one query per override.

The admin permissions panel refetches this for the selected user after every single
toggle. Reading `override.permiso.codigo` off a bare `join(Permiso)` does not populate
the relationship, so each override triggered its own lazy-load SELECT. Bounded, but it
grows with the number of overrides on the user and it is pure waste.
"""

from __future__ import annotations

from sqlalchemy import event

from app.core.security import get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import RolUsuario, Usuario
from app.services.permisos_service import PermisosService


def _seed_user_with_overrides(db, n_overrides: int, username: str) -> Usuario:
    rol = Rol(codigo=f"ROL_{username}", nombre=f"ROL_{username}")
    db.add(rol)
    db.flush()

    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
    )
    db.add(user)
    db.flush()

    for i in range(n_overrides):
        permiso = Permiso(codigo=f"{username}.p{i}", nombre=f"p{i}", categoria="pxq")
        db.add(permiso)
        db.flush()
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=permiso.id, concedido=True))
    db.flush()
    return user


def _count_selects(db, fn) -> int:
    seen = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    event.listen(db.bind, "before_cursor_execute", before_cursor_execute)
    try:
        fn()
    finally:
        event.remove(db.bind, "before_cursor_execute", before_cursor_execute)
    return len(seen)


def test_query_count_does_not_grow_with_number_of_overrides(db):
    few = _seed_user_with_overrides(db, n_overrides=1, username="pocos")
    many = _seed_user_with_overrides(db, n_overrides=12, username="muchos")
    db.commit()

    service = PermisosService(db)

    db.expire_all()
    queries_few = _count_selects(db, lambda: service.obtener_permisos_detallados_usuario(few))
    db.expire_all()
    queries_many = _count_selects(db, lambda: service.obtener_permisos_detallados_usuario(many))

    assert queries_few == queries_many, (
        f"N+1: {queries_few} queries con 1 override vs {queries_many} con 12 "
        "— la relación `permiso` se está cargando de a una"
    )


def test_detallados_still_reports_overrides(db):
    user = _seed_user_with_overrides(db, n_overrides=2, username="contenido")
    db.commit()

    resultado = PermisosService(db).obtener_permisos_detallados_usuario(user)

    entradas = {p["codigo"]: p for permisos in resultado.values() for p in permisos}
    assert entradas["contenido.p0"]["override"] is True
    assert entradas["contenido.p0"]["origen"] == "override_agregado"
    assert entradas["contenido.p0"]["efectivo"] is True
