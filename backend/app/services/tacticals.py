"""Tacticals: create, list, detail and void (tacticals T1; contract in `handoffs/tactical-tarea.md` "Contrato final").

A tactical (`app.models.tactical`) is a header; each line of it becomes rows of the EXISTING engines, created through
their own create steps (same validation, audit rows and queueing), so allocation, FIFO and caps are not rewritten:

- sell out (productos | marca | categoria): one `SellOutCampana` over its own hidden group (`OffsetGrupo.oculto`)
  whose filter rows carry the line's scope. `tope_por_producto`: one campaign and group per product.
- sell in over productos | marca | categoria: one cost bonus (`SellInBonoMarca`, `base = 'costo_venta'`, ARS), a %
  or an amount per unit of each sale's cost by sale date. `tope_por_producto`: one bonus per product.
- sell in `factura` with % or per unit: one invoice bonus (`alcance = base = 'factura'`) on that operation.
- sell in `factura` with a fixed total: one sell-in purchase (`SellInCompra`, monto, proporcional) over the invoice's
  invoiced lines.

Every child carries `tactical_id` and `tactical_linea` (its 1-based line). The header's dates, currency, FX, VAT flag
and `acumulable` are copied to every child, which is what the engines read, except where an engine has its own: an
invoice line converts at its operation's rate (a fixed rate is refused there) and a cost bonus is ARS.

One atomic create: the header and every child in one transaction; the first refused line rolls everything back and
comes back as `TacticalError` with "Línea N: ..." (the engine's own message after it). A campaign whose queue row a
running drain holds is `TacticalOcupado` (retry). Voiding a tactical voids every active child through its engine's
own void step, in one transaction.

The read returns one line per child (T5: a per-product line is one line per product), each with what it used: a
campaign's consumptions, a cost bonus's sales rows (ARS), what an invoice bonus generated, and the sales that
consumed an invoice total (converted to its currency at its own rate).
"""

from __future__ import annotations

import functools
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem, SellInCompraPedido, SellInConsumo
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo, SellOutConsumo
from app.models.tactical import Tactical
from app.schemas.sell_in import SellInCompraCreate, SellInLineaIn
from app.schemas.sell_in_bonos import BASE_COSTO_VENTA, BASE_FACTURA, SellInBonoIn
from app.schemas.sell_out import SellOutCampanaIn
from app.schemas.tacticals import TacticalIn, TacticalLineaIn
from app.services.sell_in import bonos_crud, compras
from app.services.sell_in.compras import contiene
from app.services.sell_out import campanas

GRUPO_NOMBRE_MAX = 100  # offset_grupos.nombre is VARCHAR(100)
CAMPANA_NOMBRE_MAX = 200
CENTAVO = Decimal("0.01")


class TacticalError(ValueError):
    """A rule the operator broke: 422 with this message."""


class TacticalOcupado(TacticalError):
    """A campaign of the tactical is being recomputed: 409, retry; nothing stored."""


class TacticalYaAnulado(TacticalError):
    pass


def _texto(valor: Optional[str]) -> Optional[str]:
    return (valor or "").strip() or None


def _fecha(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _audit(db: Session, tipo: TipoAccion, usuario_id: int, valores: dict, motivo: Optional[str] = None) -> None:
    db.add(
        Auditoria(
            item_id=None,
            usuario_id=usuario_id,
            tipo_accion=tipo,
            valores_anteriores=None,
            valores_nuevos=valores,
            es_masivo=False,
            comentario=motivo,
        )
    )


# --- header -------------------------------------------------------------------------------------------------------


def _validar_cabecera(db: Session, data: TacticalIn) -> tuple[str, str, Optional[str]]:
    """The header's rules; returns `(nombre, marca, tc_modo)` normalized (USD without a mode is `al_cobro`)."""
    nombre, marca = _texto(data.nombre), _texto(data.marca)
    if nombre is None:
        raise TacticalError("El nombre es obligatorio")
    if marca is None:
        raise TacticalError("La marca es obligatoria")
    if not db.query(ProductoERP.item_id).filter(ProductoERP.marca == marca).limit(1).first():
        raise TacticalError(f"No hay productos de la marca {marca}")
    if data.fecha_hasta < data.fecha_desde:
        raise TacticalError("La fecha hasta no puede ser anterior a la fecha desde")
    if data.moneda == "ARS":
        if data.tc_modo is not None or data.tipo_cambio is not None:
            raise TacticalError("Un tactical en pesos no lleva tipo de cambio")
        return nombre, marca, None
    tc_modo = data.tc_modo or "al_cobro"
    if tc_modo == "fijo":
        if data.tipo_cambio is None or data.tipo_cambio <= 0:
            raise TacticalError("Con tipo de cambio fijo hay que indicar el tipo de cambio, mayor a 0")
    elif data.tipo_cambio is not None:
        raise TacticalError("Solo con tipo de cambio fijo se indica el tipo de cambio")
    return nombre, marca, tc_modo


# --- lines --------------------------------------------------------------------------------------------------------

_CAMPO = {"productos": "item_ids", "marca": "marca", "categoria": "categoria", "factura": "pedido_compra_id"}
_NOMBRE_CAMPO = {"item_ids": "productos", "marca": "marca", "categoria": "categoría", "pedido_compra_id": "factura"}


@dataclass(frozen=True)
class _Alcance:
    item_ids: tuple[int, ...] = ()
    marca: Optional[str] = None
    categoria: Optional[str] = None
    pedido: Optional[Any] = None  # row of (id, numero, fecha_factura, tipo_cambio)


def _validar_linea(db: Session, data: TacticalIn, linea: TacticalLineaIn) -> _Alcance:
    """The scope and amount rules every line shares; the engine-specific ones come with its mapping."""
    dados = {
        "item_ids": linea.item_ids,
        "marca": _texto(linea.marca),
        "categoria": _texto(linea.categoria),
        "pedido_compra_id": linea.pedido_compra_id,
    }
    propio = _CAMPO[linea.alcance]
    for campo, valor in dados.items():
        if campo != propio and valor:
            raise TacticalError(f"una línea por {linea.alcance} no lleva {_NOMBRE_CAMPO[campo]}")
    if linea.tope_por_producto and linea.alcance != "productos":
        raise TacticalError("el tope por producto es solo para una línea de productos")
    if linea.valor <= 0:
        raise TacticalError("el monto tiene que ser mayor a 0")
    if linea.modo_monto == "porcentaje" and linea.valor > 100:
        raise TacticalError("el porcentaje no puede superar 100")
    if linea.alcance == "productos":
        ids = tuple(dict.fromkeys(linea.item_ids))
        if not ids:
            raise TacticalError("elegí al menos un producto")
        existen = {i for (i,) in db.query(ProductoERP.item_id).filter(ProductoERP.item_id.in_(ids))}
        faltan = [str(i) for i in ids if i not in existen]
        if faltan:
            raise TacticalError(f"no existen los productos {', '.join(faltan)}")
        return _Alcance(item_ids=ids)
    if linea.alcance == "marca":
        if dados["marca"] is None:
            raise TacticalError("falta la marca")
        if not db.query(ProductoERP.item_id).filter(ProductoERP.marca == dados["marca"]).limit(1).first():
            raise TacticalError(f"no hay productos de la marca {dados['marca']}")
        return _Alcance(marca=dados["marca"])
    if linea.alcance == "categoria":
        if dados["categoria"] is None:
            raise TacticalError("falta la categoría")
        if not db.query(ProductoERP.item_id).filter(ProductoERP.categoria == dados["categoria"]).limit(1).first():
            raise TacticalError(f"no hay productos de la categoría {dados['categoria']}")
        return _Alcance(categoria=dados["categoria"])
    if data.tipo != "sell_in":
        raise TacticalError("una línea por factura es solo de sell in")
    if linea.pedido_compra_id is None:
        raise TacticalError("falta la factura")
    pedido = (  # only what a line reads: number, invoice date and rate
        db.query(PedidoCompra.id, PedidoCompra.numero, PedidoCompra.fecha_factura, PedidoCompra.tipo_cambio)
        .filter(PedidoCompra.id == linea.pedido_compra_id)
        .first()
    )
    if pedido is None:
        raise TacticalError(f"no existe la factura {linea.pedido_compra_id}")
    if pedido.fecha_factura is None:
        raise TacticalError(f"la operación {pedido.numero} no tiene fecha de factura")
    if not data.fecha_desde <= pedido.fecha_factura <= data.fecha_hasta:
        raise TacticalError(
            f"la factura de la operación {pedido.numero} es del {_fecha(pedido.fecha_factura)}, fuera de la vigencia"
        )
    return _Alcance(pedido=pedido)


def _partes(linea: TacticalLineaIn, alcance: _Alcance) -> list[_Alcance]:
    """One scope per child: each product alone on a per-product line, the whole scope otherwise."""
    if linea.tope_por_producto:
        return [_Alcance(item_ids=(i,)) for i in alcance.item_ids]
    return [alcance]


def _nombre(tactical: Tactical, numero: int, parte: _Alcance, codigos: dict[int, str], maximo: int) -> str:
    nombre = f"{tactical.nombre} · línea {numero}"
    if len(parte.item_ids) == 1:
        nombre += f" · {codigos.get(parte.item_ids[0], parte.item_ids[0])}"
    return nombre[:maximo]


def _grupo_oculto(db: Session, tactical: Tactical, nombre: str, parte: _Alcance, usuario_id: int) -> int:
    """The hidden group of one sell-out child: its filter rows ARE the line's scope."""
    grupo = OffsetGrupo(nombre=nombre[:GRUPO_NOMBRE_MAX], usuario_id=usuario_id, oculto=True)
    db.add(grupo)
    db.flush()
    if parte.item_ids:
        db.add_all(OffsetGrupoFiltro(grupo_id=grupo.id, item_id=i) for i in parte.item_ids)
    else:
        db.add(OffsetGrupoFiltro(grupo_id=grupo.id, marca=parte.marca, categoria=parte.categoria))
    db.flush()
    return grupo.id


def _sell_out(db, tactical, data, linea, numero, parte, codigos, usuario_id) -> None:
    nombre = _nombre(tactical, numero, parte, codigos, CAMPANA_NOMBRE_MAX)
    grupo_id = _grupo_oculto(db, tactical, nombre, parte, usuario_id)
    valor = {"por_unidad": "monto_unit", "porcentaje": "porcentaje", "monto_total": "monto_total"}[linea.modo_monto]
    entrada = SellOutCampanaIn(
        nombre=nombre,
        fecha_desde=data.fecha_desde,
        fecha_hasta=data.fecha_hasta,
        tipo=linea.modo_monto,
        **{valor: linea.valor},
        moneda=data.moneda,
        tc_modo=tactical.tc_modo,
        tipo_cambio=data.tipo_cambio,
        tope_unidades=linea.tope_unidades,
        tope_monto=linea.tope_monto,
        acumulable=data.acumulable,
        # A percentage applies on the net without VAT already: the flag means nothing there (and is refused).
        monto_incluye_iva=data.incluye_iva and linea.modo_monto != "porcentaje",
        grupo_ids=[grupo_id],
    )
    campanas.crear_campana_sin_commit(db, entrada, usuario_id, tactical=(tactical.id, numero))


def _sell_in(db, tactical, data, linea, numero, parte, codigos, usuario_id) -> None:
    descripcion = _nombre(tactical, numero, parte, codigos, CAMPANA_NOMBRE_MAX)
    if parte.pedido is not None and linea.modo_monto == "monto_total":
        _total_de_factura(db, tactical, data, linea, numero, parte.pedido, descripcion, usuario_id)
        return
    if parte.pedido is not None:
        if data.incluye_iva:
            raise TacticalError("una línea por factura no lleva montos con IVA: va sobre el neto facturado")
        if tactical.tc_modo == "fijo":
            raise TacticalError(
                "un % o monto por unidad sobre una factura usa el tipo de cambio de la operación: no lleva tipo de "
                "cambio fijo"
            )
        campos = {"alcance": "factura", "pedido_id": parte.pedido.id, "moneda": data.moneda, "base": BASE_FACTURA}
    else:
        if linea.modo_monto == "monto_total":
            raise TacticalError("en sell in, el monto total es solo para una línea por factura")
        if data.moneda != "ARS" and (linea.modo_monto == "por_unidad" or linea.tope_monto is not None):
            raise TacticalError(
                "una reducción de costo por unidad o con tope de monto va en pesos (ARS): el costo de cada venta "
                "está en pesos"
            )
        alcance = "modelos" if parte.item_ids else ("marca" if parte.marca else "categoria")
        campos = {
            "alcance": alcance,
            "marca": parte.marca,
            "categoria": parte.categoria,
            "modelos": list(parte.item_ids),
            "moneda": "ARS",
            "base": BASE_COSTO_VENTA,
            "incluye_iva": data.incluye_iva,
        }
    entrada = SellInBonoIn(
        **campos,
        tipo=linea.modo_monto,
        monto_unit=linea.valor if linea.modo_monto == "por_unidad" else None,
        porcentaje=linea.valor if linea.modo_monto == "porcentaje" else None,
        fecha_desde=data.fecha_desde,
        fecha_hasta=data.fecha_hasta,
        descripcion=descripcion,
        tope_unidades=linea.tope_unidades,
        tope_monto=linea.tope_monto,
        acumulable=data.acumulable,
    )
    bonos_crud.crear_bono_sin_commit(db, entrada, usuario_id, tactical=(tactical.id, numero))


def _total_de_factura(db, tactical, data, linea, numero, pedido, descripcion, usuario_id) -> None:
    """An invoice's fixed total: a sell-in purchase split over its invoiced lines (`proporcional`)."""
    if linea.tope_unidades is not None or linea.tope_monto is not None:
        raise TacticalError("un monto total no lleva topes: el monto total es el tope")
    if data.moneda == "USD" and tactical.tc_modo != "fijo":
        raise TacticalError("un monto total en USD necesita tipo de cambio fijo")
    t = PedidoCompraLineaFacturada
    cantidades = [
        (int(item_id), int(cantidad))
        for item_id, cantidad in db.query(t.item_id, func.sum(t.cantidad))
        .filter(t.pedido_id == pedido.id)
        .group_by(t.item_id)
        .having(func.sum(t.cantidad) > 0)
        .order_by(t.item_id)
    ]
    if not cantidades:
        raise TacticalError(f"la factura de la operación {pedido.numero} no tiene líneas facturadas")
    entrada = SellInCompraCreate(
        moneda=data.moneda,
        tipo="monto",
        monto_total=linea.valor,
        # USD: the tactical's fixed rate. ARS: the operation's own rate, which converts a product cost kept in USD
        # (the engine refuses a USD cost without one).
        tipo_cambio=data.tipo_cambio if data.moneda == "USD" else pedido.tipo_cambio,
        formula="proporcional",
        lineas=[SellInLineaIn(item_id=i, cantidad=c) for i, c in cantidades],
        pedido_compra_ids=[pedido.id],
        fecha_compra=pedido.fecha_factura,
        descripcion=descripcion,
    )
    compras.crear_compra_sin_commit(db, entrada, usuario_id, tactical=(tactical.id, numero))


def _ocupado_si_deadlock(operacion):
    """A deadlock (40P01) with another writer of a campaign is `TacticalOcupado` (rolled back, retry), never a raw
    error: the engines' own wrapper (`campanas.deadlock_es_ocupada`), with this module's error."""

    @campanas.deadlock_es_ocupada
    def con_rollback(db: Session, *args, **kwargs):
        return operacion(db, *args, **kwargs)

    @functools.wraps(operacion)
    def envuelta(db: Session, *args, **kwargs):
        try:
            return con_rollback(db, *args, **kwargs)
        except campanas.SellOutRecalculando as exc:
            raise TacticalOcupado(str(exc)) from exc

    return envuelta


@_ocupado_si_deadlock
def crear(db: Session, data: TacticalIn, usuario_id: int) -> Tactical:
    """The header and every child, all or nothing (module docstring); commits."""
    try:
        tactical = _crear(db, data, usuario_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(tactical)
    return tactical


def _crear(db: Session, data: TacticalIn, usuario_id: int) -> Tactical:
    nombre, marca, tc_modo = _validar_cabecera(db, data)
    tactical = Tactical(
        tipo=data.tipo,
        nombre=nombre,
        marca=marca,
        referencia=_texto(data.referencia),
        fecha_desde=data.fecha_desde,
        fecha_hasta=data.fecha_hasta,
        moneda=data.moneda,
        tc_modo=tc_modo,
        tipo_cambio=data.tipo_cambio,
        incluye_iva=data.incluye_iva,
        acumulable=data.acumulable,
        nota=_texto(data.nota),
        estado="activo",
        usuario_id=usuario_id,
    )
    db.add(tactical)
    db.flush()
    todos = {i for linea in data.lineas for i in linea.item_ids}
    codigos = dict(db.query(ProductoERP.item_id, ProductoERP.codigo).filter(ProductoERP.item_id.in_(todos)))
    crear_hijo = _sell_out if data.tipo == "sell_out" else _sell_in
    for numero, linea in enumerate(data.lineas, start=1):
        try:
            alcance = _validar_linea(db, data, linea)
            for parte in _partes(linea, alcance):
                crear_hijo(db, tactical, data, linea, numero, parte, codigos, usuario_id)
        except campanas.SellOutRecalculando as exc:
            raise TacticalOcupado(f"Línea {numero}: {exc}") from exc
        except ValidationError as exc:  # an engine's input schema refused a value the tactical's own did not check
            mensaje = str(exc.errors()[0].get("msg", "un valor no es válido")).removeprefix("Value error, ")
            raise TacticalError(f"Línea {numero}: {_sin_mayuscula(mensaje)}") from exc
        except ValueError as exc:  # TacticalError and every engine's refusal (SellOutError, SellInBonoError, ...)
            raise TacticalError(f"Línea {numero}: {_sin_mayuscula(str(exc))}") from exc
    _audit(db, TipoAccion.TACTICAL_CREADO, usuario_id, {"tactical_id": tactical.id, **_cabecera(tactical)})
    return tactical


def _sin_mayuscula(mensaje: str) -> str:
    return mensaje[:1].lower() + mensaje[1:] if mensaje[:2] != mensaje[:2].upper() else mensaje


def _cabecera(t: Tactical) -> dict:
    return {
        "tipo": t.tipo,
        "nombre": t.nombre,
        "marca": t.marca,
        "fecha_desde": t.fecha_desde.isoformat(),
        "fecha_hasta": t.fecha_hasta.isoformat(),
        "moneda": t.moneda,
        "estado": t.estado,
    }


# --- void ---------------------------------------------------------------------------------------------------------


@_ocupado_si_deadlock
def anular(db: Session, tactical_id: int, usuario_id: int, motivo: Optional[str]) -> Optional[Tactical]:
    """Void the tactical and every active child through its engine's void step (module docstring). None when it
    does not exist; `TacticalYaAnulado` on a second call; `TacticalOcupado` when a campaign is being recomputed."""
    try:
        tactical = db.query(Tactical).filter(Tactical.id == tactical_id).populate_existing().with_for_update().first()
        if tactical is None:
            return None
        if tactical.estado == "anulado":
            raise TacticalYaAnulado(f"El tactical {tactical_id} ya está anulado")
        hijos = _anular_hijos(db, tactical_id, usuario_id, motivo)
        tactical.estado = "anulado"
        _audit(db, TipoAccion.TACTICAL_ANULADO, usuario_id, {"tactical_id": tactical_id, **hijos}, motivo)
        db.commit()
    except campanas.SellOutRecalculando as exc:
        db.rollback()
        raise TacticalOcupado(str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(tactical)
    return tactical


def _anular_hijos(db: Session, tactical_id: int, usuario_id: int, motivo: Optional[str]) -> dict:
    anuladas = {"campana_ids": [], "bono_ids": [], "compra_ids": []}
    for (cid,) in db.query(SellOutCampana.id).filter(SellOutCampana.tactical_id == tactical_id).order_by("id"):
        try:
            campana = campanas.bloquear(db, cid)
        except campanas.SellOutYaAnulada:
            continue
        campanas.anular_sin_commit(db, campana, usuario_id, motivo, masivo=True)
        anuladas["campana_ids"].append(cid)
    for (bid,) in db.query(SellInBonoMarca.id).filter(SellInBonoMarca.tactical_id == tactical_id).order_by("id"):
        try:
            bonos_crud.anular_bono_sin_commit(db, bid, usuario_id, motivo, es_masivo=True)
        except bonos_crud.SellInBonoYaAnulado:
            continue
        anuladas["bono_ids"].append(bid)
    for (cid,) in db.query(SellInCompra.id).filter(SellInCompra.tactical_id == tactical_id).order_by("id"):
        try:
            compras.anular_compra_sin_commit(db, cid, usuario_id, motivo, es_masivo=True)
        except compras.SellInYaAnulada:
            continue
        anuladas["compra_ids"].append(cid)
    return anuladas


# --- read ---------------------------------------------------------------------------------------------------------


@dataclass
class Filtros:
    tipos: list[str]  # the kinds the caller may read (and asked for)
    marca: Optional[str] = None
    estado: Optional[str] = None  # vigentes | vencidos | anulados
    desde: Optional[date] = None
    hasta: Optional[date] = None
    q: Optional[str] = None


def listar(db: Session, filtros: Filtros, page: int, page_size: int, hoy: Optional[date] = None) -> tuple[int, list]:
    hoy = hoy or date.today()
    query = db.query(Tactical).filter(Tactical.tipo.in_(filtros.tipos))
    if filtros.marca:
        query = query.filter(Tactical.marca == filtros.marca)
    if filtros.estado == "anulados":
        query = query.filter(Tactical.estado == "anulado")
    elif filtros.estado == "vigentes":
        query = query.filter(Tactical.estado == "activo", Tactical.fecha_hasta >= hoy)
    elif filtros.estado == "vencidos":
        query = query.filter(Tactical.estado == "activo", Tactical.fecha_hasta < hoy)
    if filtros.desde is not None:
        query = query.filter(Tactical.fecha_hasta >= filtros.desde)
    if filtros.hasta is not None:
        query = query.filter(Tactical.fecha_desde <= filtros.hasta)
    if _texto(filtros.q):
        q = _texto(filtros.q)
        query = query.filter(or_(contiene(Tactical.nombre, q), contiene(Tactical.referencia, q)))
    total = query.order_by(None).count()
    filas = (
        query.order_by(Tactical.fecha_desde.desc(), Tactical.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, filas


def _cents(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _lineas_campanas(db: Session, ids: list[int]) -> list[dict]:
    campanas_ = db.query(SellOutCampana).filter(SellOutCampana.tactical_id.in_(ids)).all()
    if not campanas_:
        return []
    cids = [c.id for c in campanas_]
    alcances: dict[int, dict] = defaultdict(lambda: {"item_ids": [], "marca": None, "categoria": None})
    for cid, item_id, marca, categoria in (
        db.query(
            SellOutCampanaGrupo.campana_id,
            OffsetGrupoFiltro.item_id,
            OffsetGrupoFiltro.marca,
            OffsetGrupoFiltro.categoria,
        )
        .join(OffsetGrupoFiltro, OffsetGrupoFiltro.grupo_id == SellOutCampanaGrupo.grupo_id)
        .filter(SellOutCampanaGrupo.campana_id.in_(cids))
        .order_by(OffsetGrupoFiltro.id)
    ):
        if item_id is not None:
            alcances[cid]["item_ids"].append(item_id)
        else:
            alcances[cid]["marca"], alcances[cid]["categoria"] = marca, categoria
    usado = {
        cid: (int(u), _cents(m))
        for cid, u, m in db.query(
            SellOutConsumo.campana_id, func.sum(SellOutConsumo.unidades), func.sum(SellOutConsumo.monto)
        )
        .filter(SellOutConsumo.campana_id.in_(cids))
        .group_by(SellOutConsumo.campana_id)
    }
    salida = []
    for c in campanas_:
        a = alcances[c.id]
        unidades, monto = usado.get(c.id, (0, _cents(0)))
        salida.append(
            {
                "tactical_id": c.tactical_id,
                "id": c.id,
                "linea": c.tactical_linea,
                "origen": "sell_out_campana",
                "estado": c.estado,
                "alcance": "productos" if a["item_ids"] else ("marca" if a["marca"] else "categoria"),
                "item_ids": a["item_ids"],
                "marca": a["marca"],
                "categoria": a["categoria"],
                "pedido_compra_id": None,
                "pedido_numero": None,
                "modo_monto": c.tipo,
                "valor": {"por_unidad": c.monto_unit, "porcentaje": c.porcentaje, "monto_total": c.monto_total}[c.tipo],
                "moneda": c.moneda,
                "tope_unidades": c.tope_unidades,
                "tope_monto": c.tope_monto,
                "unidades_usadas": unidades,
                "monto_usado": monto,
            }
        )
    return salida


def _lineas_bonos(db: Session, ids: list[int]) -> list[dict]:
    bonos = db.query(SellInBonoMarca).filter(SellInBonoMarca.tactical_id.in_(ids)).all()
    salida = []
    for bono, fila in zip(bonos, bonos_crud.serializar(db, bonos)):
        salida.append(
            {
                "tactical_id": bono.tactical_id,
                "id": bono.id,
                "linea": bono.tactical_linea,
                "origen": "sell_in_bono",
                "estado": bono.estado,
                "alcance": {"modelos": "productos"}.get(bono.alcance, bono.alcance),
                "item_ids": [m["item_id"] for m in fila["modelos"]],
                "marca": bono.marca,
                "categoria": bono.categoria,
                "pedido_compra_id": bono.pedido_id,
                "pedido_numero": fila["pedido_numero"],
                "modo_monto": bono.tipo,
                "valor": bono.monto_unit if bono.tipo == "por_unidad" else bono.porcentaje,
                "moneda": bono.moneda,
                "tope_unidades": bono.tope_unidades,
                "tope_monto": bono.tope_monto,
                "unidades_usadas": fila["unidades"],
                "monto_usado": _cents(fila["monto_generado"]),
            }
        )
    return salida


def _lineas_compras(db: Session, ids: list[int]) -> list[dict]:
    compras_ = db.query(SellInCompra).filter(SellInCompra.tactical_id.in_(ids)).all()
    if not compras_:
        return []
    cids = [c.id for c in compras_]
    pedidos = {
        cid: (pid, numero)
        for cid, pid, numero in db.query(SellInCompraPedido.compra_id, PedidoCompra.id, PedidoCompra.numero)
        .join(PedidoCompra, PedidoCompra.id == SellInCompraPedido.pedido_compra_id)
        .filter(SellInCompraPedido.compra_id.in_(cids))
    }
    usado = {
        cid: (int(u), Decimal(str(m or 0)))
        for cid, u, m in db.query(
            SellInCompraItem.compra_id, func.sum(SellInConsumo.unidades), func.sum(SellInConsumo.descuento_ars)
        )
        .join(SellInConsumo, SellInConsumo.compra_item_id == SellInCompraItem.id)
        .filter(SellInCompraItem.compra_id.in_(cids))
        .group_by(SellInCompraItem.compra_id)
    }
    salida = []
    for c in compras_:
        unidades, ars = usado.get(c.id, (0, Decimal(0)))
        # What the sales took is ARS; shown in the purchase's currency at its own rate (a USD purchase carries one).
        monto = ars / Decimal(c.tipo_cambio) if c.moneda == "USD" and c.tipo_cambio else ars
        pedido_id, numero = pedidos.get(c.id, (None, None))
        salida.append(
            {
                "tactical_id": c.tactical_id,
                "id": c.id,
                "linea": c.tactical_linea,
                "origen": "sell_in_compra",
                "estado": c.estado,
                "alcance": "factura",
                "item_ids": [],
                "marca": None,
                "categoria": None,
                "pedido_compra_id": pedido_id,
                "pedido_numero": numero,
                "modo_monto": "monto_total",
                "valor": c.monto_total,
                "moneda": c.moneda,
                "tope_unidades": None,
                "tope_monto": None,
                "unidades_usadas": unidades,
                "monto_usado": _cents(monto),
            }
        )
    return salida


def serializar(db: Session, tacticals: Iterable[Tactical]) -> list[dict]:
    """Each tactical with its lines, one per child, in line order (module docstring): a few queries per page."""
    tacticals = list(tacticals)
    ids = [t.id for t in tacticals]
    lineas = (_lineas_campanas(db, ids) + _lineas_bonos(db, ids) + _lineas_compras(db, ids)) if ids else []
    item_ids = {i for linea in lineas for i in linea["item_ids"]}
    productos = {
        p.item_id: p
        for p in db.query(ProductoERP.item_id, ProductoERP.codigo, ProductoERP.descripcion).filter(
            ProductoERP.item_id.in_(item_ids)
        )
    }
    por_linea: dict[tuple[int, int], int] = defaultdict(int)
    for linea in lineas:
        por_linea[(linea["tactical_id"], linea["linea"])] += 1
    de_tactical: dict[int, list[dict]] = defaultdict(list)
    for linea in sorted(lineas, key=lambda x: (x["linea"], x["id"])):
        item_ids_ = linea.pop("item_ids")
        linea["productos"] = [
            {
                "item_id": i,
                "codigo": productos[i].codigo if i in productos else None,
                "descripcion": productos[i].descripcion if i in productos else None,
            }
            for i in item_ids_
        ]
        linea["tope_por_producto"] = por_linea[(linea["tactical_id"], linea["linea"])] > 1
        de_tactical[linea.pop("tactical_id")].append(linea)
    columnas = (
        "id", "tipo", "nombre", "marca", "referencia", "fecha_desde", "fecha_hasta", "moneda", "tc_modo",
        "tipo_cambio", "incluye_iva", "acumulable", "nota", "estado", "usuario_id", "created_at", "updated_at",
    )  # fmt: skip
    return [{**{c: getattr(t, c) for c in columnas}, "lineas": de_tactical[t.id]} for t in tacticals]
