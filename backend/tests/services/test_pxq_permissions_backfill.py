"""Tests for `app.services.pxq_permissions_backfill` (PR2, task 16-20).

Spec: dedicated PxQ permission with default grant, derived from LIVE
`promos.escribir` state at migration time — roles AND user overrides
(including negative ones), never a hardcoded role list.
"""

from __future__ import annotations

from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.core.security import get_password_hash
from app.services.pxq_permissions_backfill import (
    PXQ_ESCRIBIR_CODE,
    PXQ_VER_CODE,
    backfill_pxq_permissions_from_promos,
    ensure_pxq_permission_catalog,
)

PROMOS_ESCRIBIR_CODE = "promos.escribir"


def _make_permiso(db, codigo: str) -> Permiso:
    permiso = Permiso(codigo=codigo, nombre=codigo, categoria="pxq")
    db.add(permiso)
    db.flush()
    return permiso


def _make_role(db, codigo: str) -> Rol:
    rol = Rol(codigo=codigo, nombre=codigo)
    db.add(rol)
    db.flush()
    return rol


def _make_user(db, rol: Rol, username: str) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def test_pxq_permission_codes_exist_and_are_distinct_from_promos_escribir(db) -> None:
    ensure_pxq_permission_catalog(db)
    codigos = {p.codigo for p in db.query(Permiso).all()}
    assert PXQ_VER_CODE in codigos
    assert PXQ_ESCRIBIR_CODE in codigos
    assert PXQ_VER_CODE != PROMOS_ESCRIBIR_CODE
    assert PXQ_ESCRIBIR_CODE != PROMOS_ESCRIBIR_CODE


def test_role_holding_promos_escribir_gets_pxq_grants(db) -> None:
    ensure_pxq_permission_catalog(db)
    promos_escribir = _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "ADMIN_PXQ")
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=promos_escribir.id))
    db.flush()

    counts = backfill_pxq_permissions_from_promos(db)

    pxq_ver = db.query(Permiso).filter_by(codigo=PXQ_VER_CODE).first()
    pxq_escribir = db.query(Permiso).filter_by(codigo=PXQ_ESCRIBIR_CODE).first()
    granted_codes = {rp.permiso.codigo for rp in db.query(RolPermisoBase).filter(RolPermisoBase.rol_id == rol.id).all()}
    assert pxq_ver.codigo in granted_codes
    assert pxq_escribir.codigo in granted_codes
    assert counts["roles_granted"] == 1


def test_role_without_promos_escribir_gets_nothing(db) -> None:
    ensure_pxq_permission_catalog(db)
    _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "SIN_PROMOS")
    db.flush()

    backfill_pxq_permissions_from_promos(db)

    granted_codes = {rp.permiso.codigo for rp in db.query(RolPermisoBase).filter(RolPermisoBase.rol_id == rol.id).all()}
    assert PXQ_VER_CODE not in granted_codes
    assert PXQ_ESCRIBIR_CODE not in granted_codes


def test_user_with_positive_override_on_promos_escribir_gets_pxq_grants(db) -> None:
    ensure_pxq_permission_catalog(db)
    promos_escribir = _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "VENTAS_PXQ")
    user = _make_user(db, rol, "override_user")
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=promos_escribir.id, concedido=True))
    db.flush()

    backfill_pxq_permissions_from_promos(db)

    overrides = {
        o.permiso.codigo: o.concedido
        for o in db.query(UsuarioPermisoOverride).filter(UsuarioPermisoOverride.usuario_id == user.id).all()
    }
    assert overrides[PXQ_VER_CODE] is True
    assert overrides[PXQ_ESCRIBIR_CODE] is True


def test_user_with_negative_override_on_promos_escribir_does_not_get_pxq_escribir(db) -> None:
    """A user explicitly revoked from promos.escribir (concedido=false)
    must NOT receive pxq.escribir via backfill — negative overrides are
    copied, not ignored."""
    ensure_pxq_permission_catalog(db)
    promos_escribir = _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "REVOKED_PXQ")
    # Role grants promos.escribir by default...
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=promos_escribir.id))
    user = _make_user(db, rol, "revoked_user")
    # ...but this user has an explicit negative override.
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=promos_escribir.id, concedido=False))
    db.flush()

    backfill_pxq_permissions_from_promos(db)

    pxq_escribir = db.query(Permiso).filter_by(codigo=PXQ_ESCRIBIR_CODE).first()
    negative_override = (
        db.query(UsuarioPermisoOverride)
        .filter(
            UsuarioPermisoOverride.usuario_id == user.id,
            UsuarioPermisoOverride.permiso_id == pxq_escribir.id,
        )
        .first()
    )
    assert negative_override is not None
    assert negative_override.concedido is False


def test_user_without_any_promos_write_grant_gets_no_pxq_permissions(db) -> None:
    ensure_pxq_permission_catalog(db)
    _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "PLAIN_ROLE")
    user = _make_user(db, rol, "plain_user")
    db.flush()

    backfill_pxq_permissions_from_promos(db)

    overrides = db.query(UsuarioPermisoOverride).filter(UsuarioPermisoOverride.usuario_id == user.id).all()
    assert overrides == []


def test_dry_run_reports_counts_without_writing_anything(db) -> None:
    ensure_pxq_permission_catalog(db)
    promos_escribir = _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "DRY_RUN_ROLE")
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=promos_escribir.id))
    user = _make_user(db, rol, "dry_run_user")
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=promos_escribir.id, concedido=False))
    db.flush()

    counts = backfill_pxq_permissions_from_promos(db, dry_run=True)

    assert counts["roles_granted"] == 1
    assert counts["negative_overrides_copied"] == 1
    # Nothing actually written.
    assert db.query(RolPermisoBase).filter(RolPermisoBase.rol_id == rol.id).count() == 1
    assert db.query(UsuarioPermisoOverride).filter(UsuarioPermisoOverride.usuario_id == user.id).count() == 1


def test_dry_run_does_not_count_roles_that_already_hold_pxq(db) -> None:
    """The dry-run count is the mandatory pre-deploy gate (task 2c.20) and gets
    recorded in the PR description, so it has to be exact. Counting every
    promos.escribir grant regardless of whether PxQ is already present inflates
    the number on any re-run — and a re-run is exactly when someone would look
    at it to decide whether the migration is safe to apply again."""
    ensure_pxq_permission_catalog(db)
    promos_escribir = _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "ALREADY_GRANTED_ROLE")
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=promos_escribir.id))
    pxq_permisos = db.query(Permiso).filter(Permiso.codigo.in_([PXQ_VER_CODE, PXQ_ESCRIBIR_CODE])).all()
    assert len(pxq_permisos) == 2
    for permiso in pxq_permisos:
        db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()

    counts = backfill_pxq_permissions_from_promos(db, dry_run=True)

    assert counts["roles_granted"] == 0


def test_dry_run_count_matches_what_a_real_run_writes(db) -> None:
    """A dry-run whose number does not equal the real run's effect is worse than
    no dry-run: it is a number someone trusts."""
    ensure_pxq_permission_catalog(db)
    promos_escribir = _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "COUNT_MATCH_ROLE")
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=promos_escribir.id))
    db.flush()

    predicted = backfill_pxq_permissions_from_promos(db, dry_run=True)
    applied = backfill_pxq_permissions_from_promos(db, dry_run=False)
    db.flush()

    assert predicted["roles_granted"] == applied["roles_granted"]

    second_pass = backfill_pxq_permissions_from_promos(db, dry_run=True)
    assert second_pass["roles_granted"] == 0


def test_migration_catalog_matches_the_service_catalog() -> None:
    """The migration cannot import the service (a migration is an immutable
    historical snapshot), so the two carry duplicate literals. The dry-run runs
    the SERVICE while what actually lands is the MIGRATION — if they drift, the
    count reported in the PR describes something the migration will not write,
    which is worse than having no dry-run at all.

    Parsed from the migration source rather than imported, so this keeps
    holding even if the migration grows imports of its own."""
    import ast
    from pathlib import Path

    from app.services.pxq_permissions_backfill import _CATALOG

    migration = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260801_pxq_permisos_backfill.py"
    tree = ast.parse(migration.read_text(encoding="utf-8"))

    permisos_node = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "PERMISOS" for t in node.targets)
    )
    migration_rows = ast.literal_eval(permisos_node)

    # The migration stores es_critico as SQL text ('true'/'false'); everything
    # else must match the service tuple exactly.
    normalized = tuple(
        (codigo, nombre, descripcion, categoria, orden, es_critico == "true")
        for codigo, nombre, descripcion, categoria, orden, es_critico in migration_rows
    )

    assert normalized == _CATALOG


def test_dry_run_does_not_recount_negative_overrides_already_copied(db) -> None:
    """The negative-override counter had the same inflation the role counter
    did: a second look reported work that no longer exists."""
    ensure_pxq_permission_catalog(db)
    promos_escribir = _make_permiso(db, PROMOS_ESCRIBIR_CODE)
    rol = _make_role(db, "NEG_RECOUNT_ROLE")
    user = _make_user(db, rol, "neg_recount_user")
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=promos_escribir.id, concedido=False))
    db.flush()

    predicted = backfill_pxq_permissions_from_promos(db, dry_run=True)
    assert predicted["negative_overrides_copied"] == 1

    backfill_pxq_permissions_from_promos(db, dry_run=False)
    db.flush()

    second_pass = backfill_pxq_permissions_from_promos(db, dry_run=True)
    assert second_pass["negative_overrides_copied"] == 0
