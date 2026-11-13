"""The shipping cost a PM chooses for a product (S7b): the options to choose from, and the stored choice.

The rules (what each mode resolves to, the 30-day window of a stored `ponderado`, the MAX fallback of an unusable
`mla`) live in `app.services.envio_real_service`, which applies them for every pricing caller; this module only
lays them out for the Publicaciones ML product view and records the choice. Every helper is called through the
`envio` module, so the tests stub the mlwebhook read and the units sold in one place.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.auditoria import Auditoria, TipoAccion
from app.models.ml_publications import MlItem
from app.models.producto import ProductoERP
from app.models.producto_envio_eleccion import ProductoEnvioEleccion
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import Usuario
from app.services import envio_real_service as envio


class CostosNoDisponibles(RuntimeError):
    """The mlwebhook read of the publications' shipping costs failed."""


class EleccionInvalida(ValueError):
    """A choice that cannot be stored; `field` is the body field at fault."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _envio_erp(db: Session, item_id: int) -> tuple[bool, Optional[float]]:
    """(the product exists, its ERP envio)."""
    row = db.execute(select(ProductoERP.envio).where(ProductoERP.item_id == item_id)).first()
    return (row is not None, None if row is None else row[0])


def _store_kinds(db: Session, mlas: list[str]) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """(listing type, logistic type) of each MLA the publications store has read, in ONE statement."""
    if not mlas:
        return {}
    with db.no_autoflush:  # a read-only lookup: never flush the caller's pending objects
        rows = db.execute(
            select(MlItem.item_id, MlItem.listing_type_id, MlItem.logistic_type).where(MlItem.item_id.in_(mlas))
        ).all()
    return {mla: (tipo, logistica) for mla, tipo, logistica in rows}


def _warning(mla: Optional[str]) -> str:
    return (
        f"La publicación {mla} elegida no está activa o no tiene costo de envío en Mercado Libre: "
        "se usa el máximo de las publicaciones activas."
    )


def opciones_envio(db: Session, item_id: int, date_from: date, date_to: date) -> Optional[dict[str, Any]]:
    """What the PM chooses from, for the period `[date_from, date_to]`; None for an unknown product.

    Every active publication with its own cost (None without one) and its units sold in the period, the most sold
    flagged (every one tied at the top, none without sales); `promedio`, `ponderado` (None without sales in the
    period) and `max` over the active publications that have a cost; and the stored choice with the cost it
    resolves to NOW (a `ponderado` choice with the last 30 days, as the resolvers do) and a `warning` when a chosen
    publication fell back to the MAX.

    A failed mlwebhook read raises `CostosNoDisponibles`: an empty list would look like "no costs" to the PM.
    """
    exists, envio_erp = _envio_erp(db, item_id)
    if not exists:
        return None
    mlas = envio.mlas_activas(db, item_id)
    try:
        own = envio.costos_envio_por_mla(mlas, db=db) if mlas else {}
    except Exception as exc:  # any driver/connection error of the other database: told apart from "no costs"
        raise CostosNoDisponibles(str(exc)) from exc
    costs = {mla: own[mla] for mla in mlas if mla in own}
    units = envio.unidades_vendidas_por_mla(db, mlas, date_from, date_to) if mlas else {}
    top = max(units.values(), default=0)
    kinds = _store_kinds(db, mlas)
    publicaciones = sorted(
        (
            {
                "mla": mla,
                "costo": own.get(mla),
                "unidades": units.get(mla, 0),
                "mas_vendida": 0 < top == units.get(mla),
                "tipo": kinds.get(mla, (None, None))[0],
                "logistica": kinds.get(mla, (None, None))[1],
            }
            for mla in mlas
        ),
        key=lambda row: (-row["unidades"], row["mla"]),
    )

    with db.no_autoflush:
        row = db.execute(
            select(ProductoEnvioEleccion, Usuario.nombre)
            .outerjoin(Usuario, Usuario.id == ProductoEnvioEleccion.usuario_id)
            .where(ProductoEnvioEleccion.item_id == item_id)
        ).first()
    stored, usuario_nombre = (row[0], row[1]) if row is not None else (None, None)
    modo = stored.modo if stored is not None else envio.MODO_DEFAULT
    mla = stored.mla if stored is not None else None
    units_now = units
    if modo == "ponderado" and mlas and (date_from, date_to) != envio.periodo_ponderado():
        units_now = envio.unidades_vendidas_por_mla(db, mlas, *envio.periodo_ponderado())
    resolved = envio.costo_envio_elegido(modo, mla, costs, units_now)
    return {
        "item_id": item_id,
        "date_from": date_from,
        "date_to": date_to,
        "publicaciones": publicaciones,
        "promedio": envio.costo_promedio(costs),
        "ponderado": envio.costo_ponderado(costs, units),
        "max": max(costs.values(), default=None),
        "eleccion": {
            "modo": modo,
            "mla": mla,
            "costo": resolved if resolved is not None else float(envio_erp or 0.0),
            "warning": _warning(mla) if costs and envio.eleccion_cae_a_maximo(modo, mla, costs) else None,
            "usuario_id": stored.usuario_id if stored is not None else None,
            "usuario_nombre": usuario_nombre,
            "updated_at": stored.updated_at if stored is not None else None,
        },
    }


def guardar_eleccion(
    db: Session, item_id: int, modo: str, mla: Optional[str], *, usuario_id: int
) -> Optional[dict[str, Any]]:
    """Store the choice of `item_id` (one row per product, replaced), with who and when; None for an unknown
    product. `max` is stored as a row too, so who chose it and when stays recorded. Every change also writes one
    `auditoria` row (before -> after) in the same transaction (L12). The caller commits.

    Raises `EleccionInvalida` for an `mla` that is not a publication of the product (active or not: a paused one
    may come back; while it is inactive the product resolves to the MAX and the options warn)."""
    if modo not in envio.MODOS_ENVIO:
        raise EleccionInvalida("modo", f"modo debe ser uno de {', '.join(envio.MODOS_ENVIO)}")
    if (modo == "mla") != (mla is not None):
        raise EleccionInvalida("mla", "mla va solo, y siempre, con modo = mla")
    # The product's row, locked until the caller commits: saves of the same product run one after the other, so the
    # audit's `before` below is always the previous save's choice (also when neither had a stored row yet), L22.
    locked = db.execute(select(ProductoERP.item_id).where(ProductoERP.item_id == item_id).with_for_update()).first()
    if locked is None:
        return None
    if mla is not None:
        belongs = db.execute(
            select(PublicacionML.mla).where(PublicacionML.mla == mla, PublicacionML.item_id == item_id).limit(1)
        ).first()
        if belongs is None:
            raise EleccionInvalida("mla", f"La publicación {mla} no es de este producto")
    previous = db.execute(
        select(ProductoEnvioEleccion.modo, ProductoEnvioEleccion.mla).where(ProductoEnvioEleccion.item_id == item_id)
    ).first()
    before = (
        {"modo": previous.modo, "mla": previous.mla}
        if previous is not None
        else {"modo": envio.MODO_DEFAULT, "mla": None}
    )
    after = {"modo": modo, "mla": mla}
    if before != after:  # L12: every change, who and when, in the choice's own transaction
        db.add(
            Auditoria(
                item_id=item_id,
                usuario_id=usuario_id,
                tipo_accion=TipoAccion.ENVIO_PRODUCTO_ELECCION,
                valores_anteriores=before,
                valores_nuevos=after,
                fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
            )
        )
    values = {"item_id": item_id, "modo": modo, "mla": mla, "usuario_id": usuario_id, "updated_at": func.now()}
    statement = insert(ProductoEnvioEleccion).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[ProductoEnvioEleccion.item_id],
        set_={key: statement.excluded[key] for key in ("modo", "mla", "usuario_id", "updated_at")},
    ).returning(ProductoEnvioEleccion.updated_at)
    updated_at: datetime = db.execute(statement).scalar_one()
    return {"item_id": item_id, "modo": modo, "mla": mla, "usuario_id": usuario_id, "updated_at": updated_at}
