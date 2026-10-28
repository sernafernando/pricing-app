"""Migrate the legacy offsets (`offsets_ganancia`) to sell-out campaigns (sell-in-sell-out T15).

Each ACTIVE offset (`fecha_hasta` NULL or not before `--hoy`) of type
`monto_por_unidad` with a positive amount becomes ONE `por_unidad` campaign,
loaded through the campaigns service (`app.services.sell_out.campanas`: the
same validation, audit row and `sell_out.drain` queueing as a campaign loaded
from the screen) and stamped with `offset_origen_id`:

- scope: a new `offset_grupos` row gets one `offset_grupo_filtros` row per non-null scope
  field (marca / categoria / subcategoria_id / item_id). A legacy offset
  reaches a product matching ANY of its fields and a group matches ANY of its
  rows (each row ANDs its own fields), so the reach is the same;
- `monto` -> `monto_unit` in the offset's `moneda`; a USD campaign gets the
  service's default FX mode (`al_cobro`), the offset's rate is not kept;
- `max_unidades` -> `tope_unidades`; `max_monto_usd` -> `tope_monto` only for a
  USD offset (an ARS campaign keeps no money cap, with a warning);
- a NULL `fecha_hasta` ends on `--fecha-hasta-default` (2026-12-31), with a
  warning so someone adjusts it; a campaign covers every channel, so an offset
  that skipped some is migrated with a warning.

Everything else is reported in the CSV and NOT migrated, each with its reason:
expired offsets (history is not recomputed), `porcentaje_costo` (waits for the
sell-in percentage, T3g; until then it keeps working as a legacy offset),
`monto_fijo`, a non-positive amount, an offset of a group (the legacy money
path applies each grouped offset's own amount to its own product under one
shared cap, which a campaign linked to the group would not), no scope, no user (offset without
`usuario_id` and no `--usuario-id`) and the service's validation errors.
An offset already migrated is reported as such with its campaign: a re-run
creates nothing.

Under `--apply`, every offset left out is also kept, with its own detail and the
reason, in `offsets_migracion_pendientes` for the owner's review (T22a, owner:
"lo que no se pueda migrar directo haceme un detalle y guardamelo en una
tabla"): one row per offset, updated by a re-run, and removed once the offset
migrates. The dry run leaves the table as it is; its summary counts what
`--apply` would keep there (`pendientes`).

Dry run is the DEFAULT: it only validates (`validar` / `validar_campos`) and
writes nothing. `--apply` loads each offset in its own transaction (its new
group and its campaign commit together, or neither does). Exits 1 when a
validation or database error left an offset out, 0 otherwise. Run from `backend/` with `-m`:
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.migrar_offsets_a_sell_out --csv /tmp/offsets.csv
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.migrar_offsets_a_sell_out --csv /tmp/offsets.csv --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_migracion_pendiente import OffsetMigracionPendiente
from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import NOMBRE_MAX, SellOutCampanaIn
from app.services.sell_out import campanas
from app.utils.csv_cells import csv_money, csv_text

logger = logging.getLogger(__name__)

FECHA_HASTA_DEFAULT = date(2026, 12, 31)
ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")
COLUMNAS = [
    "offset_id",
    "tipo",
    "descripcion",
    "alcance",
    "valor",
    "moneda",
    "desde",
    "hasta",
    "resultado",
    "campana_id",
    "motivo",
    "avisos",
]
MIGRADO, NO_MIGRADO, YA_MIGRADO, MIGRARIA = "migrado", "no migrado", "ya migrado", "migraría (dry-run)"
# Scope fields as (column, CSV label), in the order the filter rows are created.
_ALCANCE = (
    ("marca", "marca"),
    ("categoria", "categoría"),
    ("subcategoria_id", "subcategoría"),
    ("item_id", "producto"),
)
_CANALES = (("aplica_ml", "ML"), ("aplica_fuera", "fuera de ML"), ("aplica_tienda_nube", "Tienda Nube"))
_GRUPO_NOMBRE_MAX = OffsetGrupo.__table__.c.nombre.type.length


@dataclass
class _Plan:
    """What one offset becomes: a campaign (`data`), or a reason not to migrate it (`error`: a value the
    campaign cannot hold, reported like a validation error)."""

    motivo: Optional[str] = None
    error: bool = False
    data: Optional[SellOutCampanaIn] = None
    usuario_id: Optional[int] = None
    avisos: list[str] = field(default_factory=list)


def _texto(offset: OffsetGanancia) -> str:
    return (offset.descripcion or "").strip()


def _alcance(offset: OffsetGanancia) -> str:
    if offset.grupo_id is not None:
        return f"grupo #{offset.grupo_id}"
    return " o ".join(f"{label} {getattr(offset, col)}" for col, label in _ALCANCE if getattr(offset, col) is not None)


def _monto(valor: float) -> Decimal:
    return Decimal(str(valor))


# The legacy money path applies each grouped offset's own amount to its own product, the group only sharing one cap;
# a campaign linked to the group would apply one amount to all it reaches. None is active in production (2026-10-22).
GRUPO_MOTIVO = (
    "Offset de un grupo: en el sistema anterior cada offset del grupo aplica su monto a su producto con un tope "
    "compartido; revisar a mano"
)


def _planear(offset: OffsetGanancia, hoy: date, fecha_hasta_default: date, usuario_id: Optional[int]) -> _Plan:
    if offset.fecha_hasta is not None and offset.fecha_hasta < hoy:
        return _Plan(f"Vencido el {offset.fecha_hasta.isoformat()}: no se migra para no recalcular la historia")
    if offset.tipo_offset == "porcentaje_costo":
        return _Plan("esperando sell-in % (T3g)")
    if offset.tipo_offset == "monto_fijo":
        return _Plan("Monto fijo: no tiene equivalente en una campaña por unidad")
    if offset.tipo_offset != "monto_por_unidad":
        return _Plan(f"Tipo de offset desconocido: {offset.tipo_offset}")
    if offset.monto is None or offset.monto <= 0:
        return _Plan("Monto negativo o cero")
    if offset.grupo_id is not None:
        return _Plan(GRUPO_MOTIVO)
    usuario = offset.usuario_id if offset.usuario_id is not None else usuario_id
    if usuario is None:
        return _Plan("Sin usuario: indicar --usuario-id")
    if not any(getattr(offset, col) is not None for col, _ in _ALCANCE):
        return _Plan("Sin alcance: no indica marca, categoría, subcategoría, producto ni grupo")

    plan = _Plan(usuario_id=usuario)
    moneda = offset.moneda or "ARS"
    tope_monto = None
    if offset.max_monto_usd is not None:
        if moneda == "USD":
            tope_monto = _monto(offset.max_monto_usd)
        else:
            plan.avisos.append(
                f"El tope en USD ({csv_money(offset.max_monto_usd)}) no se migró: la campaña es en pesos"
            )
    if moneda == "USD" and offset.tipo_cambio is not None:
        plan.avisos.append(
            f"El tipo de cambio del offset ({csv_money(offset.tipo_cambio)}) no se migró: "
            "la campaña queda con tipo de cambio al cobro"
        )
    fecha_hasta = offset.fecha_hasta
    if fecha_hasta is None:
        fecha_hasta = fecha_hasta_default
        plan.avisos.append(f"Sin fecha hasta: se usó {fecha_hasta.isoformat()}, revisar")
    sin_canal = [label for col, label in _CANALES if getattr(offset, col) is False]
    if sin_canal:
        plan.avisos.append(f"El offset no aplicaba a: {', '.join(sin_canal)}; la campaña aplica a todos los canales")
    texto = _texto(offset)
    try:
        plan.data = SellOutCampanaIn(
            nombre=(texto or f"Offset #{offset.id}")[:NOMBRE_MAX],
            descripcion=f"Migrado del offset #{offset.id}" + (f": {texto}" if texto else ""),
            fecha_desde=offset.fecha_desde,
            fecha_hasta=fecha_hasta,
            tipo="por_unidad",
            monto_unit=_monto(offset.monto),
            moneda=moneda,
            tope_unidades=offset.max_unidades,
            tope_monto=tope_monto,
            grupo_ids=[],  # its own new group, created under --apply
        )
    except ValidationError as exc:
        return _Plan(f"Valor no válido en: {_campos(exc)}", error=True)
    return plan


def _campos(exc: ValidationError) -> str:
    """The fields a validation error names; a model-level error has none and names the whole campaign."""
    return ", ".join(dict.fromkeys(str(e["loc"][0]) if e["loc"] else "campaña" for e in exc.errors()))


def _nuevo_grupo(db: Session, offset: OffsetGanancia, usuario_id: int) -> int:
    """The offset's scope as a group: one filter row per field, so a product matching any of them is reached."""
    nombre = f"Offset #{offset.id}: {_texto(offset)}" if _texto(offset) else f"Offset #{offset.id}"
    grupo = OffsetGrupo(
        nombre=nombre[:_GRUPO_NOMBRE_MAX],
        descripcion=f"Alcance del offset #{offset.id}, migrado a sell out",
        usuario_id=usuario_id,
    )
    db.add(grupo)
    db.flush()
    for col, _ in _ALCANCE:
        if getattr(offset, col) is not None:
            db.add(OffsetGrupoFiltro(grupo_id=grupo.id, **{col: getattr(offset, col)}))
    db.flush()
    return grupo.id


def _fila(offset: OffsetGanancia, resultado: str, campana_id=None, motivo=None, avisos=()) -> dict:
    valor = offset.porcentaje if offset.tipo_offset == "porcentaje_costo" else offset.monto
    return {
        "offset_id": offset.id,
        "tipo": csv_text(offset.tipo_offset),
        "descripcion": csv_text(offset.descripcion),
        "alcance": csv_text(_alcance(offset)),
        "valor": csv_money(valor),
        "moneda": csv_text(offset.moneda),
        "desde": offset.fecha_desde.isoformat(),
        "hasta": offset.fecha_hasta.isoformat() if offset.fecha_hasta else "",
        "resultado": resultado,
        "campana_id": campana_id if campana_id is not None else "",
        "motivo": csv_text(motivo),
        "avisos": csv_text(" | ".join(avisos)),
    }


# The offset's own columns copied to the review table, as they are.
_DETALLE = (
    "tipo_offset",
    "descripcion",
    "marca",
    "categoria",
    "subcategoria_id",
    "item_id",
    "grupo_id",
    "monto",
    "porcentaje",
    "moneda",
    "tipo_cambio",
    "fecha_desde",
    "fecha_hasta",
    "max_unidades",
    "max_monto_usd",
    "aplica_ml",
    "aplica_fuera",
    "aplica_tienda_nube",
    "usuario_id",
)


def _guardar_pendiente(db: Session, offset: OffsetGanancia, motivo: str, avisos: list[str]) -> None:
    """Keeps the offset for review, or refreshes its row: a re-run stores the offset as it is now."""
    values = {
        "offset_id": offset.id,
        **{col: getattr(offset, col) for col in _DETALLE},
        "motivo": motivo,
        "avisos": " | ".join(avisos) or None,
    }
    stmt = insert(OffsetMigracionPendiente).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[OffsetMigracionPendiente.offset_id],
        set_={**{k: stmt.excluded[k] for k in values if k != "offset_id"}, "registrado_en": func.now()},
    )
    db.execute(stmt)


def _quitar_pendiente(db: Session, offset_id: int) -> None:
    db.query(OffsetMigracionPendiente).filter(OffsetMigracionPendiente.offset_id == offset_id).delete()


def _ya_migrada(db: Session, offset_id: int) -> Optional[int]:
    return db.query(SellOutCampana.id).filter(SellOutCampana.offset_origen_id == offset_id).scalar()


def _uno(db: Session, offset: OffsetGanancia, plan: _Plan, apply: bool) -> tuple[dict, Optional[str]]:
    """The CSV row of one planned offset and its validation error, if any. Under `apply` it commits."""
    try:
        if not apply:
            campanas.validar_campos(plan.data)  # its group does not exist yet
            return _fila(offset, MIGRARIA, avisos=plan.avisos), None
        plan.data.grupo_ids = [_nuevo_grupo(db, offset, plan.usuario_id)]
        campana = campanas.crear_campana(db, plan.data, plan.usuario_id, offset_origen_id=offset.id)
        return _fila(offset, MIGRADO, campana.id, avisos=plan.avisos), None
    except campanas.SellOutError as exc:
        db.rollback()  # drops the new group too
        return _fila(offset, NO_MIGRADO, motivo=str(exc), avisos=plan.avisos), str(exc)
    except SQLAlchemyError as exc:
        # One offset's database error must not cost the others, nor the report: it is rolled back and reported.
        db.rollback()
        logger.exception("Offset #%s: database error", offset.id)
        motivo = f"Error de base de datos: {type(exc).__name__}"
        return _fila(offset, NO_MIGRADO, motivo=motivo, avisos=plan.avisos), motivo


def run_migracion(
    *,
    session_factory: Callable[[], Session],
    apply: bool = False,
    hoy: date,
    fecha_hasta_default: date = FECHA_HASTA_DEFAULT,
    usuario_id: Optional[int] = None,
) -> tuple[dict, list[dict]]:
    """`(summary, CSV rows)`: every offset in id order, each in its own session."""
    with session_factory() as db:
        ids = [oid for (oid,) in db.query(OffsetGanancia.id).order_by(OffsetGanancia.id)]
    summary = {
        "dry_run": not apply,
        "offsets": len(ids),
        "migrados": 0,
        "migrarian": 0,
        "ya_migrados": 0,
        "no_migrados": 0,
        "con_error": [],
        "campana_ids": [],
        "pendientes": 0,
    }
    contador = {MIGRADO: "migrados", MIGRARIA: "migrarian", YA_MIGRADO: "ya_migrados", NO_MIGRADO: "no_migrados"}
    filas = []
    for offset_id in ids:
        with session_factory() as db:
            offset = fila = error = None
            pendiente = None  # (reason, warnings) of an offset left out, for the review table
            guardado = False  # kept for review (or, in a dry run, would be)
            try:
                offset = db.get(OffsetGanancia, offset_id)
                if offset is None:  # deleted after the ids were read: no detail left to keep
                    filas.append(
                        {
                            **dict.fromkeys(COLUMNAS, ""),
                            "offset_id": offset_id,
                            "resultado": NO_MIGRADO,
                            "motivo": "El offset ya no existe",
                        }
                    )
                    summary["no_migrados"] += 1
                    continue
                ya = _ya_migrada(db, offset_id)
                error = None
                if ya is not None:
                    fila = _fila(offset, YA_MIGRADO, ya)
                else:
                    plan = _planear(offset, hoy, fecha_hasta_default, usuario_id)
                    if plan.data is None:
                        fila = _fila(offset, NO_MIGRADO, motivo=plan.motivo, avisos=plan.avisos)
                        error = plan.motivo if plan.error else None
                        pendiente = (plan.motivo, plan.avisos)
                    else:
                        fila, error = _uno(db, offset, plan, apply)
                        if fila["resultado"] == NO_MIGRADO:
                            pendiente = (error or "No migrado", plan.avisos)
                if apply:
                    # `_uno` already rolled a failed campaign back: what commits here is the review row alone.
                    if pendiente is not None:
                        _guardar_pendiente(db, offset, *pendiente)
                    else:
                        _quitar_pendiente(db, offset_id)
                    db.commit()
                guardado = pendiente is not None
            except SQLAlchemyError as exc:
                db.rollback()
                logger.exception("Offset #%s: database error", offset_id)
                motivo = f"Error de base de datos: {type(exc).__name__}"
                error = error or motivo
                if fila is None:
                    # Reading the offset failed: reported with its id alone, the run and the report go on.
                    fila = {
                        **dict.fromkeys(COLUMNAS, ""),
                        "offset_id": offset_id,
                        "resultado": NO_MIGRADO,
                        "motivo": motivo,
                    }
                else:
                    # Keeping it for review failed: the CSV keeps its reason and says the table missed it.
                    aviso = f"No se guardó en la tabla de revisión ({motivo})"
                    fila["avisos"] = csv_text(" | ".join(filter(None, [fila["avisos"], aviso])))
            finally:
                if not apply:
                    db.rollback()
        filas.append(fila)
        summary[contador[fila["resultado"]]] += 1
        if guardado:
            summary["pendientes"] += 1
        if error is not None:
            summary["con_error"].append(offset_id)
        if fila["resultado"] == MIGRADO:
            summary["campana_ids"].append(fila["campana_id"])
    return summary, filas


def escribir_csv(path: str, filas: list[dict]) -> None:
    # `;` and a BOM, like the app's other exports: Excel opens it in the Spanish locale with its accents.
    with open(path, "w", encoding="utf-8-sig", newline="") as archivo:
        writer = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        writer.writeheader()
        writer.writerows(filas)


def _fecha(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value!r}") from None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate the legacy offsets to sell-out campaigns (dry run by default)."
    )
    parser.add_argument("--csv", required=True, help="Where to write the report (CSV).")
    parser.add_argument("--apply", action="store_true", help="Create the campaigns; without it nothing is written.")
    parser.add_argument("--usuario-id", type=int, default=None, help="User for the offsets that have none.")
    parser.add_argument(
        "--fecha-hasta-default", type=_fecha, default=FECHA_HASTA_DEFAULT, help="End date for open-ended offsets."
    )
    parser.add_argument("--hoy", type=_fecha, default=None, help="Business date (default: today in Argentina).")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    from app.core import database  # resolved at call time, so tests can point it elsewhere

    # The report is the only record of the warnings: an unwritable path stops the run before anything is created.
    open(args.csv, "w", encoding="utf-8-sig").close()
    summary, filas = run_migracion(
        session_factory=database.SessionLocal,
        apply=args.apply,
        hoy=args.hoy or datetime.now(ARGENTINA).date(),
        fecha_hasta_default=args.fecha_hasta_default,
        usuario_id=args.usuario_id,
    )
    escribir_csv(args.csv, filas)
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 1 if summary["con_error"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
