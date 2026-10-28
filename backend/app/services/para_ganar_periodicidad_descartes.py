"""Dismiss 'new MLA' alerts for Periodicidad without adding them to the list."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.para_ganar_periodicidad import (
    SCOPE_MLAS,
    ParaGanarPeriodicidadEan,
)
from app.services.para_ganar_periodicidad import normalize_ean


def _catalog_clause_sql(*, incluir_tradicionales: bool, alias: str = "p") -> str:
    if incluir_tradicionales:
        return f"""
              AND EXISTS (
                SELECT 1 FROM ml_publication_links lx
                WHERE lx.mla = {alias}.mla AND lx.catalog_product_id IS NOT NULL
              )
        """
    return f"""
              AND EXISTS (
                SELECT 1 FROM ml_publication_links lx
                WHERE lx.mla = {alias}.mla AND lx.catalog_listing IS TRUE
              )
    """


def list_mlas_nuevos_for_ean(
    db: Session,
    *,
    ean: str,
    incluir_tradicionales: bool = False,
) -> list[str]:
    """Active MLAs of the EAN not in the subscription and not yet discarded."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        return []
    params = {"ean_exact": ean_norm}
    catalog_clause = _catalog_clause_sql(incluir_tradicionales=incluir_tradicionales)
    rows = (
        db.execute(
            text(
                f"""
            SELECT p.mla
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            JOIN para_ganar_periodicidad_ean pe ON pe.ean = e.codigo
            WHERE e.codigo = :ean_exact
              AND p.activo = true
              AND pe.scope_mode = 'mlas'
              AND NOT EXISTS (
                SELECT 1 FROM para_ganar_periodicidad_ean_mla pm
                WHERE pm.ean = pe.ean AND pm.mla = p.mla
              )
              AND NOT EXISTS (
                SELECT 1 FROM para_ganar_periodicidad_ean_mla_descartado d
                WHERE d.ean = pe.ean AND d.mla = p.mla
              )
              {catalog_clause}
            ORDER BY p.mla
            """
            ),
            params,
        )
        .scalars()
        .all()
    )
    return [str(mla) for mla in rows]


_BULK_INSERT_CHUNK = 500


def _bulk_insert_descartados(
    db: Session,
    *,
    pairs: list[tuple[str, str]],
    user_id: Optional[int],
) -> int:
    """Insert (ean, mla) dismiss rows; skip conflicts. Returns rows actually inserted."""
    if not pairs:
        return 0
    now = datetime.now(UTC)
    inserted = 0
    for offset in range(0, len(pairs), _BULK_INSERT_CHUNK):
        chunk = pairs[offset : offset + _BULK_INSERT_CHUNK]
        value_sql: list[str] = []
        params: dict = {"discarded_at": now, "discarded_by_id": user_id}
        for idx, (ean, mla) in enumerate(chunk):
            e_key = f"ean_{idx}"
            m_key = f"mla_{idx}"
            value_sql.append(f"(:{e_key}, :{m_key}, :discarded_at, :discarded_by_id)")
            params[e_key] = ean
            params[m_key] = mla
        result = db.execute(
            text(
                f"""
                INSERT INTO para_ganar_periodicidad_ean_mla_descartado
                  (ean, mla, discarded_at, discarded_by_id)
                VALUES {", ".join(value_sql)}
                ON CONFLICT (ean, mla) DO NOTHING
                """
            ),
            params,
        )
        inserted += int(result.rowcount or 0)
    db.flush()
    return inserted


def descartar_mlas_nuevos_ean(
    db: Session,
    *,
    ean: str,
    user_id: Optional[int],
    incluir_tradicionales: bool = False,
) -> int:
    """Acknowledge current new MLAs for one EAN. Returns how many were discarded."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise ValueError("EAN inválido")
    sub = db.get(ParaGanarPeriodicidadEan, ean_norm)
    if sub is None:
        raise LookupError("EAN no suscripto")
    if sub.scope_mode != SCOPE_MLAS:
        return 0

    nuevos = list_mlas_nuevos_for_ean(
        db, ean=ean_norm, incluir_tradicionales=incluir_tradicionales
    )
    return _bulk_insert_descartados(
        db,
        pairs=[(ean_norm, mla) for mla in nuevos],
        user_id=user_id,
    )


def descartar_mlas_nuevos_alcance(
    db: Session,
    *,
    where_extra: str,
    params: dict,
    user_id: Optional[int],
    incluir_tradicionales: bool = False,
) -> tuple[int, int]:
    """
    Dismiss all current new-MLA gaps inside an already-built alcance WHERE clause.
    Returns (eans_afectados, mlas_descartados).
    """
    catalog_clause = _catalog_clause_sql(incluir_tradicionales=incluir_tradicionales)
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT e.codigo AS ean, p.mla
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            JOIN para_ganar_periodicidad_ean pe ON pe.ean = e.codigo
            WHERE p.activo = true
              AND pe.scope_mode = 'mlas'
              AND NOT EXISTS (
                SELECT 1 FROM para_ganar_periodicidad_ean_mla pm
                WHERE pm.ean = pe.ean AND pm.mla = p.mla
              )
              AND NOT EXISTS (
                SELECT 1 FROM para_ganar_periodicidad_ean_mla_descartado d
                WHERE d.ean = pe.ean AND d.mla = p.mla
              )
              {catalog_clause}
              {where_extra}
            ORDER BY e.codigo, p.mla
            """
        ),
        params,
    ).all()
    pairs = [(str(row.ean), str(row.mla)) for row in rows]
    inserted = _bulk_insert_descartados(db, pairs=pairs, user_id=user_id)
    eans_afectados = len({ean for ean, _ in pairs}) if inserted else 0
    return eans_afectados, inserted
