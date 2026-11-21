"""Recompute a product's costo SI and store it, backing up what it replaces (S8, L2.4 / L2.5 / L4.8).

The whole history is recomputed from the product's start (cheap: one step per purchase invoice), then compared with
the stored one step by step. Only the steps from the first one that differs are replaced, so a late sell in rewrites
its date onward ("se recalcula desde el 01/11 en adelante", L2.4) and leaves everything before it untouched, closed
months included; the replaced rows go to `costo_si_backups` first. A product whose history did not change writes
nothing. One product at a time per transaction-level advisory lock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.costo_si import fuentes
from app.services.costo_si.engine import Paso, calcular

LOCK_CLASS = 2026_1125  # pg_advisory_xact_lock(class, item_id): one recompute per product at a time

_COLUMNAS = (
    "tipo",
    "fecha",
    "ct_transaction",
    "cantidad",
    "costo_neto_usd",
    "sell_ins",
    "sell_in_pct",
    "costo_neto_neto_usd",
    "stock_antes",
    "stock_base",
    "stock_despues",
    "promedio_usd",
    "tipo_cambio",
    "fuente_tc",
    "en_compras",
    "moneda",
)

_GUARDADOS_SQL = text(
    f"SELECT orden, {', '.join(_COLUMNAS)}, calculado_at FROM costo_si_pasos WHERE item_id = :i ORDER BY orden"
)

_INSERT_SQL = text(
    f"INSERT INTO costo_si_pasos (item_id, orden, {', '.join(_COLUMNAS)}) VALUES "
    f"(:item_id, :orden, {', '.join(':' + c for c in _COLUMNAS)})"
)


@dataclass(frozen=True)
class Resultado:
    item_id: int
    pasos: int  # steps in the history now
    reemplazados: int  # stored steps replaced (backed up)
    desde: Optional[date]  # first date whose value changed; None: nothing changed


def _fila(paso: Paso, moneda: str) -> dict:
    return {
        "tipo": paso.tipo,
        "fecha": paso.fecha,
        "ct_transaction": paso.ct_transaction,
        "cantidad": paso.cantidad,
        "costo_neto_usd": paso.costo_neto_usd,
        "sell_ins": [{"origen": s.origen, "ref": s.ref, "porcentaje": str(s.porcentaje)} for s in paso.sell_ins],
        "sell_in_pct": paso.sell_in_pct,
        "costo_neto_neto_usd": paso.costo_neto_neto_usd,
        "stock_antes": paso.stock_antes,
        "stock_base": paso.stock_base,
        "stock_despues": paso.stock_despues,
        "promedio_usd": paso.promedio_usd,
        "tipo_cambio": paso.tipo_cambio,
        "fuente_tc": paso.fuente_tc,
        "en_compras": paso.en_compras,
        "moneda": moneda,
    }


def _clave(fila: dict) -> tuple:
    """Comparable form of a step: numbers as Decimal, so 8.6 and 8.6000 are the same step."""
    out: List[Any] = []
    for c in _COLUMNAS:
        v = fila[c]
        if c == "sell_ins":
            v = tuple((s["origen"], int(s["ref"]), Decimal(str(s["porcentaje"]))) for s in (v or []))
        elif isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
            v = Decimal(str(v))
        out.append(v)
    return tuple(out)


def _json(fila: dict) -> dict:
    return {k: (str(v) if isinstance(v, (Decimal, date)) else v) for k, v in fila.items()}


def guardar(db: Session, item_id: int, pasos: Sequence[Paso], motivo: str, moneda: str = "USD") -> Resultado:
    """Stores `pasos` (amounts in `moneda`, the product's cost currency, L18) as the product's history, replacing
    (after backing them up) only the steps that changed: a currency change rewrites every step."""
    db.execute(text("SELECT pg_advisory_xact_lock(:c, :i)"), {"c": LOCK_CLASS, "i": item_id})
    guardados = [dict(r._mapping) for r in db.execute(_GUARDADOS_SQL, {"i": item_id})]
    nuevos = [_fila(p, moneda) for p in pasos]
    k = 0
    while k < len(guardados) and k < len(nuevos) and _clave(guardados[k]) == _clave(nuevos[k]):
        k += 1
    if k == len(guardados) == len(nuevos):
        return Resultado(item_id, len(nuevos), 0, None)
    fechas = [f["fecha"] for f in (guardados[k : k + 1] + nuevos[k : k + 1])]
    desde = min(fechas) if fechas else None
    viejos = guardados[k:]
    if viejos:
        db.execute(
            text(
                "INSERT INTO costo_si_backups (item_id, desde, motivo, pasos) "
                "VALUES (:i, :desde, :motivo, CAST(:pasos AS jsonb))"
            ),
            {"i": item_id, "desde": desde, "motivo": motivo, "pasos": json.dumps([_json(f) for f in viejos])},
        )
        db.execute(text("DELETE FROM costo_si_pasos WHERE item_id = :i AND orden >= :k"), {"i": item_id, "k": k})
    if nuevos[k:]:
        db.execute(
            _INSERT_SQL,
            [
                {**fila, "sell_ins": json.dumps(fila["sell_ins"]), "item_id": item_id, "orden": orden}
                for orden, fila in enumerate(nuevos[k:], start=k)
            ],
        )
    return Resultado(item_id, len(nuevos), len(viejos), desde)


def recalcular(db: Session, item_id: int, *, motivo: str = "recalculo") -> Resultado:
    """Recompute `item_id` from its start (its first sell-in date, or 2026-11-01 without one: L21) and store it. Reads only the app's own data (Full included:
    `full_ml`). Does not commit."""
    entrada = fuentes.entrada(db, item_id)
    if entrada is None:
        return guardar(db, item_id, [], motivo)
    return guardar(db, item_id, calcular(entrada.inicio, entrada.compras), motivo, entrada.moneda)
