"""Server-side guards every AI write passes, in this order (design §12.2), before anything is written:

1. scope `pricing.write` on the token (MCP only) AND `mcp.escribir`, read fresh from the database;
2. kill switch: env `MCP_WRITE_KILL_SWITCH` (wins), `ML_PUB_KILL_SWITCH`, then the `mcp_write.enabled` DB flag
   (default OFF);
3. `motivo` (1..500 chars) and the order's own `limites` (L13 Q3: they come with each order, never fixed caps);
4. per row: the hard ±10% per price change (code constant, not configurable), the order's limits, the minimum
   markup on the predicted markup and the C1 band (app.mcp.write.criteria). A row over any of them is `bloqueada`
   with the reason and is never applied.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from limits import parse as parse_rate_limit
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.mcp import store
from app.mcp.write import criteria
from app.mcp.write.context import ORIGEN_MCP, WriteContext, WriteError
from app.services.ml_publications import settings_store

logger = logging.getLogger(__name__)

HARD_CAP_PCT = 10.0  # L13 Q2: no price moves more than 10% in one change, whatever the order says
FLAG_KEY = "mcp_write.enabled"

KIND_PRECIO = "precio"
KIND_PROMO = "promo"
KIND_ESTADO = "estado"

ESTADO_LISTA = "lista"
ESTADO_BLOQUEADA = "bloqueada"

FUENTE_DEFAULT = "default"
FUENTE_DB = "db"
FUENTE_KILL_SWITCH = "kill_switch"


# ---------------------------------------------------------------- 1. who


def check_access(db: Session, ctx: WriteContext) -> None:
    if ctx.origen == ORIGEN_MCP and store.SCOPE_WRITE not in (ctx.scopes or ()):
        raise WriteError("denegada", "esta conexión es de solo lectura (falta el scope pricing.write)", 403)
    if not store.may_write(db, store.load_user(db, ctx.usuario_id)):
        raise WriteError("denegada", f"falta el permiso {store.PERMISO_ESCRIBIR}", 403)


# ---------------------------------------------------------------- 2. kill switch


def write_status(db: Session) -> tuple[bool, str]:
    """(enabled, source): source is `kill_switch` when an env switch forces it off, `db` when a row decides, else
    `default`. An unreadable settings table reads as disabled."""
    if settings.MCP_WRITE_KILL_SWITCH:
        return False, FUENTE_KILL_SWITCH
    setting = settings_store.get_setting(FLAG_KEY, session=db)
    if setting.source == settings_store.SOURCE_KILL_SWITCH:
        return False, FUENTE_KILL_SWITCH
    if setting.source == settings_store.SOURCE_DB:
        return setting.value is True, FUENTE_DB
    return setting.value is True, FUENTE_DEFAULT


def set_write_enabled(db: Session, enabled: bool, updated_by: str) -> None:
    settings_store.set_setting(FLAG_KEY, enabled, updated_by, session=db)


def check_enabled(db: Session) -> None:
    enabled, source = write_status(db)
    if not enabled:
        why = "bloqueado por el servidor (kill switch)" if source == FUENTE_KILL_SWITCH else "apagado en Acciones IA"
        raise WriteError("deshabilitada", f"la escritura desde IA está deshabilitada: {why}", 503)


def write_rate_limited(usuario_id: int) -> bool:
    try:
        return not limiter.limiter.hit(parse_rate_limit(settings.MCP_WRITE_RATE_LIMIT), "mcp-writes", str(usuario_id))
    except Exception:  # noqa: BLE001 - fail open like the read limiter (storage outage)
        logger.warning("MCP write rate-limit storage unavailable: fail-open")
        return False


# ---------------------------------------------------------------- 3. order


def check_motivo(motivo: Any) -> str:
    text = motivo.strip() if isinstance(motivo, str) else ""
    if not text or len(text) > 500:
        raise WriteError("falta_motivo", "`motivo` es obligatorio (1 a 500 caracteres): por qué se hace el cambio")
    return text


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def required_limits(kind: str) -> tuple[str, ...]:
    if kind == KIND_PRECIO:
        return ("max_items", "max_cambio_pct", "min_markup_pct")
    if kind == KIND_PROMO:
        return ("max_items", "min_markup_pct")
    return ("max_items",)


def check_limites(limites: Any, kind: str) -> dict[str, float]:
    """The order's limits, validated. Missing ones -> `faltan_limites` naming them (they come from the person)."""
    given = limites if isinstance(limites, dict) else {}
    missing = [key for key in required_limits(kind) if given.get(key) is None]
    if missing:
        raise WriteError(
            "faltan_limites",
            f"faltan límites de la orden: {', '.join(missing)}. Pedíselos a la persona; no los inventes.",
        )
    clean: dict[str, float] = {}
    max_items = given["max_items"]
    if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
        raise WriteError("limites_invalidos", "max_items debe ser un entero >= 1")
    clean["max_items"] = max_items
    if kind == KIND_PRECIO:
        cambio = _number(given["max_cambio_pct"])
        if cambio is None or not 0 < cambio <= HARD_CAP_PCT:
            raise WriteError("limites_invalidos", f"max_cambio_pct debe estar entre 0 y {HARD_CAP_PCT:g}")
        clean["max_cambio_pct"] = cambio
    if kind in (KIND_PRECIO, KIND_PROMO):
        markup = _number(given["min_markup_pct"])
        if markup is None:
            raise WriteError("limites_invalidos", "min_markup_pct debe ser un número")
        clean["min_markup_pct"] = markup
        for key in ("max_baja_pct", "max_suba_pct"):
            if given.get(key) is not None:
                value = _number(given[key])
                if value is None or value < 0:
                    raise WriteError("limites_invalidos", f"{key} debe ser un número >= 0")
                clean[key] = value
    return clean


# ---------------------------------------------------------------- 4. rows


def block(row: dict[str, Any], detalle: str) -> None:
    row["estado"] = ESTADO_BLOQUEADA
    row["detalle"] = detalle


def _price_problem(pcts: list[float] | None, limites: dict[str, float]) -> str | None:
    if not pcts:
        return "sin_precio_actual: no hay precio actual para medir el cambio"
    for pct in pcts:
        if abs(pct) > HARD_CAP_PCT:
            return f"tope_10: cambio de {pct:+.2f}% supera el tope fijo de ±{HARD_CAP_PCT:g}% por cambio"
        if abs(pct) > limites["max_cambio_pct"]:
            return f"max_cambio_pct: cambio de {pct:+.2f}% supera {limites['max_cambio_pct']:g}%"
        if "max_baja_pct" in limites and pct < -limites["max_baja_pct"]:
            return f"max_baja_pct: baja de {pct:.2f}% supera {limites['max_baja_pct']:g}%"
        if "max_suba_pct" in limites and pct > limites["max_suba_pct"]:
            return f"max_suba_pct: suba de {pct:+.2f}% supera {limites['max_suba_pct']:g}%"
    return None


def _markup_problem(db: Session, row: dict[str, Any], limites: dict[str, float]) -> str | None:
    markup = _number(row.get("markup_previsto"))
    if markup is None:
        return "sin_markup: no se pudo calcular el markup previsto"
    if markup < limites["min_markup_pct"]:
        return f"min_markup_pct: markup previsto {markup:.2f}% menor que {limites['min_markup_pct']:g}%"
    band = criteria.band_for(db, {"accion": row["accion"], "objetivo": row["objetivo"]})
    if band == criteria.UNAVAILABLE:
        return "banda_no_disponible: los criterios de banda (C1) todavía no están disponibles"
    if isinstance(band, tuple) and not band[0] <= markup <= band[1]:
        return f"fuera_de_banda: markup previsto {markup:.2f}% fuera de la banda {band[0]:g}%..{band[1]:g}%"
    return None


def evaluate_rows(db: Session, rows: list[dict[str, Any]], limites: dict[str, float], kind: str) -> None:
    """Mark every row over a guard as `bloqueada` with the reason (in place)."""
    ready = 0
    for row in rows:
        if row.get("estado") != ESTADO_LISTA:
            continue
        problem = None
        if kind == KIND_PRECIO:
            problem = _price_problem(row.get("cambios_pct"), limites)
        if problem is None and kind in (KIND_PRECIO, KIND_PROMO):
            problem = _markup_problem(db, row, limites)
        if problem is None and ready >= limites["max_items"]:
            problem = f"max_items: la orden permite {int(limites['max_items'])} cambios"
        if problem is not None:
            block(row, problem)
        else:
            ready += 1


def pct_change(before: Any, after: Any) -> float | None:
    old, new = _number(before), _number(after)
    if old is None or new is None or old <= 0:
        return None
    return round((new - old) / old * 100, 4)
