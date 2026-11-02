"""Sell-out programs: the higher level that groups campaigns (campaign system S1; "Programa" on screen).

A program groups the campaigns that are one deal renewed over time or split by what each applies to (in production
one name repeated over many products, or a family of names that carry their per-unit amount, all over the same
dates). It is metadata only: no allocator, cap or money path reads `programa_id`, so assigning
or clearing it queues nothing in `sell_out_dirty` and works on active and voided campaigns alike. Existing campaigns
are assigned by hand: `sugerencias` only proposes groups of campaigns without a program that share the exact same
dates (the repeated names do, and differ only in what they apply to), never applies them.

A program's name is unique ignoring case (`uq_sell_out_programas_nombre_lower`). A program is never deleted here;
an archived one (`archivado`) keeps its campaigns but takes no new ones. Every assignment change writes one audit
row per campaign (`SELL_OUT_CAMPANA_PROGRAMA`, `item_id` NULL, `campana_id` in the values), `es_masivo` when one
call changes more than one campaign, like the bulk void.
"""

from __future__ import annotations

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


# ── Programs ───────────────────────────────────────────────────────


def listar(
    db: Session,
    estado: Optional[str] = None,
    programa_id: Optional[int] = None,
    *,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
) -> list[dict]:
    """Every program (or just `programa_id`) by name, with its campaigns' count, active count and date span, in
    one query, and its distinct names (`contar_nombres`) in one more for the whole page; with `page` /
    `page_size`, only that page (cut in SQL)."""
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
    query = query.order_by(func.lower(p.nombre), p.id)
    if page is not None and page_size is not None:
        query = query.offset((page - 1) * page_size).limit(page_size)
    filas = query.all()
    ids = [fila[0] for fila in filas]
    nombres = {}
    if ids:
        de_la_pagina = db.query(c.programa_id, c.nombre).filter(c.programa_id.in_(ids)).distinct()
        nombres = contar_nombres(de_la_pagina.all())
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
            "nombres": nombres.get(pid, 0),
        }
        for pid, nombre, descripcion, estado_, campanas, activas, desde, hasta in filas
    ]


def nombre_normalizado(nombre: str) -> str:
    """A campaign name as `nombres` compares it: ignoring case and repeated spaces."""
    return " ".join(nombre.split()).casefold()


def contar_nombres(filas) -> dict:
    """`{programa_id: distinct names}` of `(programa_id, nombre)` rows, by `nombre_normalizado`."""
    vistos: dict = {}
    for programa_id, nombre in filas:
        vistos.setdefault(programa_id, set()).add(nombre_normalizado(nombre))
    return {programa_id: len(nombres) for programa_id, nombres in vistos.items()}


def contar(db: Session, estado: Optional[str] = None) -> int:
    """How many programs `listar` would return without a page."""
    query = db.query(func.count(SellOutPrograma.id))
    if estado:
        query = query.filter(SellOutPrograma.estado == estado)
    return query.scalar() or 0


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


def validar_asignable(db: Session, programa_id: int) -> SellOutPrograma:
    """The program, which may take campaigns, share-locked until commit so it is not archived meanwhile.
    `ProgramaNoExiste` for an unknown one; a `ProgramaError` (422) for an archived one."""
    programa = db.query(SellOutPrograma).filter(SellOutPrograma.id == programa_id).with_for_update(read=True).first()
    if programa is None:
        raise ProgramaNoExiste(f"El programa {programa_id} no existe.")
    if programa.estado == "archivado":
        raise ProgramaError(f"El programa «{programa.nombre}» está archivado.")
    return programa


def asignar(db: Session, campana_ids: list[int], programa_id: Optional[int], usuario_id: int) -> tuple[int, int]:
    """Set (or clear, with None) the program of these campaigns, all or nothing, in one transaction. Returns
    `(asignadas, sin_cambio)`. `ProgramaNoExiste` for an unknown program; a `ProgramaError` (422) for an archived
    one or unknown campaigns, naming them. Active and voided campaigns alike; nothing is queued."""
    ids = sorted(set(campana_ids))
    nombres: dict[int, str] = {}
    if programa_id is not None:
        validar_asignable(db, programa_id)
    # In id order, so concurrent assignments and edits lock in one order.
    campanas = (
        db.query(SellOutCampana)
        .filter(SellOutCampana.id.in_(ids))
        .order_by(SellOutCampana.id)
        # FOR NO KEY UPDATE: metadata only, so it never waits on the FOR KEY SHARE every consumo insert takes.
        .with_for_update(key_share=True)
        .all()
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


def _palabras_comunes(nombres: list[str]) -> str:
    """The leading words every name starts with, ignoring case ("MARCA PROG 3.0" and "MARCA PROGRAM1": "MARCA"),
    in the first name's spelling; "" when they share none."""
    listas = [nombre.split() for nombre in nombres]
    comunes = []
    for palabras in zip(*listas):
        if len({p.casefold() for p in palabras}) > 1:
            break
        comunes.append(palabras[0])
    return " ".join(comunes)


def sugerencias(db: Session) -> list[dict]:
    """Groups of 2 or more campaigns WITHOUT a program that share their exact dates (`fecha_desde`, `fecha_hasta`),
    biggest first, then by start date. A group's `base` (the proposed program name, editable) is the words all its
    names start with, or its date range when they share none; `nombres` counts its distinct names. Each group's
    campaigns by name (ignoring case), then id. Voided campaigns count too: a program groups history as well."""
    c = SellOutCampana
    rows = (
        db.query(c.id, c.nombre, c.fecha_desde, c.fecha_hasta, c.estado)
        .filter(c.programa_id.is_(None))
        .order_by(c.fecha_desde, c.fecha_hasta, func.lower(c.nombre), c.id)
    )
    grupos: dict[tuple, list[dict]] = {}
    for cid, nombre, desde, hasta, estado in rows:
        fila = {"id": cid, "nombre": nombre, "fecha_desde": desde, "fecha_hasta": hasta, "estado": estado}
        grupos.setdefault((desde, hasta), []).append(fila)
    salida = []
    for (desde, hasta), campanas in grupos.items():
        if len(campanas) < 2:
            continue
        nombres = [f["nombre"] for f in campanas]
        base = _palabras_comunes(nombres) or f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
        distintos = len({nombre_normalizado(n) for n in nombres})
        salida.append(
            {"base": base, "fecha_desde": desde, "fecha_hasta": hasta, "nombres": distintos, "campanas": campanas}
        )
    return sorted(salida, key=lambda g: (-len(g["campanas"]), g["fecha_desde"], g["fecha_hasta"]))
