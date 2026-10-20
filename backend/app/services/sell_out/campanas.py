"""Sell-out campaigns: validate, load, edit, list, detail and void.

`validar` is the single place for the rules the database CHECKs also enforce
(`app.models.sell_out`), so the operator gets one readable message instead of
an integrity error. A campaign is edited by full replace while it is `activa`;
it is never deleted, only voided (`anulada`), once. Every load, edit and void
writes one audit row (`item_id` NULL, `campana_id` in the values).

Consumption, the shared cap, stacking and the ARS conversion (including the
current-BNA estimate of an `al_cobro` campaign whose rate is not set yet) are
applied by the allocator (T7); this module only stores them. The payment rate
of an `al_cobro` campaign is set with `definir_tipo_cambio`, never by an edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import TypeAdapter
from sqlalchemy import Numeric, or_
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo
from app.schemas.sell_out import SellOutCampanaIn
from app.services.sell_in.compras import contiene

# Each NUMERIC column's scale as a quantum: `monto_unit` 0.01, `porcentaje` 0.0001, ...
_QUANTUM = {
    column.name: Decimal(1).scaleb(-column.type.scale)
    for column in SellOutCampana.__table__.columns
    if isinstance(column.type, Numeric)
}
_INSTANTE = TypeAdapter(datetime)

_CAMPOS = (
    "nombre",
    "descripcion",
    "fecha_desde",
    "fecha_hasta",
    "tipo",
    "monto_unit",
    "porcentaje",
    "base_porcentaje",
    "moneda",
    "tc_modo",
    "tipo_cambio",
    "tope_unidades",
    "tope_monto",
    "acumulable",
)


class SellOutError(ValueError):
    """The request cannot be served as asked; the message is for the operator."""


class SellOutYaAnulada(SellOutError):
    """The campaign was already voided."""


def _validar_tc(data: SellOutCampanaIn, actual: Optional[SellOutCampana]) -> None:
    """FX rules (see `app.models.sell_out`); `data.tc_modo` is already resolved."""
    if data.moneda == "ARS":
        if data.tc_modo is not None or data.tipo_cambio is not None:
            raise SellOutError("Una campaña en pesos no lleva tipo de cambio")
        return
    if data.tipo_cambio is not None and data.tipo_cambio <= 0:
        raise SellOutError("El tipo de cambio tiene que ser mayor a 0")
    if data.tc_modo == "fijo" and data.tipo_cambio is None:
        raise SellOutError("Con tipo de cambio fijo hay que indicar el tipo de cambio")
    if data.tc_modo == "dia_venta" and data.tipo_cambio is not None:
        raise SellOutError("Con tipo de cambio del día de venta no se indica un tipo de cambio")
    if data.tc_modo == "al_cobro" and data.tipo_cambio is not None:
        # An edit may echo the rate already set at payment; changing it goes through its own endpoint.
        ya_definido = actual is not None and actual.tc_modo == "al_cobro" and actual.tipo_cambio == data.tipo_cambio
        if not ya_definido:
            raise SellOutError(
                "Con tipo de cambio al cobro, el tipo de cambio se define cuando la marca paga, desde su propia acción"
            )


def validar(db: Session, data: SellOutCampanaIn, actual: Optional[SellOutCampana] = None) -> list[int]:
    """Raise `SellOutError` on the first broken rule; return the campaign's distinct group ids, in order.

    A USD campaign without `tc_modo` gets `al_cobro` (the default), set on `data` in place.
    """
    if not data.nombre.strip():
        raise SellOutError("El nombre es obligatorio")
    if data.fecha_hasta < data.fecha_desde:
        raise SellOutError("La fecha hasta no puede ser anterior a la fecha desde")
    if data.tipo == "por_unidad":
        if data.monto_unit is None or data.monto_unit <= 0:
            raise SellOutError("Una campaña por unidad necesita un monto por unidad mayor a 0")
        if data.porcentaje is not None:
            raise SellOutError("Una campaña por unidad no lleva porcentaje")
    else:
        if data.porcentaje is None or not 0 < data.porcentaje <= 100:
            raise SellOutError("El porcentaje tiene que ser mayor a 0 y hasta 100")
        if data.monto_unit is not None:
            raise SellOutError("Una campaña por porcentaje no lleva monto por unidad")
    if data.moneda == "USD" and data.tc_modo is None:
        data.tc_modo = "al_cobro"
    _validar_tc(data, actual)
    if data.tope_unidades is not None and data.tope_unidades <= 0:
        raise SellOutError("El tope de unidades tiene que ser mayor a 0")
    if data.tope_monto is not None and data.tope_monto <= 0:
        raise SellOutError("El tope de monto tiene que ser mayor a 0")

    grupo_ids = list(dict.fromkeys(data.grupo_ids))
    if not grupo_ids:
        raise SellOutError("Seleccione al menos un grupo de productos")
    existentes = {gid for (gid,) in db.query(OffsetGrupo.id).filter(OffsetGrupo.id.in_(grupo_ids))}
    for gid in grupo_ids:
        if gid not in existentes:
            raise SellOutError(f"El grupo {gid} no existe")
    return grupo_ids


def _a_escala(campo: str, valor):
    """`valor` rounded to its column's scale, as the database stores it (exact: the schema caps decimals)."""
    if campo in _QUANTUM and valor is not None:
        return valor.quantize(_QUANTUM[campo])
    return valor


def _utc(instante: Optional[datetime]) -> Optional[datetime]:
    """A `timestamptz` value in UTC; a naive one (SQLite drops the zone) is already UTC."""
    if instante is None:
        return None
    if instante.tzinfo is None:
        return instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc)


def _valores(campana: SellOutCampana, grupo_ids: list[int]) -> dict:
    valores = {campo: getattr(campana, campo) for campo in _CAMPOS}
    for campo, valor in valores.items():
        if valor is not None and not isinstance(valor, (bool, int, str)):
            valores[campo] = str(valor)  # dates and decimals, JSON-safe
    # Serialized exactly as the API returns it (see `serializar`).
    definido = _INSTANTE.dump_python(_utc(campana.tc_definido_en), mode="json") if campana.tc_definido_en else None
    return {
        "campana_id": campana.id,
        **valores,
        "tc_definido_en": definido,
        "estado": campana.estado,
        "grupo_ids": grupo_ids,
    }


def _grupo_ids(db: Session, campana_id: int) -> list[int]:
    rows = db.query(SellOutCampanaGrupo.grupo_id).filter(SellOutCampanaGrupo.campana_id == campana_id)
    return [gid for (gid,) in rows.order_by(SellOutCampanaGrupo.id)]


def _audit(db: Session, tipo: TipoAccion, usuario_id: int, antes: Optional[dict], despues: dict, motivo=None) -> None:
    db.add(
        Auditoria(
            item_id=None,
            usuario_id=usuario_id,
            tipo_accion=tipo,
            valores_anteriores=antes,
            valores_nuevos=despues,
            es_masivo=0,
            comentario=motivo,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )


def _asignar(db: Session, campana: SellOutCampana, data: SellOutCampanaIn, grupo_ids: list[int]) -> None:
    previo = (campana.tc_modo, campana.tipo_cambio, campana.tc_definido_en)
    for campo in _CAMPOS:
        setattr(campana, campo, _a_escala(campo, getattr(data, campo)))
    if campana.tc_modo == "al_cobro" and previo[0] == "al_cobro":
        campana.tipo_cambio, campana.tc_definido_en = previo[1], previo[2]  # an edit keeps the payment rate
    else:
        campana.tc_definido_en = None
    campana.nombre = data.nombre.strip()
    db.flush()
    db.query(SellOutCampanaGrupo).filter(
        SellOutCampanaGrupo.campana_id == campana.id, SellOutCampanaGrupo.grupo_id.notin_(grupo_ids)
    ).delete(synchronize_session=False)
    tenidos = set(_grupo_ids(db, campana.id))
    db.add_all(SellOutCampanaGrupo(campana_id=campana.id, grupo_id=g) for g in grupo_ids if g not in tenidos)
    db.flush()


def crear_campana(db: Session, data: SellOutCampanaIn, usuario_id: int) -> SellOutCampana:
    grupo_ids = validar(db, data)
    campana = SellOutCampana(usuario_id=usuario_id)
    db.add(campana)
    _asignar(db, campana, data, grupo_ids)
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_CREADA, usuario_id, None, _valores(campana, grupo_ids))
    db.commit()
    db.refresh(campana)
    return campana


def _bloquear(db: Session, campana_id: int) -> Optional[SellOutCampana]:
    campana = db.query(SellOutCampana).filter(SellOutCampana.id == campana_id).with_for_update().first()
    if campana is not None and campana.estado == "anulada":
        raise SellOutYaAnulada(f"La campaña {campana_id} está anulada")
    return campana


def editar_campana(db: Session, campana_id: int, data: SellOutCampanaIn, usuario_id: int) -> Optional[SellOutCampana]:
    """Full replace of an active campaign. None when it does not exist; `SellOutYaAnulada` when voided."""
    campana = _bloquear(db, campana_id)
    if campana is None:
        return None
    grupo_ids = validar(db, data, campana)
    antes = _valores(campana, _grupo_ids(db, campana_id))
    _asignar(db, campana, data, grupo_ids)
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_EDITADA, usuario_id, antes, _valores(campana, grupo_ids))
    db.commit()
    db.refresh(campana)
    return campana


def anular_campana(db: Session, campana_id: int, usuario_id: int, motivo: Optional[str]) -> Optional[SellOutCampana]:
    """Void a campaign. None when it does not exist; `SellOutYaAnulada` on a second call."""
    campana = _bloquear(db, campana_id)
    if campana is None:
        return None
    campana.estado = "anulada"
    _audit(
        db, TipoAccion.SELL_OUT_CAMPANA_ANULADA, usuario_id, None, _valores(campana, _grupo_ids(db, campana_id)), motivo
    )
    db.commit()
    db.refresh(campana)
    return campana


def definir_tipo_cambio(
    db: Session, campana_id: int, tipo_cambio: Decimal, usuario_id: int
) -> Optional[SellOutCampana]:
    """Set (or change) the rate of an `al_cobro` campaign when the brand pays, also after it ended.

    None when it does not exist; `SellOutYaAnulada` when voided. Every change is audited; T7 recomputes.
    """
    campana = _bloquear(db, campana_id)
    if campana is None:
        return None
    if campana.tc_modo != "al_cobro":
        raise SellOutError("Solo las campañas en USD con tipo de cambio al cobro definen el tipo de cambio después")
    if tipo_cambio <= 0:
        raise SellOutError("El tipo de cambio tiene que ser mayor a 0")
    grupo_ids = _grupo_ids(db, campana_id)
    antes = _valores(campana, grupo_ids)
    campana.tipo_cambio = _a_escala("tipo_cambio", tipo_cambio)
    campana.tc_definido_en = datetime.now(timezone.utc)
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_TC_DEFINIDO, usuario_id, antes, _valores(campana, grupo_ids))
    db.commit()
    db.refresh(campana)
    return campana


@dataclass(frozen=True)
class FiltrosCampanas:
    estado: Optional[str] = None
    vigente_en: Optional[date] = None  # campaigns whose date range includes this day
    q: Optional[str] = None  # name or description
    grupo_id: Optional[int] = None
    tipo: Optional[str] = None


def listar_campanas(
    db: Session, filtros: FiltrosCampanas, *, page: int = 1, page_size: int = 50
) -> tuple[list[SellOutCampana], int]:
    """One page of campaigns, latest start date first."""
    query = db.query(SellOutCampana)
    if filtros.estado:
        query = query.filter(SellOutCampana.estado == filtros.estado)
    if filtros.tipo:
        query = query.filter(SellOutCampana.tipo == filtros.tipo)
    if filtros.vigente_en:
        query = query.filter(
            SellOutCampana.fecha_desde <= filtros.vigente_en, SellOutCampana.fecha_hasta >= filtros.vigente_en
        )
    if filtros.q and filtros.q.strip():
        q = filtros.q.strip()
        query = query.filter(or_(contiene(SellOutCampana.nombre, q), contiene(SellOutCampana.descripcion, q)))
    if filtros.grupo_id is not None:
        en_grupo = db.query(SellOutCampanaGrupo.campana_id).filter(SellOutCampanaGrupo.grupo_id == filtros.grupo_id)
        query = query.filter(SellOutCampana.id.in_(en_grupo))
    total = query.count()
    campanas = (
        query.order_by(SellOutCampana.fecha_desde.desc(), SellOutCampana.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return campanas, total


def serializar(db: Session, campanas: list[SellOutCampana]) -> list[dict]:
    """Each campaign with its groups (id and name, in link order), in one query for the whole page."""
    ids = [c.id for c in campanas]
    grupos: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        rows = (
            db.query(SellOutCampanaGrupo.campana_id, OffsetGrupo.id, OffsetGrupo.nombre)
            .join(OffsetGrupo, OffsetGrupo.id == SellOutCampanaGrupo.grupo_id)
            .filter(SellOutCampanaGrupo.campana_id.in_(ids))
            .order_by(SellOutCampanaGrupo.id)
        )
        for campana_id, gid, nombre in rows:
            grupos[campana_id].append({"id": gid, "nombre": nombre})
    salida = []
    for c in campanas:
        fila = {campo: getattr(c, campo) for campo in _CAMPOS}
        fila.update(
            tc_definido_en=_utc(c.tc_definido_en),
            id=c.id,
            estado=c.estado,
            usuario_id=c.usuario_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        fila["grupos"] = grupos[c.id]
        salida.append(fila)
    return salida
