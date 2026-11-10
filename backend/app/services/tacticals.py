"""Tacticals: create, list, detail and void (tacticals T1; contract in `handoffs/tactical-tarea.md` "Contrato final").

A tactical (`app.models.tactical`) is a header; each line of it becomes rows of the EXISTING engines, created through
their own create steps (same validation, audit rows and queueing), so allocation, FIFO and caps are not rewritten:

- sell out (productos | marca | categoria): one `SellOutCampana` over its own hidden group (`OffsetGrupo.oculto`)
  whose filter rows carry the line's scope. `tope_por_producto`: one campaign and group per product.
- sell in over productos | marca | categoria: one cost bonus (`SellInBonoMarca`, `base = 'costo_venta'`, ARS), a %
  or an amount per unit of each sale's cost by sale date, or a total split across the line's products by its
  `reparto_criterio` (tactical monto total S4, `tipo = 'monto_total'`). `tope_por_producto`: one bonus per product.
- sell in `factura` with % or per unit: one invoice bonus (`alcance = base = 'factura'`) on that operation.
- sell in `factura` with a fixed total: one sell-in purchase (`SellInCompra`, monto, proporcional) over the invoice's
  invoiced lines.

Every child carries `tactical_id` and `tactical_linea` (its 1-based line). The header's dates, currency, FX, VAT flag
and `acumulable` are copied to every child, which is what the engines read, except where an engine has its own: an
invoice line converts at its operation's rate (a fixed rate is refused there) and a cost bonus is ARS.

An invoice line has no dates of its own (tactical factura sin fecha S1, S2c): any invoice date is accepted, and its
bonus's range is its invoice's date, so its rebate follows that invoice's units through the FIFO until they are sold;
the reconcile moves it with a corrected invoice date. A tactical whose every line is an invoice line (`por_factura`)
asks no dates: its header spans its oldest to newest invoice, its end date is not editable and it is current until
voided. With any other line the header's dates are required and reach only the other lines.

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
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Query, Session, selectinload

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
from app.models.producto import ProductoERP
from app.models.sell_in import (
    SellInBonoMarca,
    SellInCompra,
    SellInCompraItem,
    SellInCompraPedido,
    SellInConsumo,
)
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo, SellOutConsumo
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.tactical import Tactical, TacticalCobranza, TacticalMarca, TacticalTienda
from app.schemas.sell_in import SellInCompraCreate, SellInLineaIn
from app.schemas.sell_in_bonos import BASE_COSTO_VENTA, BASE_FACTURA, SellInBonoIn
from app.schemas.sell_out import SellOutCampanaIn
from app.schemas.tacticals import (
    HIJOS_MAX,
    TacticalCobranzaIn,
    TacticalEditarIn,
    TacticalIn,
    TacticalLineaIn,
    TacticalLineaTopesIn,
    TacticalTiendaIn,
)
from app.services.sell_in import bonos_crud, compras
from app.services.sell_in.compras import contiene
from app.services.sell_out import campanas, tienda_scope

GRUPO_NOMBRE_MAX = 100  # offset_grupos.nombre is VARCHAR(100)
CAMPANA_NOMBRE_MAX = 200
CENTAVO = Decimal("0.01")
SIN_FECHAS = "Las fechas son obligatorias: solo un tactical con todas sus líneas por factura va sin fechas"
SIN_FECHA_HASTA = "Un tactical por factura no tiene fecha hasta: cada factura aplica hasta que se venden sus unidades"
TOTAL_USD_SIN_TC_FIJO = "un monto total en USD necesita tipo de cambio fijo"
COSTO_EN_PESOS = (
    "una reducción de costo por unidad o con tope de monto va en pesos (ARS): el costo de cada venta está en pesos"
)


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


def _audit(
    db: Session,
    tipo: TipoAccion,
    usuario_id: int,
    valores: dict,
    motivo: Optional[str] = None,
    antes: Optional[dict] = None,
) -> None:
    db.add(
        Auditoria(
            item_id=None,
            usuario_id=usuario_id,
            tipo_accion=tipo,
            valores_anteriores=antes,
            valores_nuevos=valores,
            es_masivo=False,
            comentario=motivo,
        )
    )


# --- header -------------------------------------------------------------------------------------------------------


def _por_factura(data: TacticalIn) -> bool:
    """Every line is an invoice line (tactical factura sin fecha S2c): the tactical asks no dates."""
    return data.tipo == "sell_in" and all(linea.alcance == "factura" for linea in data.lineas)


def _marcas(db: Session, data: TacticalIn) -> list[str]:
    """The header's brands, trimmed, without repeats, in the order given (S3). Only `marca` (an old client) means
    that one brand; with both, `marca` must be one of `marcas`. Every brand needs products, as one did before."""
    marcas = list(dict.fromkeys(m for m in (_texto(x) for x in data.marcas) if m is not None))
    marca = _texto(data.marca)
    if not marcas and marca is not None:
        marcas = [marca]
    if not marcas:
        raise TacticalError("La marca es obligatoria")
    if marca is not None and marca not in marcas:
        raise TacticalError("La marca tiene que ser una de las marcas del tactical")
    con_productos = {
        m for (m,) in db.query(ProductoERP.marca).filter(ProductoERP.marca.in_(marcas)).distinct()
    }  # fmt: skip
    faltan = [m for m in marcas if m not in con_productos]
    if faltan:
        raise TacticalError(f"No hay productos de la marca {', '.join(faltan)}")
    return marcas


def _validar_cabecera(db: Session, data: TacticalIn) -> tuple[str, list[str], Optional[str]]:
    """The header's rules; returns `(nombre, marcas, tc_modo)` normalized (USD without a mode is `al_cobro`)."""
    nombre = _texto(data.nombre)
    if nombre is None:
        raise TacticalError("El nombre es obligatorio")
    marcas = _marcas(db, data)
    if not _por_factura(data):
        if data.fecha_desde is None or data.fecha_hasta is None:
            raise TacticalError(SIN_FECHAS)
        if data.fecha_hasta < data.fecha_desde:
            raise TacticalError("La fecha hasta no puede ser anterior a la fecha desde")
    _validar_tiendas(db, data)
    if data.moneda == "ARS":
        if data.tc_modo is not None or data.tipo_cambio is not None:
            raise TacticalError("Un tactical en pesos no lleva tipo de cambio")
        return nombre, marcas, None
    tc_modo = data.tc_modo or "al_cobro"
    if tc_modo == "fijo":
        if data.tipo_cambio is None or data.tipo_cambio <= 0:
            raise TacticalError("Con tipo de cambio fijo hay que indicar el tipo de cambio, mayor a 0")
    elif data.tipo_cambio is not None:
        raise TacticalError("Solo con tipo de cambio fijo se indica el tipo de cambio")
    return nombre, marcas, tc_modo


SOLO_SELL_OUT = "Las tiendas solo se eligen en sell out: un tactical de sell in baja el costo de todas las ventas"
# Sell in's only scope (owner 2026-11-10: "lo de tiendas no aplica a sell in, es solo para sell out"): every store and
# channel with one cap, what the migration's backfill gave every tactical. Whatever it sends with every store is stored
# as that; a narrowed scope is refused (`SOLO_SELL_OUT`).
_CANALES_SELL_IN = ("fuera", "tienda_nube")


def _alcance_sell_in(data: TacticalIn) -> None:
    if data.tipo != "sell_in":
        return
    if not data.todas_tiendas or any(t.tipo == "oficial" for t in data.tiendas):
        raise TacticalError(SOLO_SELL_OUT)
    data.tope_compartido = True
    data.tiendas = [TacticalTiendaIn(tipo=canal) for canal in _CANALES_SELL_IN]


def _validar_tiendas(db: Session, data: TacticalIn) -> None:
    """Store / channel scope: todas XOR oficial rows; channels optional; store_ids must exist. Sell in takes only
    every store (`_alcance_sell_in`)."""
    _alcance_sell_in(data)
    oficiales = [t for t in data.tiendas if t.tipo == "oficial"]
    canales = [t for t in data.tiendas if t.tipo != "oficial"]
    if data.todas_tiendas and oficiales:
        raise TacticalError("Con todas las tiendas no se listan tiendas oficiales sueltas")
    if not data.todas_tiendas and not oficiales and not canales:
        raise TacticalError("Elegí al menos una tienda oficial, Por fuera o Tienda Nube (o todas)")
    vistos_store: set[int] = set()
    vistos_canal: set[str] = set()
    for fila in data.tiendas:
        if fila.tipo == "oficial":
            if fila.store_id is None:
                raise TacticalError("Una tienda oficial necesita store_id")
            if fila.store_id in vistos_store:
                raise TacticalError(f"La tienda oficial {fila.store_id} está repetida")
            vistos_store.add(fila.store_id)
        else:
            if fila.store_id is not None:
                raise TacticalError(f"El canal {fila.tipo} no lleva store_id")
            if fila.tipo in vistos_canal:
                raise TacticalError(f"El canal {fila.tipo} está repetido")
            vistos_canal.add(fila.tipo)
    if vistos_store:
        hallados = {
            sid for (sid,) in db.query(MlTiendaOficial.store_id).filter(MlTiendaOficial.store_id.in_(vistos_store))
        }
        faltan = sorted(vistos_store - hallados)
        if faltan:
            raise TacticalError(f"No existen las tiendas oficiales {', '.join(str(s) for s in faltan)}")


def _guardar_tiendas(tactical: Tactical, tiendas: list[TacticalTiendaIn]) -> None:
    tactical.tiendas = [
        TacticalTienda(tipo=fila.tipo, store_id=fila.store_id if fila.tipo == "oficial" else None) for fila in tiendas
    ]


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
    if linea.modo_monto == "monto_total" and linea.alcance == "factura":
        if linea.reparto_criterio is not None:
            raise TacticalError(
                "una línea por factura reparte su monto total sobre lo facturado: no lleva criterio de reparto"
            )
    elif linea.modo_monto == "monto_total":  # sell out, or a sell in cost bonus over products, brand or category
        if linea.reparto_criterio is None:
            raise TacticalError("elegí cómo repartir el monto total")
        if linea.tope_por_producto:
            raise TacticalError("un monto total se reparte entre los productos de la línea: no lleva tope por producto")
        if linea.tope_unidades is not None or linea.tope_monto is not None:
            raise TacticalError("un monto total no lleva topes: el total es su tope")
    elif linea.reparto_criterio is not None:
        raise TacticalError("el reparto es solo para un monto total")
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
    # Any invoice date: an invoice line has no dates of its own (S1), its bonus takes its invoice's (`_sell_in`).
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
        reparto_criterio=linea.reparto_criterio,
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
        if linea.modo_monto == "monto_total" and data.moneda == "USD" and tactical.tc_modo != "fijo":
            raise TacticalError(TOTAL_USD_SIN_TC_FIJO)
        if data.moneda != "ARS" and (linea.modo_monto == "por_unidad" or linea.tope_monto is not None):
            raise TacticalError(COSTO_EN_PESOS)
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
        monto_total=_total_en_pesos(linea, data, parte) if linea.modo_monto == "monto_total" else None,
        reparto_criterio=linea.reparto_criterio,
        # An invoice bonus's range is its own invoice's date (S2c): it applies to that invoice's units until they
        # are sold, and the reconcile moves it with a corrected invoice date (`bonos._seguir_factura`).
        fecha_desde=parte.pedido.fecha_factura if parte.pedido is not None else data.fecha_desde,
        fecha_hasta=parte.pedido.fecha_factura if parte.pedido is not None else data.fecha_hasta,
        descripcion=descripcion,
        tope_unidades=linea.tope_unidades,
        tope_monto=linea.tope_monto,
        acumulable=data.acumulable,
    )
    bonos_crud.crear_bono_sin_commit(db, entrada, usuario_id, tactical=(tactical.id, numero))


def _total_en_pesos(linea, data, parte) -> Optional[Decimal]:
    """A cost bonus's total is ARS (each sale's cost is in pesos): a USD line is converted at the tactical's fixed
    rate (`_sell_in` already refused USD without one) and the bonus stores the ARS total. An invoice total is a
    purchase in its own currency (`_total_de_factura`), not converted here."""
    if parte.pedido is not None or data.moneda != "USD":
        return linea.valor
    return _cents(Decimal(linea.valor) * Decimal(data.tipo_cambio))


def _total_de_factura(db, tactical, data, linea, numero, pedido, descripcion, usuario_id) -> None:
    """An invoice's fixed total: a sell-in purchase split over its invoiced lines (`proporcional`)."""
    if linea.tope_unidades is not None or linea.tope_monto is not None:
        raise TacticalError("un monto total no lleva topes: el monto total es el tope")
    if data.moneda == "USD" and tactical.tc_modo != "fijo":
        raise TacticalError(TOTAL_USD_SIN_TC_FIJO)
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


def _validar_hijos(data: TacticalIn) -> None:
    """A per-product line stores one child per product: bound what one create (one transaction) may store."""
    hijos = sum(len(set(linea.item_ids)) if linea.tope_por_producto else 1 for linea in data.lineas)
    if hijos > HIJOS_MAX:
        raise TacticalError(
            f"Un tactical crea hasta {HIJOS_MAX} campañas o bonos y este crearía {hijos} (con tope por producto, "
            "cada producto es uno): partilo en varios tacticals"
        )


def _fechas_de_facturas(db: Session, data: TacticalIn) -> tuple[date, date]:
    """An all-invoice tactical's dates: its oldest and newest invoice date (S2c). A line whose invoice is missing or
    undated is refused by `_validar_linea` before commit, so today's date only stands in until that rollback."""
    ids = [linea.pedido_compra_id for linea in data.lineas if linea.pedido_compra_id is not None]
    desde, hasta = (
        db.query(func.min(PedidoCompra.fecha_factura), func.max(PedidoCompra.fecha_factura))
        .filter(PedidoCompra.id.in_(ids or [-1]))
        .one()
    )
    hoy = date.today()
    return desde or hoy, hasta or hoy


def _crear(db: Session, data: TacticalIn, usuario_id: int) -> Tactical:
    _validar_hijos(data)
    nombre, marcas, tc_modo = _validar_cabecera(db, data)
    fecha_desde, fecha_hasta = (
        _fechas_de_facturas(db, data) if _por_factura(data) else (data.fecha_desde, data.fecha_hasta)
    )
    tactical = Tactical(
        tipo=data.tipo,
        nombre=nombre,
        marca=_texto(data.marca) or marcas[0],  # the one an old client sent (one of `marcas`), else the first
        referencia=_texto(data.referencia),
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        moneda=data.moneda,
        tc_modo=tc_modo,
        tipo_cambio=data.tipo_cambio,
        incluye_iva=data.incluye_iva,
        acumulable=data.acumulable,
        todas_tiendas=data.todas_tiendas,
        tope_compartido=data.tope_compartido,
        nota=_texto(data.nota),
        estado="activo",
        usuario_id=usuario_id,
    )
    _guardar_tiendas(tactical, data.tiendas)
    tactical.marcas = [TacticalMarca(marca=m) for m in marcas]
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
        "marcas": [fila.marca for fila in t.marcas],
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


# --- edit ---------------------------------------------------------------------------------------------------------


@_ocupado_si_deadlock
def editar(
    db: Session, tactical_id: int, data: TacticalEditarIn, usuario_id: int, hoy: Optional[date] = None
) -> Optional[Tactical]:
    """Change what is safe on live money: the name, the note, the end date and the lines' caps (`TacticalEditarIn`).
    Every active child takes the change through its engine's own edit step (a campaign's or a bonus's), in one
    transaction with one `TACTICAL_EDITADO` audit row; a refused child rolls everything back as "Línea N: ...". None
    when it does not exist; `TacticalYaAnulado` when voided; `TacticalOcupado` when a campaign is being recomputed.
    An invoice total (`SellInCompra`) has no dates, caps nor edit step: only the header's name and dates move."""
    hoy = hoy or date.today()
    try:
        tactical = db.query(Tactical).filter(Tactical.id == tactical_id).populate_existing().with_for_update().first()
        if tactical is None:
            return None
        if tactical.estado == "anulado":
            raise TacticalYaAnulado(f"El tactical {tactical_id} está anulado")
        hijos = serializar(db, [tactical])[0]["lineas"]
        nombre, fecha_hasta = _validar_edicion(db, tactical, data, hijos, hoy)
        topes = {t.linea: t.model_dump(exclude_unset=True, exclude={"linea"}) for t in data.lineas}
        antes = {**_editables(tactical), "lineas": _topes_de(hijos, topes)}
        _editar_hijos(db, tactical, hijos, nombre, fecha_hasta, topes, usuario_id)
        tactical.nombre, tactical.fecha_hasta = nombre, fecha_hasta
        if "nota" in data.model_fields_set:
            tactical.nota = _texto(data.nota)
        db.flush()
        despues = {
            **_editables(tactical),
            "lineas": [t.model_dump(mode="json", exclude_unset=True) for t in data.lineas],
        }
        _audit(db, TipoAccion.TACTICAL_EDITADO, usuario_id, despues, antes=antes)
        db.commit()
    except campanas.SellOutRecalculando as exc:
        db.rollback()
        raise TacticalOcupado(str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(tactical)
    return tactical


def _editables(t: Tactical) -> dict:
    return {"tactical_id": t.id, "nombre": t.nombre, "nota": t.nota, "fecha_hasta": t.fecha_hasta.isoformat()}


def _topes_de(hijos: list[dict], topes: dict[int, dict]) -> list[dict]:
    """The edited lines' caps before the edit (every child of a line has the same ones)."""
    primero = {h["linea"]: h for h in reversed(hijos)}
    return [
        {"linea": n, "tope_unidades": primero[n]["tope_unidades"], "tope_monto": _texto_de(primero[n]["tope_monto"])}
        for n in sorted(topes)
    ]


def _texto_de(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else str(valor)


def _validar_edicion(
    db: Session, tactical: Tactical, data: TacticalEditarIn, hijos: list[dict], hoy: date
) -> tuple[str, date]:
    """The new name and end date; `TacticalError` on the first broken rule, before anything changes."""
    nombre = tactical.nombre
    if "nombre" in data.model_fields_set:
        nombre = _texto(data.nombre)
        if nombre is None:
            raise TacticalError("El nombre no puede quedar vacío")
    fecha_hasta = tactical.fecha_hasta
    if data.fecha_hasta is not None and data.fecha_hasta != tactical.fecha_hasta:
        if _hijos_por_factura(tactical, hijos):
            raise TacticalError(SIN_FECHA_HASTA)
        fecha_hasta = data.fecha_hasta
        if fecha_hasta < hoy:
            raise TacticalError(f"La fecha hasta no puede ser anterior a hoy ({_fecha(hoy)})")
        if fecha_hasta < tactical.fecha_desde:
            raise TacticalError(
                f"La fecha hasta no puede ser anterior a la fecha desde ({_fecha(tactical.fecha_desde)})"
            )
    lineas = {h["linea"] for h in hijos}
    editadas = {t.linea for t in data.lineas}
    maximos = _maximos_por_tienda(db, tactical, [h for h in hijos if h["linea"] in editadas])
    for tope in data.lineas:
        if tope.linea not in lineas:
            raise TacticalError(f"El tactical no tiene línea {tope.linea}")
        for hijo in (h for h in hijos if h["linea"] == tope.linea and h["estado"] == "activa"):
            _validar_tope(tope, hijo, tactical.moneda, maximos.get((hijo["origen"], hijo["id"])))
    return nombre, fecha_hasta


def _hijos_por_factura(tactical: Tactical, hijos: list[dict]) -> bool:
    """A stored tactical whose every line is an invoice line (S2c): no dates of its own."""
    return tactical.tipo == "sell_in" and bool(hijos) and all(h["alcance"] == "factura" for h in hijos)


def _es_por_factura():
    """`_hijos_por_factura` in SQL: a sell in tactical with no child other than an invoice bonus or an invoice total
    (an invoice total is its only `SellInCompra`)."""
    de_tactical = SellInBonoMarca.tactical_id == Tactical.id
    hay_hijos = or_(
        exists().where(de_tactical),
        exists().where(SellInCompra.tactical_id == Tactical.id),
    )
    otro = exists().where(de_tactical, SellInBonoMarca.alcance != "factura")
    return and_(Tactical.tipo == "sell_in", hay_hijos, ~otro)


# The credited rows per sale of each child kind whose cap a per-store scope splits: (owner, canal, venta_ref, units, amount)
_FILAS_POR_TIENDA = {
    "sell_out_campana": (
        SellOutConsumo.campana_id,
        SellOutConsumo.canal,
        SellOutConsumo.venta_ref,
        SellOutConsumo.unidades,
        SellOutConsumo.monto,
    ),
    # Only sell out: sell in ignores stores (S5), so a sell in cap is always one cap over every sale.
}


def _maximos_por_tienda(
    db: Session, tactical: Tactical, hijos: list[dict]
) -> dict[tuple[str, int], tuple[int, Decimal]]:
    """With per-store caps, what the most-used store or channel of each active child took `(units, amount)`: each
    counter has the whole cap, so a cap never goes below that one, not below the child's total. Empty when shared."""
    if tactical.tope_compartido:
        return {}
    salida: dict[tuple[str, int], tuple[int, Decimal]] = {}
    for origen, filas in _FILAS_POR_TIENDA.items():
        ids = sorted({h["id"] for h in hijos if h["origen"] == origen and h["estado"] == "activa"})
        if not ids:
            continue
        usados = tienda_scope.usado_por_contador(db, filas, ids)
        for i in ids:
            salida[(origen, i)] = (
                tienda_scope.maximo_usado(usados[i][0], 0),
                _cents(tienda_scope.maximo_usado(usados[i][1], Decimal(0))),
            )
    return salida


def _validar_tope(
    tope: TacticalLineaTopesIn, hijo: dict, moneda: str, maximo: Optional[tuple[int, Decimal]] = None
) -> None:
    """The create's cap rules (a cost bonus is ARS), plus never below what the child already used: with per-store
    caps (`maximo`), below what its most-used store or channel used."""
    if tope.tope_monto is not None and tope.tope_monto <= 0:
        raise TacticalError(f"Línea {hijo['linea']}: el tope de monto debe ser mayor que cero")
    es_costo = hijo["origen"] == "sell_in_bono" and hijo["alcance"] != "factura"
    if es_costo and moneda != "ARS" and tope.tope_monto is not None:
        raise TacticalError(f"Línea {hijo['linea']}: {COSTO_EN_PESOS}")
    if hijo["modo_monto"] == "monto_total" and (tope.tope_unidades is not None or tope.tope_monto is not None):
        raise TacticalError(f"Línea {hijo['linea']}: un monto total no lleva topes: el monto total es el tope")
    unidades, monto = maximo if maximo is not None else (hijo["unidades_usadas"], _cents(hijo["monto_usado"]))
    donde = " en una tienda o canal" if maximo is not None else ""
    if tope.tope_unidades is not None and tope.tope_unidades < unidades:
        raise TacticalError(
            f"Línea {hijo['linea']}: el tope de unidades ({tope.tope_unidades}) no puede quedar debajo de lo ya "
            f"usado{donde} ({unidades})"
        )
    if tope.tope_monto is not None and _cents(tope.tope_monto) < monto:
        raise TacticalError(
            f"Línea {hijo['linea']}: el tope de monto ({_cents(tope.tope_monto)}) no puede quedar debajo de lo ya "
            f"usado{donde} ({monto})"
        )


def _renombrado(viejo: Optional[str], antes: str, nuevo: str, maximo: int) -> Optional[str]:
    """A child's name with the tactical's name swapped (`_nombre` built it as "<tactical> · línea N ...")."""
    if viejo is None or not viejo.startswith(antes) or antes == nuevo:
        return viejo
    return (nuevo + viejo[len(antes) :])[:maximo]


def _editar_hijos(
    db: Session,
    tactical: Tactical,
    hijos: list[dict],
    nombre: str,
    fecha_hasta: date,
    topes: dict[int, dict],
    usuario_id: int,
) -> None:
    for hijo in hijos:
        if hijo["estado"] != "activa" or hijo["origen"] == "sell_in_compra":
            continue
        numero = hijo["linea"]
        try:
            if hijo["origen"] == "sell_out_campana":
                campana = campanas.bloquear(db, hijo["id"])
                cambios = {
                    "nombre": _renombrado(campana.nombre, tactical.nombre, nombre, CAMPANA_NOMBRE_MAX),
                    "fecha_hasta": fecha_hasta,
                    **topes.get(numero, {}),
                }
                if all(getattr(campana, campo) == valor for campo, valor in cambios.items()):
                    continue
                entrada = campanas.entrada_guardada(db, campana).model_copy(update=cambios)
                campanas.editar_campana_sin_commit(db, campana.id, entrada, usuario_id)
            else:
                bono = db.get(SellInBonoMarca, hijo["id"])
                cambios = {
                    "descripcion": _renombrado(bono.descripcion, tactical.nombre, nombre, CAMPANA_NOMBRE_MAX),
                    # An invoice bonus keeps its invoice's date (S2c, S4): the header's end date is not its own.
                    **({} if bono.alcance == "factura" else {"fecha_hasta": fecha_hasta}),
                    **topes.get(numero, {}),
                }
                if all(getattr(bono, campo) == valor for campo, valor in cambios.items()):
                    continue
                entrada = bonos_crud.entrada_guardada(db, bono).model_copy(update=cambios)
                bonos_crud.editar_bono_sin_commit(db, bono.id, entrada, usuario_id)
        except campanas.SellOutRecalculando as exc:
            raise TacticalOcupado(f"Línea {numero}: {exc}") from exc
        except ValueError as exc:  # every engine's refusal (SellOutError, SellInBonoError, ...)
            raise TacticalError(f"Línea {numero}: {_sin_mayuscula(str(exc))}") from exc


# --- read ---------------------------------------------------------------------------------------------------------


@dataclass
class Filtros:
    tipos: list[str]  # the kinds the caller may read (and asked for)
    marca: Optional[str] = None
    moneda: Optional[str] = None  # ARS | USD: the tactical's own currency
    estado: Optional[str] = None  # vigentes | vencidos | anulados
    desde: Optional[date] = None
    hasta: Optional[date] = None
    q: Optional[str] = None
    cobranza: Optional[str] = None  # cobrados | pendientes (tactical cobranza S4)


def _consulta(db: Session, filtros: Filtros, hoy: date) -> Query:
    """Every filter but the collection one: the KPIs (S4) count over this."""
    query = db.query(Tactical).filter(Tactical.tipo.in_(filtros.tipos))
    if filtros.marca:  # any of the tactical's brands (S3), or its header brand (a header without brand rows yet)
        query = query.filter(
            or_(
                Tactical.marca == filtros.marca,
                exists().where(TacticalMarca.tactical_id == Tactical.id, TacticalMarca.marca == filtros.marca),
            )
        )
    if filtros.moneda:
        query = query.filter(Tactical.moneda == filtros.moneda)
    if filtros.estado == "anulados":
        query = query.filter(Tactical.estado == "anulado")
    elif filtros.estado == "vigentes":  # an all-invoice tactical has no end (S4): current until voided
        query = query.filter(Tactical.estado == "activo", or_(Tactical.fecha_hasta >= hoy, _es_por_factura()))
    elif filtros.estado == "vencidos":
        query = query.filter(Tactical.estado == "activo", Tactical.fecha_hasta < hoy, ~_es_por_factura())
    if filtros.desde is not None:
        query = query.filter(Tactical.fecha_hasta >= filtros.desde)
    if filtros.hasta is not None:
        query = query.filter(Tactical.fecha_desde <= filtros.hasta)
    if _texto(filtros.q):
        q = _texto(filtros.q)
        query = query.filter(or_(contiene(Tactical.nombre, q), contiene(Tactical.referencia, q)))
    return query


def _con_relaciones(query: Query) -> Query:
    return query.options(selectinload(Tactical.tiendas), selectinload(Tactical.marcas), selectinload(Tactical.cobranza))


def listar(db: Session, filtros: Filtros, page: int, page_size: int, hoy: Optional[date] = None) -> tuple[int, list]:
    query = _consulta(db, filtros, hoy or date.today())
    cobrado = exists().where(TacticalCobranza.tactical_id == Tactical.id)
    if filtros.cobranza == "cobrados":
        query = query.filter(cobrado)
    elif filtros.cobranza == "pendientes":
        query = query.filter(~cobrado)
    total = query.order_by(None).count()
    filas = (
        _con_relaciones(query)
        .order_by(Tactical.fecha_desde.desc(), Tactical.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, filas


def kpis(db: Session, filtros: Filtros, hoy: Optional[date] = None) -> dict:
    """Pendientes and Cobrados over every tactical the other filters match (S4): how many, and the money they used
    per currency, summed from their lines' `monto_usado` exactly as the list's Avance column shows it (a USD
    tactical's cost-reduction lines count in ARS). ARS first, then USD; a currency with no tactical is left out."""
    leidos = serializar(db, _con_relaciones(_consulta(db, filtros, hoy or date.today())).all())
    salida = {}
    for clave, cobrados in (("pendientes", False), ("cobrados", True)):
        grupo = [t for t in leidos if (t["cobranza"] is not None) == cobrados]
        montos: dict[str, Decimal] = defaultdict(Decimal)
        for t in grupo:
            for linea in t["lineas"]:
                montos[linea["moneda"]] += Decimal(linea["monto_usado"])
        salida[clave] = {
            "cantidad": len(grupo),
            "montos": [{"moneda": m, "monto": _cents(montos[m])} for m in ("ARS", "USD") if m in montos],
        }
    return salida


# --- collection (tactical cobranza S1, S2) ----------------------------------------------------------------------------

_COBRANZA_TEXTOS = ("nc_numero", "distribuidor", "otro_detalle", "observaciones")


def cobrar(db: Session, tactical_id: int, data: TacticalCobranzaIn, usuario_id: int) -> Optional[Tactical]:
    """Save the tactical's one collection record (create or replace every field): it reads "Cobrado". None when the
    tactical does not exist. The tactical row is locked so two saves never race into a duplicate."""
    try:
        tactical = db.query(Tactical).filter(Tactical.id == tactical_id).populate_existing().with_for_update().first()
        if tactical is None:
            return None
        cobranza = db.query(TacticalCobranza).filter(TacticalCobranza.tactical_id == tactical_id).first()
        if cobranza is None:
            cobranza = TacticalCobranza(tactical_id=tactical_id)
            db.add(cobranza)
        cobranza.fecha_cobro = data.fecha_cobro
        cobranza.medio = data.medio
        for campo in _COBRANZA_TEXTOS:
            setattr(cobranza, campo, _texto(getattr(data, campo)))
        cobranza.usuario_id = usuario_id
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(tactical)
    return tactical


def deshacer_cobro(db: Session, tactical_id: int) -> bool:
    """Undo: delete the tactical's collection record, so it reads "Pendiente" again. False when it had none."""
    try:
        borradas = db.query(TacticalCobranza).filter(TacticalCobranza.tactical_id == tactical_id).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.expire_all()
    return borradas > 0


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
                "reparto_criterio": c.reparto_criterio,
                "moneda": c.moneda,
                "tope_unidades": c.tope_unidades,
                "tope_monto": c.tope_monto,
                "unidades_usadas": unidades,
                "monto_usado": monto,
            }
        )
    return salida


def _valor_usd(bono: SellInBonoMarca, tasas: dict[int, Decimal]) -> Optional[Decimal]:
    """The USD amount a sell in total line was loaded with, for audit: its bonus keeps the ARS total converted at the
    tactical's fixed rate (`_total_en_pesos`), and ARS / rate rounds back to it exactly (the conversion's error is at
    most half a cent of ARS, below half a cent of USD for any rate above 1)."""
    tasa = tasas.get(bono.tactical_id)
    if bono.tipo != "monto_total" or tasa is None:
        return None
    return _cents(Decimal(bono.monto_total) / tasa)


def _lineas_bonos(db: Session, ids: list[int]) -> list[dict]:
    bonos = db.query(SellInBonoMarca).filter(SellInBonoMarca.tactical_id.in_(ids)).all()
    tasas = {
        tid: Decimal(tc)
        for tid, tc in db.query(Tactical.id, Tactical.tipo_cambio).filter(
            Tactical.id.in_(ids), Tactical.moneda == "USD", Tactical.tipo_cambio.isnot(None)
        )
    }
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
                "valor": {
                    "por_unidad": bono.monto_unit,
                    "porcentaje": bono.porcentaje,
                    "monto_total": bono.monto_total,
                }[bono.tipo],
                "reparto_criterio": bono.reparto_criterio,
                "valor_usd": _valor_usd(bono, tasas),
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
                "reparto_criterio": None,  # split over its invoiced lines (`proporcional`)
                "moneda": c.moneda,
                "tope_unidades": None,
                "tope_monto": None,
                "unidades_usadas": unidades,
                "monto_usado": _cents(monto),
            }
        )
    return salida


def _cobranza(cobranza: Optional[TacticalCobranza]) -> Optional[dict]:
    if cobranza is None:
        return None
    columnas = ("fecha_cobro", "medio", *_COBRANZA_TEXTOS, "usuario_id", "created_at", "updated_at")
    return {c: getattr(cobranza, c) for c in columnas}


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
        "tipo_cambio", "incluye_iva", "acumulable", "todas_tiendas", "tope_compartido", "nota", "estado",
        "usuario_id", "created_at", "updated_at",
    )  # fmt: skip
    return [
        {
            **{c: getattr(t, c) for c in columnas},
            "tiendas": [{"tipo": fila.tipo, "store_id": fila.store_id} for fila in t.tiendas],
            "marcas": [fila.marca for fila in t.marcas],
            "por_factura": _hijos_por_factura(t, de_tactical[t.id]),
            "lineas": de_tactical[t.id],
            "cobranza": _cobranza(t.cobranza),
        }
        for t in tacticals
    ]
