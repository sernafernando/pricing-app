"""Sell-out programs: the higher level that groups campaigns (campaign system S1; "Programa" on screen).

A program groups the campaigns that are one deal renewed over time or split by what each applies to ("EPSON PROG
24", "EPSON PROG 25", ...). It is metadata only: no allocator, cap or money path reads `programa_id`, so assigning
or clearing it queues nothing in `sell_out_dirty` and works on active and voided campaigns alike. Existing campaigns
are assigned by hand: `sugerencias` only proposes groups of campaigns without a program that share a base name
(`nombre_base`), never applies them.

A program's name is unique ignoring case (`uq_sell_out_programas_nombre_lower`). A program is never deleted here;
an archived one (`archivado`) keeps its campaigns but takes no new ones. Every assignment change writes one audit
row per campaign (`SELL_OUT_CAMPANA_PROGRAMA`, `item_id` NULL, `campana_id` in the values), `es_masivo` when one
call changes more than one campaign, like the bulk void.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.sell_out import SellOutCampana, SellOutPrograma
from app.schemas.sell_out import SellOutProgramaIn, SellOutProgramaPatchIn


class ProgramaError(ValueError):
    """The request cannot be served as asked (a 422); the message is for the operator."""


class ProgramaNoExiste(ProgramaError):
    """The program does not exist (a 404)."""


class ProgramaDuplicado(ProgramaError):
    """Another program already has this name, ignoring case (a 409)."""


# ── Base name ──────────────────────────────────────────────────────

# What separates a trailing marker from the name ("EPSON PROG - 24", "Rebate Q4-2024").
_SEPARADORES = " -–—_/.,:;|"
_SEP = r"[\s\-–—_/.,:;|]"
# A period or sequence marker: a 1-2 digit number or a 20xx year, Q1-Q4, "#3", "(2)", "N°3" / "Nº 3". A longer
# number is a model ("RB 8180"), not a period.
_MARCADOR = r"(?:\d{1,2}|20\d{2}|q[1-4]|#\s*\d+|\(\s*\d+\s*\)|n\s*[°º]\s*\d+)"
_MARCADOR_FINAL = re.compile(rf"(?:(?<={_SEP})|^){_MARCADOR}$", re.IGNORECASE)


def nombre_base(nombre: str) -> str:
    """The name without its trailing period or sequence markers and separators, spaces collapsed: "EPSON PROG 24"
    and "EPSON PROG 25" are "EPSON PROG", "Rebate Q4 2024" is "Rebate". Campaigns are grouped by its casefold.
    Never empty: when everything would be stripped ("Q4 2024") the name itself is the base."""
    original = " ".join(nombre.split())
    base = original
    while True:
        base = base.rstrip(_SEPARADORES)
        marcador = _MARCADOR_FINAL.search(base)
        if marcador is None:
            break
        base = base[: marcador.start()]
    return base or original


# ── Programs ───────────────────────────────────────────────────────


def listar(db: Session, estado: Optional[str] = None, programa_id: Optional[int] = None) -> list[dict]:
    """Every program (or just `programa_id`) by name, with its campaigns' count, active count and date span, in
    one query."""
    p, c = SellOutPrograma, SellOutCampana
    query = (
        db.query(
            p.id,
            p.nombre,
            p.descripcion,
            p.estado,
            func.count(c.id),
            func.coalesce(func.sum(case((c.estado == "activa", 1), else_=0)), 0),
            func.min(c.fecha_desde),
            func.max(c.fecha_hasta),
        )
        .outerjoin(c, c.programa_id == p.id)
        .group_by(p.id, p.nombre, p.descripcion, p.estado)
    )
    if estado:
        query = query.filter(p.estado == estado)
    if programa_id is not None:
        query = query.filter(p.id == programa_id)
    filas = query.order_by(func.lower(p.nombre), p.id).all()
    return [
        {
            "id": pid,
            "nombre": nombre,
            "descripcion": descripcion,
            "estado": estado_,
            "campanas": int(campanas),
            "activas": int(activas),
            "desde": desde,
            "hasta": hasta,
        }
        for pid, nombre, descripcion, estado_, campanas, activas, desde, hasta in filas
    ]


def detalle(db: Session, programa_id: int) -> dict:
    """One program in the list's shape."""
    filas = listar(db, programa_id=programa_id)
    if filas:
        return filas[0]
    raise ProgramaNoExiste(f"El programa {programa_id} no existe.")


def _duplicado(db: Session, nombre: str, excepto: Optional[int] = None) -> Optional[SellOutPrograma]:
    query = db.query(SellOutPrograma).filter(func.lower(SellOutPrograma.nombre) == nombre.lower())
    if excepto is not None:
        query = query.filter(SellOutPrograma.id != excepto)
    return query.first()


def _guardar(db: Session, nombre: str) -> None:
    """Commit, turning a concurrent duplicate (the unique index) into the same 409 as the check before it."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_sell_out_programas_nombre_lower" not in str(exc.orig):
            raise
        raise ProgramaDuplicado(f"Ya existe un programa llamado «{nombre}».") from exc


def crear(db: Session, data: SellOutProgramaIn, usuario_id: int) -> SellOutPrograma:
    """A new active program. `ProgramaDuplicado` when the name is taken, ignoring case."""
    existente = _duplicado(db, data.nombre)
    if existente is not None:
        raise ProgramaDuplicado(f"Ya existe un programa llamado «{existente.nombre}».")
    programa = SellOutPrograma(nombre=data.nombre, descripcion=data.descripcion, usuario_id=usuario_id)
    db.add(programa)
    _guardar(db, data.nombre)
    return programa


def editar(db: Session, programa_id: int, data: SellOutProgramaPatchIn) -> SellOutPrograma:
    """Change only the fields sent. `ProgramaNoExiste`, or `ProgramaDuplicado` when the new name is taken."""
    programa = db.query(SellOutPrograma).filter(SellOutPrograma.id == programa_id).with_for_update().first()
    if programa is None:
        raise ProgramaNoExiste(f"El programa {programa_id} no existe.")
    cambios = data.model_dump(include=data.model_fields_set)
    if "nombre" in cambios:
        existente = _duplicado(db, cambios["nombre"], excepto=programa_id)
        if existente is not None:
            raise ProgramaDuplicado(f"Ya existe un programa llamado «{existente.nombre}».")
    for campo, valor in cambios.items():
        setattr(programa, campo, valor)
    _guardar(db, programa.nombre)
    return programa


# ── Assignment ─────────────────────────────────────────────────────


def _referencia(programa_id: Optional[int], nombres: dict[int, str]) -> dict:
    return {"programa_id": programa_id, "programa": None if programa_id is None else nombres[programa_id]}


def asignar(db: Session, campana_ids: list[int], programa_id: Optional[int], usuario_id: int) -> tuple[int, int]:
    """Set (or clear, with None) the program of these campaigns, all or nothing, in one transaction. Returns
    `(asignadas, sin_cambio)`. `ProgramaNoExiste` for an unknown program; a `ProgramaError` (422) for an archived
    one or unknown campaigns, naming them. Active and voided campaigns alike; nothing is queued."""
    ids = sorted(set(campana_ids))
    nombres: dict[int, str] = {}
    if programa_id is not None:
        programa = db.query(SellOutPrograma).filter(SellOutPrograma.id == programa_id).with_for_update(read=True)
        programa = programa.first()
        if programa is None:
            raise ProgramaNoExiste(f"El programa {programa_id} no existe.")
        if programa.estado == "archivado":
            raise ProgramaError(f"El programa «{programa.nombre}» está archivado.")
    # In id order, so concurrent assignments and edits lock in one order.
    campanas = (
        db.query(SellOutCampana).filter(SellOutCampana.id.in_(ids)).order_by(SellOutCampana.id).with_for_update().all()
    )
    faltan = sorted(set(ids) - {c.id for c in campanas})
    if faltan:
        db.rollback()
        lista = ", ".join(str(i) for i in faltan)
        raise ProgramaError(
            f"La campaña {lista} no existe." if len(faltan) == 1 else f"Las campañas {lista} no existen."
        )
    cambian = [c for c in campanas if c.programa_id != programa_id]
    referidos = ({c.programa_id for c in cambian} | {programa_id}) - {None}
    if referidos:
        rows = db.query(SellOutPrograma.id, SellOutPrograma.nombre).filter(SellOutPrograma.id.in_(referidos))
        nombres = dict(rows.all())
    masivo = len(cambian) > 1
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, like the column's default
    for campana in cambian:
        antes = {"campana_id": campana.id, **_referencia(campana.programa_id, nombres)}
        campana.programa_id = programa_id
        db.add(
            Auditoria(
                item_id=None,
                usuario_id=usuario_id,
                tipo_accion=TipoAccion.SELL_OUT_CAMPANA_PROGRAMA,
                valores_anteriores=antes,
                valores_nuevos={"campana_id": campana.id, **_referencia(programa_id, nombres)},
                es_masivo=masivo,
                fecha=ahora,
            )
        )
    db.commit()
    return len(cambian), len(campanas) - len(cambian)


def programas_de(db: Session, campanas: list[SellOutCampana]) -> dict[int, dict]:
    """`{programa_id: {id, nombre}}` of the programs these campaigns belong to, in one query."""
    ids = {c.programa_id for c in campanas if c.programa_id is not None}
    if not ids:
        return {}
    rows = db.query(SellOutPrograma.id, SellOutPrograma.nombre).filter(SellOutPrograma.id.in_(ids))
    return {pid: {"id": pid, "nombre": nombre} for pid, nombre in rows}


# ── Suggestions ────────────────────────────────────────────────────


def sugerencias(db: Session) -> list[dict]:
    """Groups of 2 or more campaigns WITHOUT a program sharing a base name (`nombre_base`, ignoring case), biggest
    first, then by base. Each group's campaigns by start date; its `base` is its earliest campaign's."""
    c = SellOutCampana
    rows = (
        db.query(c.id, c.nombre, c.fecha_desde, c.fecha_hasta, c.estado)
        .filter(c.programa_id.is_(None))
        .order_by(c.fecha_desde, c.id)
    )
    grupos: dict[str, list[dict]] = {}
    for cid, nombre, desde, hasta, estado in rows:
        clave = nombre_base(nombre).casefold()
        fila = {"id": cid, "nombre": nombre, "fecha_desde": desde, "fecha_hasta": hasta, "estado": estado}
        grupos.setdefault(clave, []).append(fila)
    salida = [
        {"base": nombre_base(campanas[0]["nombre"]), "campanas": campanas}
        for campanas in grupos.values()
        if len(campanas) >= 2
    ]
    return sorted(salida, key=lambda g: (-len(g["campanas"]), g["base"].casefold()))
