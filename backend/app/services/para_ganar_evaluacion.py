"""PARA GANAR P5 Slice A — evaluate Periodicidad MLAs (R1–R3, no R4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.para_ganar_periodicidad import (
    SCOPE_ALL,
    SCOPE_MLAS,
    SCOPE_RULES,
    ParaGanarPeriodicidadEan,
)
from app.models.para_ganar_revision_mla import (
    REVISION_PENDIENTE,
    REVISION_SIN_NOVEDADES,
    ParaGanarRevisionMla,
)
from app.services.para_ganar_revision import upsert_revision_estado
from app.services.para_ganar_sugerencia import (
    SugerenciaMla,
    compute_sugerencia_mla,
    compute_sugerencia_mlas_bulk,
)
from app.services.para_ganar_tipos_publicacion import pricelists_for_tipos

REASON_R1 = "r1"
REASON_R2 = "r2"
REASON_R3 = "r3"
DELTA_RAISE_EPS = 0.01


def baseline_from_sugerencia(sug: SugerenciaMla) -> dict[str, Any]:
    """Persistable competition snapshot for the next R1–R3 compare."""
    snap = sug.snapshot_at
    if isinstance(snap, datetime):
        fecha: Optional[str] = snap.isoformat()
    elif snap is None:
        fecha = None
    else:
        fecha = str(snap)
    return {
        "our_rank": sug.our_rank,
        "our_price": sug.our_price,
        "suggestion_status": sug.suggestion_status,
        "in_top": bool(sug.in_top),
        "fecha_consulta": fecha,
    }


def pendiente_reasons(baseline: dict[str, Any], sug: SugerenciaMla) -> list[str]:
    """R1–R3 codes that fire for this current-vs-baseline pair (Slice A)."""
    reasons: list[str] = []
    if _rank_worsened(baseline, sug) or _lost_in_top(baseline, sug):
        reasons.append(REASON_R1)
    if _catalog_win_lost(baseline, sug):
        reasons.append(REASON_R2)
    if _can_raise_keeping_position(baseline, sug):
        reasons.append(REASON_R3)
    return reasons


def list_mlas_periodicidad_enabled(db: Session) -> list[str]:
    """Active catalog_listing MLAs in enabled Periodicidad (all|mlas|rules).

    Bulk-loads subscriptions, publications, explicit MLA links, and official
    stores — no per-EAN query loop.
    """
    subs = db.query(ParaGanarPeriodicidadEan).filter(ParaGanarPeriodicidadEan.enabled.is_(True)).all()
    if not subs:
        return []

    eans = [sub.ean for sub in subs]
    catalog_by_ean = _bulk_active_catalog_mlas(db, eans)
    explicit_by_ean = _bulk_explicit_mlas(
        db, [sub.ean for sub in subs if (sub.scope_mode or "").strip().lower() == SCOPE_MLAS]
    )
    tienda_needed = any(
        (sub.scope_mode or "").strip().lower() == SCOPE_RULES and _as_int_list(sub.tienda_oficial_ids) for sub in subs
    )
    candidate_mlas: set[str] = set()
    for sub in subs:
        for row in catalog_by_ean.get(sub.ean, []):
            candidate_mlas.add(row["mla"])
    stores_by_mla = _bulk_official_store_ids(db, sorted(candidate_mlas)) if tienda_needed else {}

    found: set[str] = set()
    for sub in subs:
        catalog = catalog_by_ean.get(sub.ean, [])
        mode = (sub.scope_mode or SCOPE_ALL).strip().lower()
        if mode == SCOPE_MLAS:
            allowed = explicit_by_ean.get(sub.ean, set())
            found.update(row["mla"] for row in catalog if row["mla"] in allowed)
            continue
        if mode == SCOPE_RULES:
            found.update(
                row["mla"] for row in catalog if _matches_rules(row, sub, stores_by_mla.get(row["mla"], set()))
            )
            continue
        found.update(row["mla"] for row in catalog)
    return sorted(found)


def evaluar_mla(db: Session, mla: str, *, updated_by_id: Optional[int]) -> Optional[str]:
    """Write revision estado + baseline. None = skip (do not persist)."""
    try:
        sug = compute_sugerencia_mla(db, mla)
    except (LookupError, ValueError):
        return None
    if not _snapshot_usable(sug):
        return None

    mla_norm = sug.mla
    row = db.get(ParaGanarRevisionMla, mla_norm)
    stored = row.competition_baseline if row is not None else None
    estado = _decide_estado(stored, sug)

    saved = upsert_revision_estado(
        db,
        mla=mla_norm,
        estado=estado,
        updated_by_id=updated_by_id,
    )
    saved.competition_baseline = baseline_from_sugerencia(sug)
    db.flush()
    return estado


def evaluar_periodicidad(db: Session, *, updated_by_id: Optional[int]) -> dict[str, int]:
    """Evaluate every enabled Periodicidad MLA. Caller commits.

    Prefetch sugerencias + existing revision rows, decide in memory, then
    one INSERT … ON CONFLICT upsert. No per-MLA query in the decision loop.
    """
    counts = {
        "evaluated": 0,
        "pendiente": 0,
        "sin_novedades": 0,
        "skipped": 0,
    }
    mlas = list_mlas_periodicidad_enabled(db)
    if not mlas:
        return counts

    sugs = compute_sugerencia_mlas_bulk(db, mlas)
    existing = {
        row.mla: row.competition_baseline
        for row in db.query(ParaGanarRevisionMla).filter(ParaGanarRevisionMla.mla.in_(mlas)).all()
    }
    writes: list[tuple[str, str, dict[str, Any]]] = []
    for mla in mlas:
        sug = sugs.get(mla)
        if sug is None or not _snapshot_usable(sug):
            counts["skipped"] += 1
            continue
        estado = _decide_estado(existing.get(mla), sug)
        writes.append((mla, estado, baseline_from_sugerencia(sug)))
        counts["evaluated"] += 1
        if estado == REVISION_PENDIENTE:
            counts["pendiente"] += 1
        elif estado == REVISION_SIN_NOVEDADES:
            counts["sin_novedades"] += 1
    _bulk_upsert_revision_estados(db, writes, updated_by_id=updated_by_id)
    return counts


def _decide_estado(stored: object, sug: SugerenciaMla) -> str:
    if not isinstance(stored, dict) or not stored:
        return REVISION_PENDIENTE
    return REVISION_PENDIENTE if pendiente_reasons(stored, sug) else REVISION_SIN_NOVEDADES


def _insert_revision(db: Session) -> Any:
    table = ParaGanarRevisionMla.__table__
    if db.get_bind().dialect.name == "postgresql":
        return postgresql.insert(table)
    return sqlite.insert(table)


def _bulk_upsert_revision_estados(
    db: Session,
    writes: list[tuple[str, str, dict[str, Any]]],
    *,
    updated_by_id: Optional[int],
) -> None:
    if not writes:
        return
    now = datetime.now(UTC)
    rows = [
        {
            "mla": mla,
            "estado": estado,
            "evaluated_at": now,
            "updated_at": now,
            "updated_by_id": updated_by_id,
            "competition_baseline": baseline,
        }
        for mla, estado, baseline in writes
    ]
    stmt = _insert_revision(db).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["mla"],
        set_={
            "estado": stmt.excluded.estado,
            "evaluated_at": stmt.excluded.evaluated_at,
            "updated_at": stmt.excluded.updated_at,
            "updated_by_id": stmt.excluded.updated_by_id,
            "competition_baseline": stmt.excluded.competition_baseline,
        },
    )
    db.execute(stmt)
    db.flush()


def _snapshot_usable(sug: SugerenciaMla) -> bool:
    if sug.needs_competition_refresh:
        return False
    if not sug.catalog_product_id:
        return False
    return True


def _rank_worsened(baseline: dict[str, Any], sug: SugerenciaMla) -> bool:
    prev = baseline.get("our_rank")
    curr = sug.our_rank
    if prev is None or curr is None:
        return False
    try:
        return int(curr) > int(prev)
    except (TypeError, ValueError):
        return False


def _lost_in_top(baseline: dict[str, Any], sug: SugerenciaMla) -> bool:
    return bool(baseline.get("in_top")) and not bool(sug.in_top)


def _catalog_win_lost(baseline: dict[str, Any], sug: SugerenciaMla) -> bool:
    prev = str(baseline.get("suggestion_status") or "none")
    return prev != "losing" and sug.suggestion_status == "losing"


def _can_raise_keeping_position(baseline: dict[str, Any], sug: SugerenciaMla) -> bool:
    if sug.suggestion_status != "winning":
        return False
    delta = sug.delta_ars if sug.delta_ars is not None else 0.0
    try:
        delta_f = float(delta)
    except (TypeError, ValueError):
        return False
    if delta_f <= DELTA_RAISE_EPS:
        return False
    prev = baseline.get("our_rank")
    curr = sug.our_rank
    if prev is not None and curr is not None:
        try:
            if int(curr) > int(prev):
                return False
        except (TypeError, ValueError):
            pass
    return True


def _bulk_active_catalog_mlas(db: Session, eans: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not eans:
        return {}
    params = {f"ean_{i}": ean for i, ean in enumerate(eans)}
    placeholders = ", ".join(f":ean_{i}" for i in range(len(eans)))
    rows = (
        db.execute(
            text(
                f"""
                SELECT e.codigo AS ean, p.mla, p.pricelist_id
                FROM publicaciones_ml p
                JOIN productos_erp e ON e.item_id = p.item_id
                JOIN ml_publication_links l ON l.mla = p.mla
                WHERE p.activo = true
                  AND e.codigo IN ({placeholders})
                  AND l.catalog_listing IS TRUE
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    out: dict[str, list[dict[str, Any]]] = {ean: [] for ean in eans}
    for row in rows:
        ean = str(row["ean"])
        mla = str(row["mla"]).strip().upper()
        if not mla:
            continue
        pricelist_id = int(row["pricelist_id"]) if row["pricelist_id"] is not None else None
        out.setdefault(ean, []).append({"mla": mla, "pricelist_id": pricelist_id})
    return out


def _bulk_explicit_mlas(db: Session, eans: list[str]) -> dict[str, set[str]]:
    if not eans:
        return {}
    params = {f"ean_{i}": ean for i, ean in enumerate(eans)}
    placeholders = ", ".join(f":ean_{i}" for i in range(len(eans)))
    rows = db.execute(
        text(
            f"""
            SELECT ean, mla
            FROM para_ganar_periodicidad_ean_mla
            WHERE ean IN ({placeholders})
            """
        ),
        params,
    ).all()
    out: dict[str, set[str]] = {ean: set() for ean in eans}
    for ean, mla in rows:
        out.setdefault(str(ean), set()).add(str(mla).strip().upper())
    return out


def _bulk_official_store_ids(db: Session, mlas: list[str]) -> dict[str, set[int]]:
    if not mlas:
        return {}
    params = {f"mla_{i}": mla for i, mla in enumerate(mlas)}
    placeholders = ", ".join(f":mla_{i}" for i in range(len(mlas)))
    try:
        rows = db.execute(
            text(
                f"""
                SELECT mlp_publicationid, mlp_official_store_id
                FROM tb_mercadolibre_items_publicados
                WHERE mlp_publicationid IN ({placeholders})
                  AND mlp_official_store_id IS NOT NULL
                """
            ),
            params,
        ).all()
    except (OperationalError, ProgrammingError):
        db.rollback()
        return {}
    out: dict[str, set[int]] = {}
    for mla, store_id in rows:
        key = str(mla).strip().upper()
        try:
            out.setdefault(key, set()).add(int(store_id))
        except (TypeError, ValueError):
            continue
    return out


def _matches_rules(
    row: dict[str, Any],
    sub: ParaGanarPeriodicidadEan,
    stores: set[int],
) -> bool:
    tipos = _as_str_list(sub.tipos_publicacion)
    pricelists = _as_int_list(sub.pricelist_ids)
    tiendas = _as_int_list(sub.tienda_oficial_ids)
    pricelist_id = row.get("pricelist_id")
    if tipos:
        allowed = set(pricelists_for_tipos(tipos))
        if pricelist_id not in allowed:
            return False
    if pricelists and pricelist_id not in set(pricelists):
        return False
    if tiendas and not (stores & set(tiendas)):
        return False
    return True


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _as_int_list(value: object) -> list[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out
