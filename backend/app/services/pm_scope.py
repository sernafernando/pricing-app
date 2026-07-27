"""Shared PM scope resolution: effective (marca, categoria) access = the
deduplicated UNION of `marcas_pm` (titular) and `marca_sub_pm` (sub-PM).

Two coordinated entry points (design decision D1 — a raw `text()` site
cannot consume an ORM `Query`):
  - `get_pares_marca_categoria_usuario` / `get_pares_para_pm_ids` /
    `aplicar_filtro_marcas_pm`: ORM resolvers for dashboard_ml.py and
    rentabilidad_shared.py.
  - `scope_exists_sql`: a raw-SQL snippet builder for the consultas.py
    EXISTS sites, sharing the same semantic contract (bound to
    `:scope_user_id`).

D2: `pm_ids` (admin impersonation of another PM's view) is gated to
FULL_VIEW_ROLES only — a sub-PM's effective scope already includes their
delegated pairs, so pm_ids is unnecessary (and would be a privilege
escalation vector) for non-privileged callers.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.models.marca_pm import MarcaPM
from app.models.marca_sub_pm import MarcaSubPM
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.usuario import RolUsuario, Usuario

FULL_VIEW_ROLES = (RolUsuario.SUPERADMIN, RolUsuario.ADMIN, RolUsuario.GERENTE)


def is_full_view(usuario: Usuario) -> bool:
    """True when the user's role sees all PM scopes (no filtering needed)."""
    return usuario.rol in FULL_VIEW_ROLES


def _upper_pairs(rows) -> list[tuple]:
    return [(m.upper(), c.upper()) for m, c in rows]


def get_pares_marca_categoria_usuario(db: Session, usuario: Usuario) -> Optional[list]:
    """Effective (marca, categoria) pairs for `usuario`.

    Returns None when the user has full-view access (no filtering needed).
    Otherwise returns the UNION-deduplicated list of pairs from `marcas_pm`
    (titular) and `marca_sub_pm` (sub-PM), restricted to that usuario_id.
    Inactive users are excluded upstream (the caller's own account gate);
    a `marca_sub_pm` row for an inactive grantee resolves to an empty scope.
    """
    if is_full_view(usuario):
        return None

    if not usuario.activo:
        return []

    titular_q = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id == usuario.id)
    sub_pm_q = db.query(MarcaSubPM.marca, MarcaSubPM.categoria).filter(MarcaSubPM.usuario_id == usuario.id)

    pares = titular_q.union(sub_pm_q).all()
    return _upper_pairs(pares) if pares else []


def get_pares_para_pm_ids(db: Session, pm_ids: list[int]) -> list:
    """Effective pairs for an arbitrary set of usuario_ids (admin pm_ids override).

    UNION of marcas_pm + marca_sub_pm across all requested ids.
    """
    if not pm_ids:
        return []

    titular_q = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids))
    sub_pm_q = db.query(MarcaSubPM.marca, MarcaSubPM.categoria).filter(MarcaSubPM.usuario_id.in_(pm_ids))

    pares = titular_q.union(sub_pm_q).all()
    return _upper_pairs(pares)


def aplicar_filtro_marcas_pm(
    query,
    usuario: Usuario,
    db: Session,
    pm_ids: Optional[str] = None,
    *,
    marca_col=None,
    categoria_col=None,
):
    """Apply the (marca, categoria) PM-scope filter to a query.

    Defaults to filtering `MLVentaMetrica.marca`/`.categoria` (the original
    contract). Pass `marca_col`/`categoria_col` (keyword-only) to scope a query
    over a different model — e.g. `ProductoERP.marca`/`.categoria` for a catalog
    search — with the SAME effective-scope semantics.

    If `pm_ids` is present AND the caller has a FULL_VIEW_ROLES role, filter
    by those PMs' UNION'd scope instead of the caller's own (admin/gerente
    inspecting a specific PM's — including a sub-PM's — view). Otherwise
    (D2) `pm_ids` is dropped and the caller's own effective scope applies.
    """
    if marca_col is None:
        marca_col = MLVentaMetrica.marca
    if categoria_col is None:
        categoria_col = MLVentaMetrica.categoria

    if pm_ids and not is_full_view(usuario):
        pm_ids = None  # D2: pm_ids is full-view-role-only; no impersonation for others

    if pm_ids:
        pm_ids_list = [int(pid.strip()) for pid in pm_ids.split(",") if pid.strip().isdigit()]
        if pm_ids_list:
            pares_pm = get_pares_para_pm_ids(db, pm_ids_list)

            if not pares_pm:
                return query.filter(marca_col == "__NINGUNA__")
            return query.filter(tuple_(func.upper(marca_col), func.upper(categoria_col)).in_(pares_pm))

    pares_usuario = get_pares_marca_categoria_usuario(db, usuario)

    if pares_usuario is not None:
        if len(pares_usuario) == 0:
            query = query.filter(marca_col == "__NINGUNA__")
        else:
            query = query.filter(tuple_(func.upper(marca_col), func.upper(categoria_col)).in_(pares_usuario))

    return query


def scope_exists_sql(alias_pe: str = "pe") -> str:
    """Raw-SQL EXISTS snippet: pair scoped to :scope_user_id via marcas_pm OR marca_sub_pm.

    Callers bind `scope_user_id` in their params dict, unchanged from the
    pre-existing marcas_pm-only contract.
    """
    return (
        "(EXISTS ("
        "SELECT 1 FROM marcas_pm mp_scope"
        f" WHERE mp_scope.marca = {alias_pe}.marca"
        f" AND mp_scope.categoria = {alias_pe}.categoria"
        " AND mp_scope.usuario_id = :scope_user_id"
        ") OR EXISTS ("
        "SELECT 1 FROM marca_sub_pm msp_scope"
        f" WHERE msp_scope.marca = {alias_pe}.marca"
        f" AND msp_scope.categoria = {alias_pe}.categoria"
        " AND msp_scope.usuario_id = :scope_user_id"
        "))"
    )
