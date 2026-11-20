"""Plan -> confirm -> apply for every AI write (S4), the audit rows (S7) and undo, shared by the MCP write tools and
the app's "Acciones IA" API.

- `plan_order` / `plan_undo`: guards (access, kill switch, motivo, limits, rows), then the plan is stored with a
  random single-use `confirm_token` (only its SHA-256 is kept), valid 15 minutes, bound to user + connection +
  origin + tool + plan hash.
- `apply_plan`: re-checks access and kill switch, claims the plan atomically (a used token never writes again: the
  stored result comes back as `ya_aplicado`), then per row re-reads the live value (moved -> `rechazada`), applies it
  through the real endpoint as the user and records one `mcp_write_actions` row with before/after.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import anyio
from sqlalchemy.orm import Session

from app.mcp import store, tools
from app.mcp.write import criteria, families, guards
from app.mcp.write.context import WriteContext, WriteError, in_db
from app.models.mcp_write import McpWriteAction, McpWritePlan
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)

PLAN_TTL = timedelta(minutes=15)
UNDO_TOOL = "accion_deshacer"
_PUBLIC_ROW_KEYS = (
    "accion_id",
    "objetivo",
    "objetivo_label",
    "accion",
    "antes",
    "despues",
    "estado",
    "detalle",
    "cambios_pct",
    "markup_previsto",
    "mejora",
)


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in _PUBLIC_ROW_KEYS if key in row}


def _iso(value: datetime | None) -> str | None:
    value = store.aware(value)
    return value.isoformat().replace("+00:00", "Z") if value else None


# ---------------------------------------------------------------- guards shared by plan and apply


def _preflight(db: Session, ctx: WriteContext) -> None:
    guards.check_access(db, ctx)
    guards.check_enabled(db)


def check_reader(db: Session, ctx: WriteContext) -> None:
    """Reading the audit from the MCP needs the same scope + permission as writing (no kill switch)."""
    guards.check_access(db, ctx)


# ---------------------------------------------------------------- plan


def _plan_hash(tool: str, motivo: str, limites: Any, filas: list[dict[str, Any]]) -> str:
    payload = json.dumps([tool, motivo, limites, filas], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _store_plan(
    db: Session, ctx: WriteContext, tool: str, motivo: str, limites: Any, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    filas = [public_row(r) | {"datos": r.get("datos") or {}} for r in rows]
    ready = sum(1 for r in rows if r["estado"] == guards.ESTADO_LISTA)
    result: dict[str, Any] = {
        "filas": [public_row(r) for r in rows],
        "resumen": {"listas": ready, "bloqueadas": len(rows) - ready},
    }
    if not ready:
        return result | {
            "plan_id": None,
            "confirm_token": None,
            "aviso": "Ninguna fila se puede aplicar: todas quedaron bloqueadas (ver detalle). No se guardó plan.",
        }
    token = store.new_secret()
    plan_id = f"p_{secrets.token_urlsafe(18)}"
    moment = store.now()
    db.add(
        McpWritePlan(
            plan_id=plan_id,
            confirm_token_hash=store.hash_secret(token),
            usuario_id=ctx.usuario_id,
            connection_id=ctx.connection_id,
            origen=ctx.origen,
            cliente=ctx.cliente[:100],
            tool=tool,
            motivo=motivo,
            limites=limites,
            filas=filas,
            plan_hash=_plan_hash(tool, motivo, limites, filas),
            created_at=moment,
            expires_at=moment + PLAN_TTL,
        )
    )
    db.commit()
    return result | {"plan_id": plan_id, "confirm_token": token, "expires_at": _iso(moment + PLAN_TTL)}


def _refuse_duplicates(rows: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["objetivo"], row["accion"])
        if key in seen:
            raise WriteError("invalida", f"objetivo repetido en la orden: {row['objetivo']}")
        seen.add(key)


async def plan_order(
    ctx: WriteContext,
    tool: str,
    kind: str,
    motivo: Any,
    limites: Any,
    build_rows: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> dict[str, Any]:
    """Guards in order, then the rows (live values), then the per-row guards, then the stored plan."""
    await in_db(_preflight, ctx)
    clean_motivo = guards.check_motivo(motivo)
    clean_limites = guards.check_limites(limites, kind)
    rows = await build_rows()
    if not rows:
        raise WriteError("invalida", "la orden no tiene filas")
    _refuse_duplicates(rows)
    await in_db(guards.evaluate_rows, rows, clean_limites, kind)
    return await in_db(_store_plan, ctx, tool, clean_motivo, clean_limites, rows)


# ---------------------------------------------------------------- apply


def _load_plan(db: Session, ctx: WriteContext, tool: str, plan_id: Any, token: Any) -> dict[str, Any]:
    if not isinstance(plan_id, str) or not isinstance(token, str) or not plan_id or not token:
        raise WriteError("token", "para aplicar hacen falta plan_id y confirm_token del plan", 409)
    plan = db.query(McpWritePlan).filter(McpWritePlan.plan_id == plan_id).first()
    if plan is None:
        raise WriteError("token", "plan inexistente", 409)
    if (
        plan.usuario_id != ctx.usuario_id
        or plan.origen != ctx.origen
        or plan.connection_id != ctx.connection_id
        or plan.tool != tool
    ):
        raise WriteError("token", "el plan es de otra persona, conexión o herramienta", 409)
    if not hmac.compare_digest(plan.confirm_token_hash, store.hash_secret(token)):
        raise WriteError("token", "confirm_token inválido para ese plan", 409)
    if plan.used_at is not None:
        raise WriteError("ya_aplicado", "ese plan ya se aplicó: no se escribió nada nuevo", 409, result=plan.resultado)
    if store.aware(plan.expires_at) <= store.now():
        raise WriteError("token", "el plan venció (15 minutos): generá uno nuevo", 409)
    if plan.plan_hash != _plan_hash(plan.tool, plan.motivo, plan.limites, plan.filas):
        raise WriteError("token", "el plan guardado no coincide con su firma", 409)
    return {"plan_id": plan.plan_id, "tool": plan.tool, "motivo": plan.motivo, "filas": plan.filas}


def _claim(db: Session, plan_id: str) -> bool:
    claimed = (
        db.query(McpWritePlan)
        .filter(McpWritePlan.plan_id == plan_id, McpWritePlan.used_at.is_(None))
        .update({McpWritePlan.used_at: store.now()}, synchronize_session=False)
    )
    db.commit()
    return claimed == 1


def _record(
    db: Session,
    ctx: WriteContext,
    plan: dict[str, Any],
    row: dict[str, Any],
    resultado: str,
    detalle: str | None,
    despues: dict[str, Any] | None,
) -> int:
    action = McpWriteAction(
        plan_id=plan["plan_id"],
        usuario_id=ctx.usuario_id,
        connection_id=ctx.connection_id,
        cliente=ctx.cliente[:100],
        tool=plan["tool"],
        accion=row["accion"],
        objetivo=row["objetivo"],
        objetivo_label=row.get("objetivo_label"),
        antes=row.get("antes"),
        despues=despues if despues is not None else row.get("despues"),
        motivo=plan["motivo"],
        resultado=resultado,
        detalle=(detalle or None) and detalle[:500],
        criteria_version=criteria.CRITERIA_VERSION,
        undo_of_id=row.get("accion_id"),
        created_at=store.now(),
    )
    db.add(action)
    db.flush()
    if resultado == families.OK and row.get("accion_id"):
        original = db.get(McpWriteAction, row["accion_id"])
        if original is not None:
            original.deshecha_por_id = action.id
    db.commit()
    return action.id


def _already_undone(db: Session, accion_id: int) -> bool:
    original = db.get(McpWriteAction, accion_id)
    return original is None or original.deshecha_por_id is not None


def _finish(db: Session, plan_id: str, resultado: dict[str, Any]) -> None:
    plan = db.query(McpWritePlan).filter(McpWritePlan.plan_id == plan_id).first()
    plan.resultado = resultado
    db.commit()


async def _apply_row(ctx: WriteContext, row: dict[str, Any]) -> families.Outcome:
    enabled, _ = await in_db(lambda db: guards.write_status(db))
    if not enabled:
        return families.BLOQUEADA, "la escritura desde IA se deshabilitó durante la aplicación", None
    if row.get("accion_id") and await in_db(_already_undone, row["accion_id"]):
        return families.BLOQUEADA, "ya deshecha", None
    family = families.FAMILIES[row["accion"]]
    try:
        problem = await family.check(ctx, row, "el plan")
    except tools.ToolCallError as exc:
        problem = f"no se pudo releer el valor actual: {exc}"
    if problem:
        return families.RECHAZADA, problem, None
    try:
        return await family.apply(ctx, row)
    except Exception:  # noqa: BLE001 - one row must not stop the rest; the log has the trace
        logger.exception("MCP write row failed: %s %s", row["accion"], row["objetivo"])
        return families.ERROR, "error interno al aplicar", None


async def apply_plan(ctx: WriteContext, tool: str, plan_id: Any, token: Any) -> dict[str, Any]:
    await in_db(_preflight, ctx)
    plan = await in_db(_load_plan, ctx, tool, plan_id, token)
    if await anyio.to_thread.run_sync(guards.write_rate_limited, ctx.usuario_id):
        raise WriteError("limitada", "demasiadas escrituras: esperá un minuto", 429)
    if not await in_db(_claim, plan["plan_id"]):
        raise WriteError("ya_aplicado", "ese plan ya se está aplicando o se aplicó", 409)
    resultados = []
    for row in plan["filas"]:
        if row.get("estado") != guards.ESTADO_LISTA:
            resultados.append(
                {
                    "accion_id": row.get("accion_id"),
                    "objetivo": row["objetivo"],
                    "accion": row["accion"],
                    "resultado": families.BLOQUEADA,
                    "detalle": row.get("detalle"),
                    "nueva_accion_id": None,
                }
            )
            continue
        resultado, detalle, despues = await _apply_row(ctx, row)
        action_id = await in_db(_record, ctx, plan, row, resultado, detalle, despues)
        resultados.append(
            {
                "accion_id": row.get("accion_id"),
                "objetivo": row["objetivo"],
                "accion": row["accion"],
                "resultado": resultado,
                "detalle": detalle,
                "nueva_accion_id": action_id,
            }
        )
    counts: dict[str, int] = {}
    for item in resultados:
        counts[item["resultado"]] = counts.get(item["resultado"], 0) + 1
    result = {"plan_id": plan["plan_id"], "resultados": resultados, "resumen": counts}
    await in_db(_finish, plan["plan_id"], result)
    return result


# ---------------------------------------------------------------- undo


def action_dict(action: McpWriteAction, usuario_nombre: str | None = None) -> dict[str, Any]:
    return {
        "id": action.id,
        "plan_id": action.plan_id,
        "created_at": _iso(action.created_at),
        "usuario_id": action.usuario_id,
        "usuario_nombre": usuario_nombre,
        "cliente": action.cliente,
        "tool": action.tool,
        "accion": action.accion,
        "objetivo": action.objetivo,
        "objetivo_label": action.objetivo_label,
        "antes": action.antes or {},
        "despues": action.despues or {},
        "motivo": action.motivo,
        "resultado": action.resultado,
        "detalle": action.detalle,
        "deshacible": action.resultado == families.OK and action.accion in families.FAMILIES,
        "deshecha": action.deshecha_por_id is not None,
        "undo_of_id": action.undo_of_id,
    }


def _actions_to_undo(
    db: Session, ctx: WriteContext, accion_ids: list[int] | None, plan_id: str | None, own_only: bool
) -> list[dict[str, Any]]:
    query = db.query(McpWriteAction)
    if plan_id:
        query = query.filter(McpWriteAction.plan_id == plan_id)
    else:
        query = query.filter(McpWriteAction.id.in_(list(dict.fromkeys(accion_ids or []))))
    if own_only:
        query = query.filter(McpWriteAction.usuario_id == ctx.usuario_id)
    return [action_dict(a) for a in query.order_by(McpWriteAction.id).all()]


async def plan_undo(
    ctx: WriteContext,
    motivo: Any,
    accion_ids: list[int] | None = None,
    plan_id: str | None = None,
    own_only: bool = False,
) -> dict[str, Any]:
    """Undo plan: the same guards (access, kill switch, motivo, plan -> confirm), exempt from ±10%, limits and band
    because it restores the exact snapshot. An action whose target changed since, already undone, or not applied
    is listed as `bloqueada`."""
    await in_db(_preflight, ctx)
    clean_motivo = guards.check_motivo(motivo)
    if not accion_ids and not plan_id:
        raise WriteError("invalida", "indicá accion_ids o plan_id")
    actions = await in_db(_actions_to_undo, ctx, accion_ids, plan_id, own_only)
    if not actions:
        raise WriteError("invalida", "no hay acciones para deshacer con esos datos", 404)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        if action["resultado"] != families.OK:
            row = families.new_row(action["accion"], action["objetivo"], action["objetivo_label"])
            guards.block(row, f"la acción no se aplicó (resultado {action['resultado']})")
        elif action["deshecha"]:
            row = families.new_row(action["accion"], action["objetivo"], action["objetivo_label"])
            guards.block(row, "ya deshecha")
        else:
            row = await families.undo_row(ctx, action)
            key = (row["objetivo"], row["accion"])
            if row["estado"] == guards.ESTADO_LISTA and key in seen:
                guards.block(row, "otra acción sobre el mismo objetivo ya está en este deshacer")
            elif row["estado"] == guards.ESTADO_LISTA:
                try:
                    problem = await families.FAMILIES[row["accion"]].check(ctx, row, "la acción")
                except tools.ToolCallError as exc:
                    problem = f"no se pudo leer el valor actual: {exc}"
                if problem:
                    guards.block(row, problem)
                else:
                    seen.add(key)
        row["accion_id"] = action["id"]
        if row["estado"] != guards.ESTADO_LISTA:
            row["antes"], row["despues"] = action["despues"], action["antes"]
        rows.append(row)
    return await in_db(_store_plan, ctx, UNDO_TOOL, clean_motivo, None, rows)


# ---------------------------------------------------------------- audit list


def list_actions(
    db: Session,
    *,
    usuario_id: int | None = None,
    cliente: str | None = None,
    tool: str | None = None,
    resultado: str | None = None,
    plan_id: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    query = db.query(McpWriteAction, Usuario.nombre).outerjoin(Usuario, Usuario.id == McpWriteAction.usuario_id)
    if usuario_id is not None:
        query = query.filter(McpWriteAction.usuario_id == usuario_id)
    if cliente:
        query = query.filter(McpWriteAction.cliente == cliente)
    if tool:
        query = query.filter(McpWriteAction.tool == tool)
    if resultado:
        query = query.filter(McpWriteAction.resultado == resultado)
    if plan_id:
        query = query.filter(McpWriteAction.plan_id == plan_id)
    if desde:
        query = query.filter(McpWriteAction.created_at >= datetime.combine(desde, time.min, tzinfo=UTC))
    if hasta:
        query = query.filter(
            McpWriteAction.created_at < datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=UTC)
        )
    total = query.count()
    rows = query.order_by(McpWriteAction.created_at.desc(), McpWriteAction.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [action_dict(action, nombre) for action, nombre in rows]}
