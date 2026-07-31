"""Dedicated PxQ permission catalog + backfill (ml-wholesale-pxq-pricing PR2).

`pxq.ver` / `pxq.escribir` are declared separate from `promos.escribir` and
backfilled from the ACTUAL live grants of `promos.escribir` at migration
time — roles queried dynamically (never a hardcoded role list, unlike the
`20260713_add_permisos_promociones.py` precedent) AND user overrides,
including negative ones (`concedido=False`), so a user explicitly revoked
from promos-write does not silently gain PxQ writes.

Used by the Alembic migration (`20260801_add_ml_pxq_tier.py` upgrade path or
a companion migration) and by the pre-deploy dry-run script (task 2c.20,
`dry_run=True`).
"""

from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride

PXQ_VER_CODE = "pxq.ver"
PXQ_ESCRIBIR_CODE = "pxq.escribir"
PROMOS_ESCRIBIR_CODE = "promos.escribir"

_CATALOG = (
    (PXQ_VER_CODE, "Ver tiers PxQ ML", "Ver tiers de precio por cantidad (mayorista) ML", "pxq", 50, False),
    (
        PXQ_ESCRIBIR_CODE,
        "Editar/sincronizar tiers PxQ ML",
        "Crear/editar/sincronizar tiers de precio por cantidad (mayorista) ML",
        "pxq",
        51,
        True,
    ),
)


def ensure_pxq_permission_catalog(db: Session) -> None:
    """Idempotently inserts the `pxq.ver` / `pxq.escribir` catalog rows."""
    existing_codes = {p.codigo for p in db.query(Permiso).filter(Permiso.codigo.in_([c[0] for c in _CATALOG])).all()}
    for codigo, nombre, descripcion, categoria, orden, es_critico in _CATALOG:
        if codigo in existing_codes:
            continue
        db.add(
            Permiso(
                codigo=codigo,
                nombre=nombre,
                descripcion=descripcion,
                categoria=categoria,
                orden=orden,
                es_critico=es_critico,
            )
        )
    db.flush()


def backfill_pxq_permissions_from_promos(db: Session, dry_run: bool = False) -> Dict[str, int]:
    """Grants `pxq.ver`/`pxq.escribir` to every role/user CURRENTLY holding
    `promos.escribir`, derived from live grants (never hardcoded).

    `dry_run=True` computes the same counts WITHOUT writing anything — used
    by the pre-deploy dry-run check (task 2c.20). Returns
    `{"roles_granted", "users_granted", "negative_overrides_copied"}`.
    """
    counts = {"roles_granted": 0, "users_granted": 0, "negative_overrides_copied": 0}

    promos_permiso = db.query(Permiso).filter(Permiso.codigo == PROMOS_ESCRIBIR_CODE).first()
    pxq_ver = db.query(Permiso).filter(Permiso.codigo == PXQ_VER_CODE).first()
    pxq_escribir = db.query(Permiso).filter(Permiso.codigo == PXQ_ESCRIBIR_CODE).first()
    if promos_permiso is None or pxq_ver is None or pxq_escribir is None:
        return counts

    # Roles that currently grant promos.escribir by default (live query).
    role_grants = db.query(RolPermisoBase).filter(RolPermisoBase.permiso_id == promos_permiso.id).all()
    for grant in role_grants:
        # Count the role only if it would actually receive something. Counting
        # every promos.escribir grant regardless inflates the dry-run on any
        # re-run — and that count is the mandatory pre-deploy gate someone
        # reads to decide whether applying this is safe.
        granted_here = False
        for target_id in (pxq_ver.id, pxq_escribir.id):
            already_granted = (
                db.query(RolPermisoBase)
                .filter(RolPermisoBase.rol_id == grant.rol_id, RolPermisoBase.permiso_id == target_id)
                .first()
            )
            if already_granted is not None:
                continue
            granted_here = True
            if not dry_run:
                db.add(RolPermisoBase(rol_id=grant.rol_id, permiso_id=target_id))
        if granted_here:
            counts["roles_granted"] += 1

    # Positive user overrides on promos.escribir (concedido=True).
    positive_overrides = (
        db.query(UsuarioPermisoOverride)
        .filter(UsuarioPermisoOverride.permiso_id == promos_permiso.id, UsuarioPermisoOverride.concedido.is_(True))
        .all()
    )
    for override in positive_overrides:
        counts["users_granted"] += 1
        if dry_run:
            continue
        for target_id in (pxq_ver.id, pxq_escribir.id):
            already_granted = (
                db.query(UsuarioPermisoOverride)
                .filter(
                    UsuarioPermisoOverride.usuario_id == override.usuario_id,
                    UsuarioPermisoOverride.permiso_id == target_id,
                )
                .first()
            )
            if already_granted is None:
                db.add(
                    UsuarioPermisoOverride(
                        usuario_id=override.usuario_id,
                        permiso_id=target_id,
                        concedido=True,
                        motivo="Backfilled from promos.escribir (ml-wholesale-pxq-pricing PR2)",
                    )
                )

    # Negative user overrides on promos.escribir (concedido=False) — COPIED,
    # not ignored: a user explicitly revoked from promos-write must not
    # silently gain PxQ write access via their role.
    negative_overrides = (
        db.query(UsuarioPermisoOverride)
        .filter(UsuarioPermisoOverride.permiso_id == promos_permiso.id, UsuarioPermisoOverride.concedido.is_(False))
        .all()
    )
    for override in negative_overrides:
        # Same rule as the role counter above: count only what would actually
        # be written, or a re-run reports a number nobody can act on.
        already_present = (
            db.query(UsuarioPermisoOverride)
            .filter(
                UsuarioPermisoOverride.usuario_id == override.usuario_id,
                UsuarioPermisoOverride.permiso_id == pxq_escribir.id,
            )
            .first()
        )
        if already_present is not None:
            continue
        counts["negative_overrides_copied"] += 1
        if not dry_run:
            db.add(
                UsuarioPermisoOverride(
                    usuario_id=override.usuario_id,
                    permiso_id=pxq_escribir.id,
                    concedido=False,
                    motivo="Backfilled negative override from promos.escribir (ml-wholesale-pxq-pricing PR2)",
                )
            )

    if not dry_run:
        db.flush()

    return counts
