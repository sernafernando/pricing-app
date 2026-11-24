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
campaign's consumptions, what an invoice bonus generated, and what costo SI took off the purchase invoices for a cost
bonus or an invoice total (`costo_si.generado`, in the line's own currency at each invoice's rate).
"""

from __future__ import annotations

import logging

import functools
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from pydantic import ValidationError
from sqlalchemy import Select, Subquery, and_, case, exists, func, literal, or_, select, union_all
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Query, Session, selectinload

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
from app.models.producto import ProductoERP
from app.models.sell_in import (
    SellInBonoItem,
    SellInBonoMarca,
    SellInCompra,
    SellInCompraItem,
    SellInCompraPedido,
    SellInModoProducto,
)
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo, SellOutConsumo
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.usuario import Usuario
from app.models.tactical import Tactical, TacticalCobranza, TacticalFacturaPendiente, TacticalMarca, TacticalTienda
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
from app.services.costo_si import generado
from app.services.sell_in import aprobacion, bono_queue, bonos, bonos_crud, compras, facturas_elegidas
from app.services.sell_in.compras import contiene
from app.services.sell_out import alcance as sell_out_alcance, campanas, tienda_scope

logger = logging.getLogger(__name__)

GRUPO_NOMBRE_MAX = 100  # offset_grupos.nombre is VARCHAR(100)
CAMPANA_NOMBRE_MAX = 200
CENTAVO = Decimal("0.01")
# A line's child that is an invoice total: its purchase, or the row it waits as before the invoice.
ORIGEN_PENDIENTE = "sell_in_factura_pendiente"
TOTALES_DE_FACTURA = ("sell_in_compra", ORIGEN_PENDIENTE)
SIN_FECHAS = "Las fechas son obligatorias: solo un tactical con todas sus líneas por factura va sin fechas"
SIN_FECHA_HASTA = "Un tactical por factura no tiene fecha hasta: cada factura aplica hasta que se venden sus unidades"
TOTAL_USD_SIN_TC_FIJO = "un monto total en USD necesita tipo de cambio fijo"


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
        # A brand line may narrow to one of its categories (SISO S3, L7 D1: "los routers solo de tp-link").
        if campo != propio and valor and not (linea.alcance == "marca" and campo == "categoria"):
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
        de_marca = db.query(ProductoERP.item_id).filter(ProductoERP.marca == dados["marca"])
        if dados["categoria"] is not None:
            if not de_marca.filter(ProductoERP.categoria == dados["categoria"]).limit(1).first():
                raise TacticalError(
                    f"no hay productos de la marca {dados['marca']} en la categoría {dados['categoria']}"
                )
        elif not de_marca.limit(1).first():
            raise TacticalError(f"no hay productos de la marca {dados['marca']}")
        return _Alcance(marca=dados["marca"], categoria=dados["categoria"])
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
    # Any invoice date: an invoice line has no dates of its own (S1), its bonus takes its invoice's (`_sell_in`). Any
    # invoice line may wait for its invoice (sell in factura pendiente): a % or per unit one as its invoice bonus, a
    # total as a `TacticalFacturaPendiente`; each applies when Compras links the invoice.
    _validar_facturas_elegidas(db, linea, pedido)
    return _Alcance(pedido=pedido)


def _validar_facturas_elegidas(db: Session, linea: TacticalLineaIn, pedido: Any) -> None:
    """A pick of specific invoices (sell in varias facturas S3) names invoices linked to the line's own operation; an
    operation still without its invoice applies to all the invoices it will have (S2), so it takes no pick."""
    if linea.facturas_ct is None:
        return
    if not linea.facturas_ct:
        raise TacticalError("elegí al menos una factura, o dejá todas las facturas de la operación")
    vinculadas = {f["ct_transaction_id"] for f in facturas_elegidas.facturas_de(db, [pedido.id]).get(pedido.id, [])}
    if not vinculadas:
        raise TacticalError(
            f"la operación {pedido.numero} todavía no tiene facturas: la línea aplica a todas las que se vinculen"
        )
    ajenas = sorted(set(linea.facturas_ct) - vinculadas)
    if ajenas:
        raise TacticalError(f"la factura {ajenas[0]} no está vinculada a la operación {pedido.numero}")


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


def _sell_out(db, tactical, data, linea, numero, parte, codigos, usuario_id, heredada=False) -> None:
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
    campanas.crear_campana_sin_commit(
        db, entrada, usuario_id, tactical=(tactical.id, numero), estado=aprobacion.estado_de_linea(tactical.estado)
    )


def _sell_in(db, tactical, data, linea, numero, parte, codigos, usuario_id, heredada=False) -> None:
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
        alcance = "modelos" if parte.item_ids else ("marca" if parte.marca else "categoria")
        campos = {
            "alcance": alcance,
            "marca": parte.marca,
            "categoria": parte.categoria,
            "modelos": list(parte.item_ids),
            "moneda": moneda_de_costo(data.moneda, linea.modo_monto, linea.tope_monto),
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
        # are sold, and the reconcile moves it with a corrected invoice date (`bonos._seguir_factura`). A line
        # waiting for its invoice takes today as a placeholder: the reconcile moves it to the invoice's date when
        # Compras links it (sell in factura pendiente S3), and nothing applies before.
        fecha_desde=_fecha_de_factura(parte.pedido) if parte.pedido is not None else data.fecha_desde,
        fecha_hasta=_fecha_de_factura(parte.pedido) if parte.pedido is not None else data.fecha_hasta,
        descripcion=descripcion,
        tope_unidades=linea.tope_unidades,
        tope_monto=linea.tope_monto,
        acumulable=data.acumulable,
    )
    bonos_crud.crear_bono_sin_commit(
        db,
        entrada,
        usuario_id,
        tactical=(tactical.id, numero),
        estado=aprobacion.estado_de_linea(tactical.estado),
        heredado=heredada,
    )


def moneda_de_costo(moneda: str, modo_monto: str, tope_monto: Optional[Decimal]) -> str:
    """A cost bonus's currency (tactical sell in USD, owner: "vos elegís un tipo de moneda para el sell in y un tipo de
    cambio"): a USD tactical's per-unit amount, or money cap, is USD (P2 = A: the cap counts USD), converted per sale by
    `bonos_costo` at the tactical's rate type; a % without a money cap is a % of the ARS cost, the rate does not
    matter; a total is ARS at the fixed rate (`_total_en_pesos`)."""
    if moneda == "USD" and modo_monto != "monto_total" and (modo_monto == "por_unidad" or tope_monto is not None):
        return "USD"
    return "ARS"


def _fecha_de_factura(pedido: Any) -> date:
    """An invoice bonus's one-day range: its invoice's date, or today while it waits for the invoice."""
    return pedido.fecha_factura or date.today()


def _total_en_pesos(linea, data, parte) -> Optional[Decimal]:
    """A cost bonus's total is ARS (each sale's cost is in pesos): a USD line is converted at the tactical's fixed
    rate (`_sell_in` already refused USD without one) and the bonus stores the ARS total. An invoice total is a
    purchase in its own currency (`_total_de_factura`), not converted here."""
    if parte.pedido is not None or data.moneda != "USD":
        return linea.valor
    return _cents(Decimal(linea.valor) * Decimal(data.tipo_cambio))


def _total_de_factura(db, tactical, data, linea, numero, pedido, descripcion, usuario_id) -> None:
    """An invoice's fixed total: a sell-in purchase split over its invoiced lines (`proporcional`). Before Compras
    links the operation's invoice it waits as a `TacticalFacturaPendiente` (sell in factura pendiente), which the
    `sell_in.bono` worker turns into the same purchase (`aplicar_facturas_pendientes`)."""
    if linea.tope_unidades is not None or linea.tope_monto is not None:
        raise TacticalError("un monto total no lleva topes: el monto total es el tope")
    if data.moneda == "USD" and tactical.tc_modo != "fijo":
        raise TacticalError(TOTAL_USD_SIN_TC_FIJO)
    tasa_usd = data.tipo_cambio if data.moneda == "USD" else None
    if pedido.fecha_factura is None:
        db.add(
            TacticalFacturaPendiente(
                tactical_id=tactical.id,
                tactical_linea=numero,
                pedido_id=pedido.id,
                valor=linea.valor,
                moneda=data.moneda,
                tipo_cambio=tasa_usd,
                descripcion=descripcion,
                usuario_id=usuario_id,
            )
        )
        db.flush()
        return
    _compra_de_factura(
        db,
        (tactical.id, numero),
        pedido,
        linea.valor,
        data.moneda,
        tasa_usd,
        descripcion,
        usuario_id,
        aprobacion.estado_de_linea(tactical.estado),
    )


def _facturado(db: Session, pedido_id: int, elegidas: Optional[frozenset[int]] = None) -> list[tuple[int, int]]:
    """An operation's invoiced units per item, net of credit notes, the items with none left out: over every invoice
    (no pick, S2), or over the picked ones (`facturas_elegidas`, S3)."""
    if elegidas:
        return [(i, f.cantidad) for i, f in facturas_elegidas.facturado_elegido(db, pedido_id, elegidas).items()]
    t = PedidoCompraLineaFacturada
    return [
        (int(item_id), int(cantidad))
        for item_id, cantidad in db.query(t.item_id, func.sum(t.cantidad))
        .filter(t.pedido_id == pedido_id)
        .group_by(t.item_id)
        .having(func.sum(t.cantidad) > 0)
        .order_by(t.item_id)
    ]


def _compra_de_factura(
    db: Session,
    tactical: tuple[int, int],
    pedido: Any,
    valor: Decimal,
    moneda: str,
    tasa_usd: Optional[Decimal],
    descripcion: Optional[str],
    usuario_id: int,
    estado: str,
) -> SellInCompra:
    """The purchase of an invoice total, at save (`_total_de_factura`) or when its invoice arrives
    (`aplicar_facturas_pendientes`): one code path, so both give the same rows. `estado` follows the tactical
    (`aprobacion.estado_de_linea`): under a pending tactical it waits for the approval like every other line."""
    cantidades = _facturado(db, pedido.id, facturas_elegidas.de_linea(db, *tactical))
    if not cantidades:
        raise TacticalError(f"la factura de la operación {pedido.numero} no tiene líneas facturadas")
    entrada = SellInCompraCreate(
        moneda=moneda,
        tipo="monto",
        monto_total=valor,
        # USD: the tactical's fixed rate. ARS: the operation's own rate, which converts a product cost kept in USD
        # (the engine refuses a USD cost without one).
        tipo_cambio=tasa_usd if moneda == "USD" else pedido.tipo_cambio,
        formula="proporcional",
        lineas=[SellInLineaIn(item_id=i, cantidad=c) for i, c in cantidades],
        pedido_compra_ids=[pedido.id],
        fecha_compra=pedido.fecha_factura,
        descripcion=descripcion,
    )
    return compras.crear_compra_sin_commit(db, entrada, usuario_id, tactical=tactical, estado=estado)


def aplicar_facturas_pendientes(db: Session, pedido_ids: Iterable[int]) -> int:
    """Turn the waiting invoice totals of these operations into their purchases (sell in factura pendiente): each one
    whose operation now has its invoice date and invoiced units gets the purchase `_total_de_factura` would have made
    with the invoice already there, authored by whoever saved the line, and becomes `aplicada`. One still without
    them keeps waiting (a later change to the operation queues it again). An all-invoice tactical's header then spans
    its invoices (`bonos._cabeceras_por_factura`). Called by the `sell_in.bono` worker; does not commit. Returns how
    many were applied."""
    ids = sorted(set(pedido_ids))
    if not ids:
        return 0
    # Lock order of a tactical's writers (anular, editar): the tactical, then its waiting rows. The purchase's FK
    # takes the tactical FOR KEY SHARE anyway; taking it first waits for a void in progress instead of deadlocking
    # with it while holding its waiting row.
    duenos = (
        db.query(TacticalFacturaPendiente.tactical_id)
        .filter(TacticalFacturaPendiente.pedido_id.in_(ids), TacticalFacturaPendiente.estado == "pendiente")
        .distinct()
    )
    estados = dict(
        db.query(Tactical.id, Tactical.estado)
        .filter(Tactical.id.in_(duenos))
        .order_by(Tactical.id)
        .with_for_update(key_share=True)
        .all()
    )
    filas = (
        db.query(TacticalFacturaPendiente)
        .filter(TacticalFacturaPendiente.pedido_id.in_(ids), TacticalFacturaPendiente.estado == "pendiente")
        .order_by(TacticalFacturaPendiente.id)
        .with_for_update()
        .all()
    )
    tacticals_: set[int] = set()
    aplicadas = 0
    for fila in filas:
        pedido = (
            db.query(PedidoCompra.id, PedidoCompra.numero, PedidoCompra.fecha_factura, PedidoCompra.tipo_cambio)
            .filter(PedidoCompra.id == fila.pedido_id)
            .first()
        )
        if pedido is None or pedido.fecha_factura is None:
            continue
        # the gate reads the line's pick like the purchase does: a picked invoice without lines yet keeps waiting
        if not _facturado(db, pedido.id, facturas_elegidas.de_linea(db, fila.tactical_id, fila.tactical_linea)):
            continue
        compra = _compra_de_factura(
            db,
            (fila.tactical_id, fila.tactical_linea),
            pedido,
            Decimal(fila.valor),
            fila.moneda,
            fila.tipo_cambio,
            fila.descripcion,
            fila.usuario_id,
            aprobacion.estado_de_linea(estados.get(fila.tactical_id)),
        )
        fila.estado, fila.compra_id, fila.aplicada_en = "aplicada", compra.id, func.now()
        tacticals_.add(fila.tactical_id)
        aplicadas += 1
    db.flush()
    bonos._cabeceras_por_factura(db, tacticals_)
    return aplicadas


def repartir_totales_de_factura(db: Session, pedido_ids: Iterable[int]) -> int:
    """Re-split the applied invoice totals of these operations over all their invoiced lines (sell in varias facturas
    S2, owner: "por defecto tendría que aplicar a todas las facturas el sell in"): a total covers every invoice of its
    operation, so when another invoice links (or one is unlinked) its one purchase is re-split in place over the
    operation's current invoiced units (`compras.repartir_compra_sin_commit`). The total is never applied once per
    invoice: it stays one purchase, same id and amount, so a manual cost mode naming it and its waiting row stay
    valid. A purchase whose operation has no invoiced units left, or already has exactly them, is left as is. Called by
    the `sell_in.bono` worker after `aplicar_facturas_pendientes`; does not commit. Returns how many were re-split."""
    ids = sorted(set(pedido_ids))
    if not ids:
        return 0
    compra_ids = (
        select(SellInCompra.id)
        .join(SellInCompraPedido, SellInCompraPedido.compra_id == SellInCompra.id)
        .where(
            SellInCompraPedido.pedido_compra_id.in_(ids),
            SellInCompra.tactical_id.isnot(None),
            SellInCompra.estado.in_(aprobacion.VIVAS),
            SellInCompra.tipo == "monto",
        )
    )
    # Lock order of a tactical's writers (`aplicar_facturas_pendientes`): the tactical, then its purchases.
    duenos = select(SellInCompra.tactical_id).where(SellInCompra.id.in_(compra_ids)).distinct()
    db.query(Tactical.id).filter(Tactical.id.in_(duenos)).order_by(Tactical.id).with_for_update(key_share=True).all()
    filas = (
        db.query(
            SellInCompra.id,
            SellInCompra.usuario_id,
            SellInCompraPedido.pedido_compra_id,
            SellInCompra.tactical_id,
            SellInCompra.tactical_linea,
        )
        .join(SellInCompraPedido, SellInCompraPedido.compra_id == SellInCompra.id)
        .filter(SellInCompra.id.in_(compra_ids), SellInCompraPedido.pedido_compra_id.in_(ids))
        .order_by(SellInCompra.id)
        .all()
    )
    repartidas = 0
    elegidas = facturas_elegidas.de_lineas(db, [(f.tactical_id, f.tactical_linea) for f in filas])
    for compra_id, usuario_id, pedido_id, tactical_id, numero in filas:
        cantidades = _facturado(db, pedido_id, elegidas.get((tactical_id, numero)))
        if not cantidades:
            continue
        if compras.repartir_compra_sin_commit(db, compra_id, cantidades, usuario_id) is not None:
            repartidas += 1
    return repartidas


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
        facturas = _pedidos_de_facturas(db, tactical.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    _encolar_si_llego_la_factura(db, facturas)
    db.refresh(tactical)
    return tactical


def _pedidos_de_facturas(db: Session, tactical_id: int) -> list[int]:
    """The operations of the tactical's invoice lines (a %/per unit invoice bonus or a waiting invoice total), with or
    without their invoice as this transaction reads them: Compras may link one at any point of the save, after its
    lines read it without it, and the queue's own gate decides after the commit (`_encolar_si_llego_la_factura`)."""
    bonos_ = select(SellInBonoMarca.pedido_id).where(
        SellInBonoMarca.tactical_id == tactical_id,
        SellInBonoMarca.alcance == "factura",
        SellInBonoMarca.estado.in_(aprobacion.VIVAS),
    )
    totales = select(TacticalFacturaPendiente.pedido_id).where(
        TacticalFacturaPendiente.tactical_id == tactical_id, TacticalFacturaPendiente.estado == "pendiente"
    )
    return sorted({pid for (pid,) in db.execute(union_all(bonos_, totales)) if pid is not None})


def _encolar_si_llego_la_factura(db: Session, pedido_ids: list[int]) -> None:
    """After a save commits, re-read the operations of its invoice lines and queue the invoiced ones under the
    triggers' gate (sell in factura pendiente total): a link committed while the save was still open ran the operation
    triggers before the new lines were visible to them, so nothing queued it. One already invoiced before the save is
    queued again, which reconciles to the same result. Its own transaction; the save is already committed, so a
    failure here is logged and the line waits for the operation's next change."""
    if not pedido_ids:
        return
    try:
        bono_queue.encolar_pedidos_facturados(db, pedido_ids)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("tacticals: could not queue operations %s whose invoice arrived during the save", pedido_ids)


def _validar_hijos(data: TacticalIn) -> None:
    """A per-product line stores one child per product: bound what one create (one transaction) may store."""
    hijos = sum(len(set(linea.item_ids)) if linea.tope_por_producto else 1 for linea in data.lineas)
    if hijos > HIJOS_MAX:
        raise TacticalError(
            f"Un tactical crea hasta {HIJOS_MAX} campañas o bonos y este crearía {hijos} (con tope por producto, "
            "cada producto es uno): partilo en varios tacticals"
        )


def _fechas_de_facturas(db: Session, data: TacticalIn) -> tuple[date, date]:
    """An all-invoice tactical's dates: its oldest and newest invoice date (S2c). With every invoice still missing
    (sell in factura pendiente) today stands in, like its bonuses' placeholder; the reconcile spans the invoices once
    Compras links them (`bonos._cabeceras_por_factura`)."""
    ids = [linea.pedido_compra_id for linea in data.lineas if linea.pedido_compra_id is not None]
    desde, hasta = (
        db.query(func.min(PedidoCompra.fecha_factura), func.max(PedidoCompra.fecha_factura))
        .filter(PedidoCompra.id.in_(ids or [-1]))
        .one()
    )
    hoy = date.today()
    return desde or hoy, hasta or hoy


def _aplicar_cabecera(db: Session, tactical: Tactical, data: TacticalIn) -> None:
    """Validate the header (`_validar_cabecera`) and write it on `tactical`, its stores and brands included: the
    create's header, and the edit's full replace (S8)."""
    _validar_hijos(data)
    nombre, marcas, tc_modo = _validar_cabecera(db, data)
    fecha_desde, fecha_hasta = (
        _fechas_de_facturas(db, data) if _por_factura(data) else (data.fecha_desde, data.fecha_hasta)
    )
    tactical.tipo = data.tipo
    tactical.nombre = nombre
    tactical.marca = _texto(data.marca) or marcas[0]  # the one an old client sent (one of `marcas`), else the first
    tactical.referencia = _texto(data.referencia)
    tactical.fecha_desde, tactical.fecha_hasta = fecha_desde, fecha_hasta
    tactical.moneda, tactical.tc_modo, tactical.tipo_cambio = data.moneda, tc_modo, data.tipo_cambio
    tactical.incluye_iva, tactical.acumulable = data.incluye_iva, data.acumulable
    tactical.todas_tiendas, tactical.tope_compartido = data.todas_tiendas, data.tope_compartido
    tactical.nota = _texto(data.nota)
    if tactical.id is not None:  # an edit: the old rows go first (`uq_tactical_marcas` would see a kept brand twice)
        tactical.tiendas.clear()
        tactical.marcas.clear()
        db.flush()
    _guardar_tiendas(tactical, data.tiendas)
    tactical.marcas = [TacticalMarca(marca=m) for m in marcas]


def _crear(db: Session, data: TacticalIn, usuario_id: int) -> Tactical:
    tactical = Tactical(estado="pendiente", usuario_id=usuario_id)  # applies nothing until approved (S2)
    _aplicar_cabecera(db, tactical, data)
    db.add(tactical)
    db.flush()
    _crear_hijos(db, tactical, data, usuario_id)
    _audit(db, TipoAccion.TACTICAL_CREADO, usuario_id, {"tactical_id": tactical.id, **_cabecera(tactical)})
    return tactical


def _crear_hijos(
    db: Session,
    tactical: Tactical,
    data: TacticalIn,
    usuario_id: int,
    conservadas: frozenset[int] = frozenset(),
    heredadas: frozenset[int] = frozenset(),
) -> None:
    """Every line's children through the engines' create steps; a line in `conservadas` keeps the child it has (an
    edit's unchanged invoice total, `_conservables`), and one in `heredadas` already was a sell in lump-sum bonus
    (`_heredadas`), so it is not a new one."""
    todos = {i for linea in data.lineas for i in linea.item_ids}
    codigos = dict(db.query(ProductoERP.item_id, ProductoERP.codigo).filter(ProductoERP.item_id.in_(todos)))
    crear_hijo = _sell_out if data.tipo == "sell_out" else _sell_in
    for numero, linea in enumerate(data.lineas, start=1):
        if numero in conservadas:
            facturas_elegidas.guardar(db, tactical.id, numero, linea.facturas_ct)  # the same pick (`_conservables`)
            continue
        try:
            if linea.facturas_ct is not None and linea.alcance != "factura":
                raise TacticalError("solo una línea por factura elige facturas")
            alcance = _validar_linea(db, data, linea)
            # Before its children: every child of the line reads the line's pick (`facturas_elegidas`), an invoice
            # total right away (`_compra_de_factura`). None stored: every invoice.
            facturas_elegidas.guardar(db, tactical.id, numero, linea.facturas_ct)
            for parte in _partes(linea, alcance):
                crear_hijo(db, tactical, data, linea, numero, parte, codigos, usuario_id, numero in heredadas)
        except campanas.SellOutRecalculando as exc:
            raise TacticalOcupado(f"Línea {numero}: {exc}") from exc
        except ValidationError as exc:  # an engine's input schema refused a value the tactical's own did not check
            mensaje = str(exc.errors()[0].get("msg", "un valor no es válido")).removeprefix("Value error, ")
            raise TacticalError(f"Línea {numero}: {_sin_mayuscula(mensaje)}") from exc
        except ValueError as exc:  # TacticalError and every engine's refusal (SellOutError, SellInBonoError, ...)
            raise TacticalError(f"Línea {numero}: {_sin_mayuscula(str(exc))}") from exc


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


# --- approval (tacticals approval S2-S5) ------------------------------------------------------------------------

# What a money edit changes (S5: amounts, %, units/caps, dates, scope, base/kind): the header but its name, reference
# and note, and every line's definition but its child's id and state. Name, note and collection keep the approval.
CABECERA_DE_DINERO = (
    "tipo", "marca", "fecha_desde", "fecha_hasta", "moneda", "tc_modo", "tipo_cambio", "incluye_iva", "acumulable",
    "todas_tiendas", "tope_compartido",
)  # fmt: skip


class TacticalYaAprobado(TacticalError):
    """A second approval: 409."""


def _dinero(db: Session, tactical: Tactical) -> dict:
    db.flush()
    db.expire(tactical, ["tiendas", "marcas"])
    hijos = [h for h in serializar(db, [tactical])[0]["lineas"] if h["estado"] != "anulada"]
    return {
        **{c: getattr(tactical, c) for c in CABECERA_DE_DINERO},
        "marcas": sorted(fila.marca for fila in tactical.marcas),
        "tiendas": sorted((fila.tipo, fila.store_id) for fila in tactical.tiendas),
        "lineas": [{k: v for k, v in h.items() if k not in ("id", "estado")} for h in _definicion_de(hijos)],
    }


def _a_pendiente_si_cambio(db: Session, tactical: Tactical, antes: dict, usuario_id: int) -> None:
    """After an edit (PATCH or PUT): an approved tactical whose money changed goes back to pending (S4)."""
    if tactical.estado == "activo" and _dinero(db, tactical) != antes:
        a_pendiente(db, tactical.id, usuario_id, "Se editaron sus montos")


def _lineas_de(db: Session, tactical_id: int) -> dict[str, list[int]]:
    """The tactical's lines that are not voided, per engine (a purchase a bonus generated is not one of them)."""
    return {
        clave: [
            i
            for (i,) in db.query(modelo.id).filter(
                modelo.tactical_id == tactical_id, modelo.estado.in_(aprobacion.VIVAS)
            )
        ]
        for modelo, clave in (
            (SellInBonoMarca, "bono_ids"),
            (SellInCompra, "compra_ids"),
            (SellOutCampana, "campana_ids"),
        )
    }


def a_pendiente(db: Session, tactical_id: int, usuario_id: int, motivo: Optional[str] = None) -> bool:
    """Send an approved tactical and its lines back to pending (S4): nothing from it applies until it is approved
    again, and the approver is cleared. Locks the tactical first (the order of every tactical writer). False when it
    is not approved. Does not commit."""
    tactical = db.query(Tactical).filter(Tactical.id == tactical_id).populate_existing().with_for_update().first()
    if tactical is None or tactical.estado != "activo":
        return False
    antes = {"aprobado_por": tactical.aprobado_por, "aprobado_at": _iso(tactical.aprobado_at)}
    tactical.estado, tactical.aprobado_por, tactical.aprobado_at = "pendiente", None, None
    lineas = aprobacion.cambiar_lineas(db, **_lineas_de(db, tactical_id), de=aprobacion.ACTIVA, a=aprobacion.PENDIENTE)
    _audit(db, TipoAccion.TACTICAL_A_PENDIENTE, usuario_id, {"tactical_id": tactical_id, **lineas}, motivo, antes)
    return True


def _iso(valor: Any) -> Optional[str]:
    return valor.isoformat() if valor is not None else None


@_ocupado_si_deadlock
def aprobar(db: Session, tactical_id: int, usuario_id: int) -> Optional[Tactical]:
    """Approve a pending tactical (`POST /tacticals/{id}/aprobar`, S3): it and every line that is not voided start
    applying in one transaction (`aprobacion.cambiar_lineas` queues what follows), with who approved and when, and
    one `TACTICAL_APROBADO` row. Its author may approve it (L31). None when it does not exist; `TacticalYaAnulado`
    when voided; `TacticalYaAprobado` when already approved; `TacticalOcupado` when a campaign is being recomputed.
    Commits."""
    try:
        tactical = db.query(Tactical).filter(Tactical.id == tactical_id).populate_existing().with_for_update().first()
        if tactical is None:
            return None
        if tactical.estado == "anulado":
            raise TacticalYaAnulado(f"El tactical {tactical_id} está anulado")
        if tactical.estado == "activo":
            raise TacticalYaAprobado(f"El tactical {tactical_id} ya está aprobado")
        tactical.estado, tactical.aprobado_por, tactical.aprobado_at = "activo", usuario_id, func.now()
        lineas = aprobacion.cambiar_lineas(
            db, **_lineas_de(db, tactical_id), de=aprobacion.PENDIENTE, a=aprobacion.ACTIVA
        )
        _audit(db, TipoAccion.TACTICAL_APROBADO, usuario_id, {"tactical_id": tactical_id, **lineas})
        facturas = _pedidos_de_facturas(db, tactical_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    _encolar_si_llego_la_factura(db, facturas)
    db.refresh(tactical)
    return tactical


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
    # A waiting invoice total never becomes a purchase once its tactical is voided.
    pendientes = (
        db.query(TacticalFacturaPendiente)
        .filter(TacticalFacturaPendiente.tactical_id == tactical_id, TacticalFacturaPendiente.estado == "pendiente")
        .order_by(TacticalFacturaPendiente.id)
        .all()
    )
    for fila in pendientes:
        fila.estado = "anulada"
    if pendientes:
        anuladas["factura_pendiente_ids"] = [f.id for f in pendientes]
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
        dinero = _dinero(db, tactical)
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
        _a_pendiente_si_cambio(db, tactical, dinero, usuario_id)
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
        for hijo in (h for h in hijos if h["linea"] == tope.linea and h["estado"] in aprobacion.VIVAS):
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
        exists().where(TacticalFacturaPendiente.tactical_id == Tactical.id),
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
    db: Session, tactical: Tactical, hijos: list[dict], compartido: Optional[bool] = None
) -> dict[tuple[str, int], tuple[int, Decimal]]:
    """With per-store caps, what the most-used store or channel of each active child took `(units, amount)`: each
    counter has the whole cap, so a cap never goes below that one, not below the child's total. Empty when shared
    (`compartido`, the tactical's own unless a new definition sets it)."""
    if tactical.tope_compartido if compartido is None else compartido:
        return {}
    salida: dict[tuple[str, int], tuple[int, Decimal]] = {}
    for origen, filas in _FILAS_POR_TIENDA.items():
        ids = sorted({h["id"] for h in hijos if h["origen"] == origen and h["estado"] in aprobacion.VIVAS})
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
    """The create's cap rules, plus never below what the child already used: with per-store caps (`maximo`), below
    what its most-used store or channel used. A cost bonus whose currency the new cap changes (`moneda_de_costo`: a
    USD tactical's % line with or without a money cap) compares only units: its used amount is in the old currency."""
    if tope.tope_monto is not None and tope.tope_monto <= 0:
        raise TacticalError(f"Línea {hijo['linea']}: el tope de monto debe ser mayor que cero")
    if hijo["modo_monto"] == "monto_total" and (tope.tope_unidades is not None or tope.tope_monto is not None):
        raise TacticalError(f"Línea {hijo['linea']}: un monto total no lleva topes: el monto total es el tope")
    nueva = _moneda_tras_tope(hijo, moneda, tope.model_dump(exclude_unset=True))
    if nueva is not None and nueva != hijo["moneda"]:
        tope = tope.model_copy(update={"tope_monto": None})
    _validar_usado(tope, hijo, maximo)


def _moneda_tras_tope(hijo: dict, moneda: str, cambios: dict) -> Optional[str]:
    """A cost bonus's currency once `cambios` (a PATCH line's set caps) apply, by `moneda_de_costo`; None for any
    other child."""
    if hijo["origen"] != "sell_in_bono" or hijo["alcance"] == "factura":
        return None
    tope_monto = cambios["tope_monto"] if "tope_monto" in cambios else hijo["tope_monto"]
    return moneda_de_costo(moneda, hijo["modo_monto"], tope_monto)


def _validar_usado(
    tope: TacticalLineaTopesIn | TacticalLineaIn, hijo: dict, maximo: Optional[tuple[int, Decimal]] = None
) -> None:
    """A cap never below what the child already used; with per-store caps (`maximo`), below what its most-used store
    or channel used."""
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
        if hijo["estado"] not in aprobacion.VIVAS or hijo["origen"] in TOTALES_DE_FACTURA:
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
                moneda = _moneda_tras_tope(hijo, tactical.moneda, topes.get(numero, {}))
                if moneda is not None:
                    cambios["moneda"] = moneda  # a money cap on a USD tactical's % line counts USD (P2 = A)
                if all(getattr(bono, campo) == valor for campo, valor in cambios.items()):
                    continue
                entrada = bonos_crud.entrada_guardada(db, bono).model_copy(update=cambios)
                bonos_crud.editar_bono_sin_commit(db, bono.id, entrada, usuario_id)
        except campanas.SellOutRecalculando as exc:
            raise TacticalOcupado(f"Línea {numero}: {exc}") from exc
        except ValueError as exc:  # every engine's refusal (SellOutError, SellInBonoError, ...)
            raise TacticalError(f"Línea {numero}: {_sin_mayuscula(str(exc))}") from exc


# --- full edit (S8) -----------------------------------------------------------------------------------------------

COBRADO = (
    "El tactical está cobrado: para cambiar sus montos o líneas, primero deshacé el cobro (nombre, nota, fecha hasta "
    "y topes se editan igual)"
)
MOTIVO_REEMPLAZO = "Reemplazado al editar el tactical"


class TacticalCobrado(TacticalError):
    """A collected tactical's money is not replaced: 409 (`COBRADO`)."""


@_ocupado_si_deadlock
def reemplazar(
    db: Session, tactical_id: int, data: TacticalIn, usuario_id: int, hoy: Optional[date] = None
) -> Optional[Tactical]:
    """Replace the whole definition, as if the tactical were loaded again from scratch (S8), keeping its id.

    In one transaction: every active child is voided through its engine's void step and detached from the tactical
    (its audit rows and the `TACTICAL_EDITADO` row keep the trace), the header takes the new values, and every line
    is created again through the engines' create steps, so what the tactical already applied is recomputed with the
    new definition by the queues the engines already feed. An unchanged invoice-total line keeps its purchase.

    Refused: a voided tactical (`TacticalYaAnulado`), a collected one (`TacticalCobrado`: undo the collection first),
    an invoice-total purchase a manual cost mode names that would be voided, and a changed end date before today (an
    unchanged past one stays). A sell out `al_cobro` rate already set carries to the line's new campaigns while the
    currency and the FX mode do not change; otherwise it is discarded. None when it does not exist."""
    hoy = hoy or date.today()
    try:
        tactical = db.query(Tactical).filter(Tactical.id == tactical_id).populate_existing().with_for_update().first()
        if tactical is None:
            return None
        if tactical.estado == "anulado":
            raise TacticalYaAnulado(f"El tactical {tactical_id} está anulado")
        if tactical.cobranza is not None:
            raise TacticalCobrado(COBRADO)
        if not _por_factura(data) and data.fecha_hasta is not None and data.fecha_hasta != tactical.fecha_hasta:
            if data.fecha_hasta < hoy:
                raise TacticalError(f"La fecha hasta no puede ser anterior a hoy ({_fecha(hoy)})")
        hijos = serializar(db, [tactical])[0]["lineas"]
        dinero = _dinero(db, tactical)
        antes = {**_cabecera(tactical), "tactical_id": tactical.id, "lineas": _definicion_de(hijos)}
        conservadas = _conservables(tactical, data, hijos)
        heredadas = _heredadas(tactical, data, hijos)  # before the children are voided
        _validar_topes_usados(db, tactical, data, [h for h in hijos if h["linea"] not in conservadas])
        _sin_modo_manual(db, [h for h in hijos if h["linea"] not in conservadas])
        tasas = _tasas_al_cobro(db, tactical, data)
        reemplazados = _reemplazar_hijos(db, tactical_id, conservadas, usuario_id)
        facturas_elegidas.borrar(db, tactical_id)  # every line stores its pick again (`_crear_hijos`)
        _aplicar_cabecera(db, tactical, data)
        db.flush()
        _crear_hijos(db, tactical, data, usuario_id, frozenset(conservadas), heredadas)
        _poner_tasas(db, tactical_id, tasas)
        despues = {
            **_cabecera(tactical),
            "tactical_id": tactical.id,
            "definicion": data.model_dump(mode="json"),
            "reemplazados": reemplazados,
        }
        _audit(db, TipoAccion.TACTICAL_EDITADO, usuario_id, despues, antes=antes)
        _a_pendiente_si_cambio(db, tactical, dinero, usuario_id)
        facturas = _pedidos_de_facturas(db, tactical_id)
        db.commit()
    except campanas.SellOutRecalculando as exc:
        db.rollback()
        raise TacticalOcupado(str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    _encolar_si_llego_la_factura(db, facturas)
    db.refresh(tactical)
    return tactical


def _definicion_de(hijos: list[dict]) -> list[dict]:
    """What each child was, for the audit row's `valores_anteriores`."""
    campos = ("linea", "origen", "id", "estado", "alcance", "marca", "categoria", "pedido_compra_id", "modo_monto",
              "valor", "reparto_criterio", "moneda", "tope_unidades", "tope_monto", "facturas_ct")  # fmt: skip
    return [
        {
            **{c: (str(h[c]) if isinstance(h[c], Decimal) else h[c]) for c in campos},
            "item_ids": [p["item_id"] for p in h["productos"]],
        }
        for h in hijos
    ]


def _heredadas(tactical: Tactical, data: TacticalIn, hijos: list[dict]) -> frozenset[int]:
    """The new lines that repeat a stored sell in lump-sum bonus line: a full edit creates them again, which is not
    loading a new lump sum (`bonos_crud.validar`'s `nuevo`, sell-in-costo-si T5 PR A, L25). A new line is paired
    with the old line of the same scope whatever its number (L18, like `_validar_topes_usados`)."""
    if data.tipo != "sell_in" or tactical.tipo != "sell_in":
        return frozenset()
    por_linea: dict[int, list[dict]] = defaultdict(list)
    for h in hijos:
        if h["estado"] == "activa":
            por_linea[h["linea"]].append(h)
    totales = {
        n: actuales
        for n, actuales in por_linea.items()
        if all(h["origen"] == "sell_in_bono" and h["modo_monto"] == "monto_total" for h in actuales)
    }
    heredadas = set()
    for numero, linea in enumerate(data.lineas, start=1):
        if linea.modo_monto != "monto_total" or linea.alcance == "factura":
            continue
        viejo = next((n for n, actuales in totales.items() if _mismo_alcance(linea, actuales)), None)
        if viejo is not None:
            totales.pop(viejo)
            heredadas.add(numero)
    return frozenset(heredadas)


def _conservables(tactical: Tactical, data: TacticalIn, hijos: list[dict]) -> set[int]:
    """The lines whose only child is an active invoice total the new definition repeats as is (same line number,
    invoice, total, currency and rate): their purchase stays, so its FIFO units are not released and taken again."""
    if data.tipo != "sell_in":
        return set()
    por_linea: dict[int, list[dict]] = defaultdict(list)
    for h in hijos:
        if h["estado"] in aprobacion.VIVAS:
            por_linea[h["linea"]].append(h)
    conservadas = set()
    for numero, linea in enumerate(data.lineas, start=1):
        actuales = por_linea.get(numero, [])
        if len(actuales) != 1 or actuales[0]["origen"] not in TOTALES_DE_FACTURA:
            continue
        actual = actuales[0]
        if (
            linea.alcance == "factura"
            and linea.modo_monto == "monto_total"
            and linea.pedido_compra_id == actual["pedido_compra_id"]
            and _cents(linea.valor) == _cents(actual["valor"])
            and frozenset(linea.facturas_ct or ()) == frozenset(actual["facturas_ct"] or ())
            and data.moneda == actual["moneda"] == tactical.moneda
            and (data.moneda == "ARS" or data.tipo_cambio == tactical.tipo_cambio)
        ):
            conservadas.add(numero)
    return conservadas


def _validar_topes_usados(db: Session, tactical: Tactical, data: TacticalIn, hijos: list[dict]) -> None:
    """Rule 1 keeps the PATCH edit's guard (L16): a line whose type and scope stay (`_mismo_alcance`) cannot get a cap
    below what its active children already used. A new line is paired with the old line of the same scope whatever
    its number (L18: a deleted or moved line renumbers the rest), and the refusal names the new line's number. The
    amount is compared only while the currency stays: a used amount in another currency says nothing about the new
    cap."""
    if data.tipo != tactical.tipo:
        return
    por_linea: dict[int, list[dict]] = defaultdict(list)
    for h in hijos:
        if h["estado"] in aprobacion.VIVAS:
            por_linea[h["linea"]].append(h)
    pares: list[tuple[int, TacticalLineaIn, list[dict]]] = []
    for numero, linea in enumerate(data.lineas, start=1):
        viejo = next((n for n, actuales in por_linea.items() if _mismo_alcance(linea, actuales)), None)
        if viejo is not None:
            pares.append((numero, linea, por_linea.pop(viejo)))
    if not pares:
        return
    activos = [h for _, _, actuales in pares for h in actuales]
    maximos = _maximos_por_tienda(db, tactical, activos, compartido=data.tope_compartido)
    for numero, linea, actuales in pares:
        tope = linea if data.moneda == tactical.moneda else linea.model_copy(update={"tope_monto": None})
        for hijo in actuales:
            _validar_usado(tope, {**hijo, "linea": numero}, maximos.get((hijo["origen"], hijo["id"])))


def _mismo_alcance(linea: TacticalLineaIn, actuales: list[dict]) -> bool:
    """The new line targets what the line's current children target: the same scope and, by scope, the same brand and
    category, invoice, or products (a per-product line has one child per product)."""
    if any(h["alcance"] != linea.alcance for h in actuales):
        return False
    if linea.alcance == "marca":
        return all((h["marca"], h["categoria"] or None) == (linea.marca, linea.categoria or None) for h in actuales)
    if linea.alcance == "categoria":
        return all(h["categoria"] == linea.categoria for h in actuales)
    if linea.alcance == "factura":
        return all(h["pedido_compra_id"] == linea.pedido_compra_id for h in actuales)
    return {p["item_id"] for h in actuales for p in h["productos"]} == set(linea.item_ids)


def _sin_modo_manual(db: Session, hijos: list[dict]) -> None:
    """An invoice-total purchase a manual cost mode names (`sell_in_modos_producto.compra_id`, append-only) cannot
    be voided by an edit: that mode would point at a voided load."""
    compra_ids = {
        h["id"]: h["linea"] for h in hijos if h["origen"] == "sell_in_compra" and h["estado"] in aprobacion.VIVAS
    }
    if not compra_ids:
        return
    usadas = {
        cid
        for (cid,) in db.query(SellInModoProducto.compra_id)
        .filter(SellInModoProducto.compra_id.in_(compra_ids))
        .distinct()
    }
    if usadas:
        numero = min(compra_ids[c] for c in usadas)
        raise TacticalError(
            f"Línea {numero}: el monto total de esta factura ya se usó en un modo de costo manual: esa línea no se "
            "puede cambiar ni quitar"
        )


def _sufijo(nombre: str, numero: int) -> str:
    """What follows "línea N" in a child's name (`_nombre`): empty, or the product's code of a per-product line."""
    marca = f"línea {numero}"
    return nombre.split(marca, 1)[1] if marca in nombre else ""


def _tasas_al_cobro(db: Session, tactical: Tactical, data: TacticalIn) -> dict[tuple[int, str], tuple]:
    """The rates already set on the active `al_cobro` campaigns, by (line, name suffix), when the new definition
    keeps sell out in USD `al_cobro`: those carry to the new campaigns (D2). Any other change discards them."""
    sigue = (
        tactical.tipo == data.tipo == "sell_out"
        and tactical.moneda == data.moneda == "USD"
        and tactical.tc_modo == "al_cobro"
        and (data.tc_modo or "al_cobro") == "al_cobro"
    )
    if not sigue:
        return {}
    c = SellOutCampana
    return {
        (linea, _sufijo(nombre, linea)): (tasa, definido)
        for linea, nombre, tasa, definido in db.query(c.tactical_linea, c.nombre, c.tipo_cambio, c.tc_definido_en)
        .filter(c.tactical_id == tactical.id, c.estado.in_(aprobacion.VIVAS), c.tc_definido_en.isnot(None))
        .order_by(c.id)
    }


def _poner_tasas(db: Session, tactical_id: int, tasas: dict[tuple[int, str], tuple]) -> None:
    if not tasas:
        return
    for campana in db.query(SellOutCampana).filter(
        SellOutCampana.tactical_id == tactical_id, SellOutCampana.estado.in_(aprobacion.VIVAS)
    ):
        tasa = tasas.get((campana.tactical_linea, _sufijo(campana.nombre, campana.tactical_linea)))
        if tasa is not None:
            campana.tipo_cambio, campana.tc_definido_en = tasa  # the create already queued the campaign
    db.flush()


def _reemplazar_hijos(db: Session, tactical_id: int, conservadas: set[int], usuario_id: int) -> dict:
    """Void every active child but the kept lines' (`_anular_hijos`'s engine steps) and detach them from the tactical:
    the new children take their line numbers, and the read shows only the current definition."""
    anuladas = {"campana_ids": [], "bono_ids": [], "compra_ids": []}
    for (cid,) in (
        db.query(SellOutCampana.id)
        .filter(SellOutCampana.tactical_id == tactical_id, SellOutCampana.estado.in_(aprobacion.VIVAS))
        .order_by("id")
    ):
        campana = campanas.bloquear(db, cid)
        campanas.anular_sin_commit(db, campana, usuario_id, MOTIVO_REEMPLAZO, masivo=True)
        anuladas["campana_ids"].append(cid)
    for (bid,) in (
        db.query(SellInBonoMarca.id)
        .filter(SellInBonoMarca.tactical_id == tactical_id, SellInBonoMarca.estado.in_(aprobacion.VIVAS))
        .order_by("id")
    ):
        bonos_crud.anular_bono_sin_commit(db, bid, usuario_id, MOTIVO_REEMPLAZO, es_masivo=True)
        anuladas["bono_ids"].append(bid)
    for (cid,) in (
        db.query(SellInCompra.id)
        .filter(
            SellInCompra.tactical_id == tactical_id,
            SellInCompra.estado.in_(aprobacion.VIVAS),
            SellInCompra.tactical_linea.notin_(conservadas or {0}),
        )
        .order_by("id")
    ):
        compras.anular_compra_sin_commit(db, cid, usuario_id, MOTIVO_REEMPLAZO, es_masivo=True)
        anuladas["compra_ids"].append(cid)
    # A waiting invoice total of a line not kept goes away: it applied nothing, the new line holds its own.
    borradas = (
        db.query(TacticalFacturaPendiente)
        .filter(
            TacticalFacturaPendiente.tactical_id == tactical_id,
            TacticalFacturaPendiente.estado == "pendiente",
            TacticalFacturaPendiente.tactical_linea.notin_(conservadas or {0}),
        )
        .delete(synchronize_session="fetch")
    )
    if borradas:
        anuladas["facturas_pendientes_borradas"] = borradas
    db.flush()
    sueltos = {"tactical_id": None, "tactical_linea": None}
    for modelo, clave in ((SellOutCampana, "campana_ids"), (SellInBonoMarca, "bono_ids"), (SellInCompra, "compra_ids")):
        if anuladas[clave]:
            db.query(modelo).filter(modelo.id.in_(anuladas[clave])).update(sueltos, synchronize_session="fetch")
    return anuladas


# --- read ---------------------------------------------------------------------------------------------------------


@dataclass
class Filtros:
    tipos: list[str]  # the kinds the caller may read (and asked for)
    marca: Optional[str] = None
    moneda: Optional[str] = None  # ARS | USD: the tactical's own currency
    estado: Optional[str] = None  # vigentes | vencidos | anulados | pendientes_aprobacion
    desde: Optional[date] = None
    hasta: Optional[date] = None
    q: Optional[str] = None
    cobranza: Optional[str] = None  # cobrados | pendientes (tactical cobranza S4)
    contiene: Optional[str] = None  # productos | marca | categoria | factura: a kind of line it holds (SISO S1)
    producto: Optional[str] = None  # código or descripción of a product one of its lines reaches (SISO S2)


def _filtros_sell_out(campana_ids: Any):
    """The tactical has a sell out campaign among `campana_ids`."""
    return exists().where(SellOutCampana.tactical_id == Tactical.id, SellOutCampana.id.in_(campana_ids))


def _contiene(tipo: str):
    """The tactical has a line of kind `tipo` (SISO S1), told apart the way `serializar` names a line's `alcance`."""
    bono = SellInBonoMarca.tactical_id == Tactical.id
    filas = select(SellOutCampanaGrupo.campana_id).join(
        OffsetGrupoFiltro, OffsetGrupoFiltro.grupo_id == SellOutCampanaGrupo.grupo_id
    )
    if tipo == "factura":
        return or_(
            exists().where(bono, SellInBonoMarca.alcance == "factura"),
            exists().where(SellInCompra.tactical_id == Tactical.id),
            exists().where(TacticalFacturaPendiente.tactical_id == Tactical.id),
        )
    if tipo == "productos":
        de_campana = filas.where(OffsetGrupoFiltro.item_id.isnot(None))
        return or_(_filtros_sell_out(de_campana), exists().where(bono, SellInBonoMarca.alcance == "modelos"))
    # A campaign's scope row without a product is its brand when it has one, else its category (`_lineas_campanas`).
    con_marca = func.coalesce(OffsetGrupoFiltro.marca, "") != ""
    de_campana = filas.where(OffsetGrupoFiltro.item_id.is_(None), con_marca if tipo == "marca" else ~con_marca)
    return or_(_filtros_sell_out(de_campana), exists().where(bono, SellInBonoMarca.alcance == tipo))


def _alcanza_producto(db: Session, q: str):
    """One of the tactical's lines reaches a product whose code or description contains `q` (SISO S2), with each
    engine's own rule: a sell out campaign through its groups' filter rows (`alcance.campanas_que_alcanzan`); a sell in
    bonus by brand, category, its models or its invoice's invoiced lines (`bonos._alcanzadas`); an invoice total by
    its purchase's lines."""
    coincide = or_(contiene(ProductoERP.codigo, q), contiene(ProductoERP.descripcion, q))
    productos = select(ProductoERP.item_id).where(coincide)
    por_bono = or_(
        and_(SellInBonoMarca.alcance == "marca", SellInBonoMarca.marca.in_(select(ProductoERP.marca).where(coincide))),
        and_(
            SellInBonoMarca.alcance == "categoria",
            SellInBonoMarca.categoria.in_(select(ProductoERP.categoria).where(coincide)),
        ),
        and_(
            SellInBonoMarca.alcance == "modelos",
            exists().where(SellInBonoItem.bono_id == SellInBonoMarca.id, SellInBonoItem.item_id.in_(productos)),
        ),
        and_(
            SellInBonoMarca.alcance == "factura",
            exists().where(
                PedidoCompraLineaFacturada.pedido_id == SellInBonoMarca.pedido_id,
                PedidoCompraLineaFacturada.item_id.in_(productos),
            ),
        ),
    )
    por_compra = exists().where(
        SellInCompra.tactical_id == Tactical.id,
        SellInCompraItem.compra_id == SellInCompra.id,
        SellInCompraItem.item_id.in_(productos),
    )
    campanas_ = sell_out_alcance.campanas_que_alcanzan(db, productos).subquery()
    return or_(
        _filtros_sell_out(select(campanas_.c.campana_id)),
        exists().where(SellInBonoMarca.tactical_id == Tactical.id, por_bono),
        por_compra,
    )


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
    elif filtros.estado == "pendientes_aprobacion":  # S8: what the approver still has to review
        query = query.filter(Tactical.estado == "pendiente")
    if filtros.desde is not None:
        query = query.filter(Tactical.fecha_hasta >= filtros.desde)
    if filtros.hasta is not None:
        query = query.filter(Tactical.fecha_desde <= filtros.hasta)
    if _texto(filtros.q):
        q = _texto(filtros.q)
        query = query.filter(or_(contiene(Tactical.nombre, q), contiene(Tactical.referencia, q)))
    if filtros.contiene:
        query = query.filter(_contiene(filtros.contiene))
    if _texto(filtros.producto):
        query = query.filter(_alcanza_producto(db, _texto(filtros.producto)))
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


def _usado_por_linea(ids: Select) -> Subquery:
    """One row per child of the tacticals in `ids` (a subquery of ids): `(tactical_id, moneda, monto, tope)`, `monto`
    being its `monto_usado` exactly as `serializar` computes it (`_lineas_campanas`, `_lineas_bonos` through
    `bonos_crud.serializar`, `_lineas_compras`), rounded to cents per child. A child that used nothing is a 0 row.
    A cost bonus and an invoice total used what costo SI took off their invoices (T5 PR B, L26, `costo_si.generado`).
    `estimado` is always 0: each invoice's amount is at its own rate, nothing waits for the collection rate.
    `tope` is its money cap in that same currency (S6): its `tope_monto`, or the total of a Monto total child (the
    total is its cap; a cost bonus keeps it in ARS, converted at the tactical's fixed rate); NULL without one. A pending
    child applies nothing, so it is left out (tacticals approval S12)."""
    cero = literal(0)

    def tope(modelo):
        return func.coalesce(modelo.tope_monto, case((modelo.tipo == "monto_total", modelo.monto_total))).label("tope")

    campanas_ = (
        select(
            SellOutCampana.tactical_id.label("tactical_id"),
            SellOutCampana.moneda.label("moneda"),
            func.round(func.coalesce(func.sum(SellOutConsumo.monto), cero), 2).label("monto"),
            tope(SellOutCampana),
            cero.label("estimado"),
        )
        .select_from(SellOutCampana)
        .outerjoin(SellOutConsumo, SellOutConsumo.campana_id == SellOutCampana.id)
        .where(SellOutCampana.tactical_id.in_(ids), SellOutCampana.estado != aprobacion.PENDIENTE)
        .group_by(SellOutCampana.id)
    )
    # A cost bonus: what costo SI took off its invoices, in the bonus's own currency, as `monto_generado`.
    costo = SellInBonoMarca.base == BASE_COSTO_VENTA
    por_bono = generado.por_bono().subquery()
    bonos_costo_ = (
        select(
            SellInBonoMarca.tactical_id,
            SellInBonoMarca.moneda,
            func.round(func.coalesce(por_bono.c.monto, cero), 2),
            tope(SellInBonoMarca),
            cero,
        )
        .select_from(SellInBonoMarca)
        .outerjoin(por_bono, por_bono.c.bono_id == SellInBonoMarca.id)
        .where(SellInBonoMarca.tactical_id.in_(ids), costo, SellInBonoMarca.estado != aprobacion.PENDIENTE)
    )
    # Any other bonus: its active purchases' assigned amounts in the bonus's own currency (another one is not added).
    bonos_compras = (
        select(
            SellInBonoMarca.tactical_id,
            SellInBonoMarca.moneda,
            func.round(func.coalesce(func.sum(SellInCompraItem.monto_asignado), cero), 2),
            tope(SellInBonoMarca),
            cero,
        )
        .select_from(SellInBonoMarca)
        .outerjoin(
            SellInCompra,
            and_(
                SellInCompra.bono_id == SellInBonoMarca.id,
                SellInCompra.estado == "activa",
                SellInCompra.moneda == SellInBonoMarca.moneda,
            ),
        )
        .outerjoin(SellInCompraItem, SellInCompraItem.compra_id == SellInCompra.id)
        .where(SellInBonoMarca.tactical_id.in_(ids), ~costo, SellInBonoMarca.estado != aprobacion.PENDIENTE)
        .group_by(SellInBonoMarca.id)
    )
    # An invoice total: what costo SI took off its invoices, in the purchase's own currency.
    por_compra = generado.por_compra().subquery()
    compras_ = (
        select(
            SellInCompra.tactical_id,
            SellInCompra.moneda,
            func.round(func.coalesce(por_compra.c.monto, cero), 2),
            SellInCompra.monto_total,  # an invoice total: in the purchase's own currency, its own cap
            cero,
        )
        .select_from(SellInCompra)
        .outerjoin(por_compra, por_compra.c.compra_id == SellInCompra.id)
        .where(SellInCompra.tactical_id.in_(ids), SellInCompra.estado != aprobacion.PENDIENTE)
    )
    return union_all(campanas_, bonos_costo_, bonos_compras, compras_).subquery()


def kpis(db: Session, filtros: Filtros, hoy: Optional[date] = None) -> dict:
    """Pendientes and Cobrados over every tactical the other filters match (S4): how many, and the money they used
    per currency, the sum of their lines' `monto_usado` exactly as the list's Avance column shows it (each line in
    its own currency), next to the sum of their money caps in that currency (S6, None
    when no line there has one; `tope_parcial` when only some lines there have one), and how many have no money cap
    on any line. Three SQL aggregates and one query that logs the costo SI steps with no cost, whatever the number of
    tacticals. ARS first, then USD; a currency with no line is left out."""
    cobrado = exists().where(TacticalCobranza.tactical_id == Tactical.id)
    base = (
        _consulta(db, filtros, hoy or date.today())
        # Money KPIs count only what applies (tacticals approval S12): a pending tactical is counted apart
        # (`contar_pendientes_aprobacion`), whatever the estado filter.
        .filter(Tactical.estado != aprobacion.PENDIENTE)
        .order_by(None)
        .with_entities(Tactical.id.label("id"), cobrado.label("cobrado"))
        .subquery()
    )
    cantidades = {bool(c): int(n) for c, n in db.query(base.c.cobrado, func.count()).group_by(base.c.cobrado)}
    lineas = _usado_por_linea(select(base.c.id))
    # A costo SI step with no cost is left out of the sums below (§7): logged with its item and date.
    generado.avisar_sin_costo(db, select(base.c.id))
    montos: dict[bool, dict[str, dict]] = defaultdict(dict)
    for c, moneda, monto, tope, con_tope_, lineas_, estimado in (
        db.query(
            base.c.cobrado,
            lineas.c.moneda,
            func.sum(lineas.c.monto),
            func.sum(lineas.c.tope),
            func.count(lineas.c.tope),
            func.count(),
            func.max(lineas.c.estimado),
        )
        .join(lineas, lineas.c.tactical_id == base.c.id)
        .group_by(base.c.cobrado, lineas.c.moneda)
    ):
        montos[bool(c)][moneda] = {
            "moneda": moneda,
            "monto": _cents(monto),
            "tope": None if tope is None else _cents(tope),
            # The cap covers only some of the lines `monto` sums: comparing them would read "900 of 500".
            "tope_parcial": 0 < con_tope_ < lineas_,
            # Kept for the client: always False since costo SI values each invoice at its own rate (T5 PR B, L26).
            "estimado": bool(estimado),
        }
    con_tope = (
        select(lineas.c.tactical_id, func.count(lineas.c.tope).label("topes")).group_by(lineas.c.tactical_id).subquery()
    )
    sin_tope = {
        bool(c): int(n)
        for c, n in db.query(base.c.cobrado, func.count())
        .outerjoin(con_tope, con_tope.c.tactical_id == base.c.id)
        .filter(func.coalesce(con_tope.c.topes, 0) == 0)
        .group_by(base.c.cobrado)
    }
    return {
        clave: {
            "cantidad": cantidades.get(cobrados, 0),
            "sin_tope": sin_tope.get(cobrados, 0),
            "montos": [montos[cobrados][m] for m in ("ARS", "USD") if m in montos[cobrados]],
        }
        for clave, cobrados in (("pendientes", False), ("cobrados", True))
    }


# --- approval inbox (tacticals approval S11, S12) ---------------------------------------------------------------------

CARGAS_PENDIENTES_MAX = 200  # the largest page of the approval inbox


def _sueltas(modelo):
    """Its standalone rows waiting for approval: `pendiente` and of no tactical (a tactical's line is approved with
    its tactical)."""
    return and_(modelo.estado == aprobacion.PENDIENTE, modelo.tactical_id.is_(None))


def _consultas_sueltas(db: Session, tipos: list[str]) -> list[tuple[str, Any, Query]]:
    """`(origen, model, query)` per kind of standalone load the caller may read: a sell in bonus or purchase, a sell
    out campaign or a legacy profit offset (S10: a sell out discount on profit, never a tactical's line). A purchase a
    bonus generated (`origen = 'bono_marca'`) follows its bonus and is never a load."""
    salida: list[tuple[str, Any, Query]] = []
    if "sell_in" in tipos:
        salida.append(("sell_in_bono", SellInBonoMarca, db.query(SellInBonoMarca).filter(_sueltas(SellInBonoMarca))))
        compras_ = db.query(SellInCompra).filter(_sueltas(SellInCompra), SellInCompra.origen == "manual")
        salida.append(("sell_in_compra", SellInCompra, compras_))
    if "sell_out" in tipos:
        salida.append(("sell_out_campana", SellOutCampana, db.query(SellOutCampana).filter(_sueltas(SellOutCampana))))
        offsets = db.query(OffsetGanancia).filter(OffsetGanancia.estado == aprobacion.PENDIENTE)
        salida.append(("offset_ganancia", OffsetGanancia, offsets))
    return salida


def _creada(modelo):
    """When the load was stored: a legacy offset names it `fecha_creacion`."""
    return modelo.fecha_creacion if modelo is OffsetGanancia else modelo.created_at


def _carga(origen: str, fila: Any) -> dict:
    if origen == "sell_in_bono":
        nombre = fila.descripcion or f"Bono {fila.marca or fila.categoria or f'#{fila.id}'}"
        desde, hasta, marca = fila.fecha_desde, fila.fecha_hasta, fila.marca
    elif origen == "sell_in_compra":
        nombre = fila.descripcion or f"Compra #{fila.id}"
        desde = hasta = fila.fecha_compra
        marca = None
    elif origen == "offset_ganancia":
        alcance = fila.marca or fila.categoria or (f"producto {fila.item_id}" if fila.item_id else None)
        nombre = fila.descripcion or f"Offset {alcance or f'#{fila.id}'}"
        desde, hasta, marca = fila.fecha_desde, fila.fecha_hasta, fila.marca
    else:
        nombre, desde, hasta, marca = fila.nombre, fila.fecha_desde, fila.fecha_hasta, None
    return {
        "origen": origen,
        "id": fila.id,
        "nombre": nombre,
        "marca": marca,
        "moneda": fila.moneda or "ARS",  # an offset may have none: it reads ARS, as its API answers
        "fecha_desde": desde,
        "fecha_hasta": hasta,
        "usuario_id": fila.usuario_id,
        "created_at": fila.fecha_creacion if origen == "offset_ganancia" else fila.created_at,
    }


def cargas_pendientes(
    db: Session, tipos: list[str], page: int = 1, page_size: int = CARGAS_PENDIENTES_MAX
) -> list[dict]:
    """One page of the standalone loads waiting for approval (S11: "no pending item may be unreachable from the UI"),
    of the kinds in `tipos`, newest first across kinds; `contar_cargas_pendientes` counts them all. Each is
    `{origen, id, ...}` with the same `origen` as a tactical's line, so the screen opens its record's panel, where it
    is approved (an offset is approved from the inbox itself)."""
    hasta = page * page_size  # every kind's first `hasta` rows hold the first `hasta` of the merged order
    filas = []
    for origen, modelo, query in _consultas_sueltas(db, tipos):
        recientes = query.order_by(_creada(modelo).desc(), modelo.id.desc()).limit(hasta)
        filas += [_carga(origen, fila) for fila in recientes]
    filas.sort(key=lambda c: (c["created_at"], c["id"]), reverse=True)
    return filas[hasta - page_size : hasta]


def contar_cargas_pendientes(db: Session, tipos: list[str]) -> int:
    """How many standalone loads of the kinds in `tipos` wait for approval (the pages of `cargas_pendientes`)."""
    return sum(query.order_by(None).count() for _, _, query in _consultas_sueltas(db, tipos))


def con_autores(db: Session, cargas: list[dict]) -> list[dict]:
    """`cargas_pendientes` with who loaded each one (`usuario_nombre`), for the API: one query."""
    ids = {c["usuario_id"] for c in cargas} - {None}
    nombres = dict(db.query(Usuario.id, Usuario.nombre).filter(Usuario.id.in_(ids))) if ids else {}
    for c in cargas:
        c["usuario_nombre"] = nombres.get(c["usuario_id"])
    return cargas


def contar_pendientes_aprobacion(db: Session, filtros: Filtros, hoy: Optional[date] = None) -> int:
    """How many loads wait for approval (S12: "a separate 'N pendientes de aprobación' count"): the pending
    tacticals the other filters match (whatever the estado filter asks) plus every standalone pending load of the
    kinds in `filtros.tipos`. That is what the "Pendientes de aprobación" filter shows."""
    pendientes = replace(filtros, estado="pendientes_aprobacion")
    tacticals_ = _consulta(db, pendientes, hoy or date.today()).order_by(None).count()
    return tacticals_ + contar_cargas_pendientes(db, filtros.tipos)


# --- collection (tactical cobranza S1, S2) ----------------------------------------------------------------------------

_COBRANZA_TEXTOS = ("nc_numero", "distribuidor", "otro_detalle", "observaciones")


def cobrar(db: Session, tactical_id: int, data: TacticalCobranzaIn, usuario_id: int) -> Optional[Tactical]:
    """Save the tactical's one collection record (create or replace every field): it reads "Cobrado". None when the
    tactical does not exist; `TacticalPendienteDeCobro` (a 409) while it waits for approval (tacticals approval S16:
    it is approved before it is collected; undoing a record it kept from before stays allowed, `deshacer_cobro`). The
    tactical row is locked so two saves never race into a duplicate."""
    try:
        tactical = db.query(Tactical).filter(Tactical.id == tactical_id).populate_existing().with_for_update().first()
        if tactical is None:
            return None
        if tactical.estado == "pendiente":
            raise TacticalPendienteDeCobro(SIN_APROBAR_COBRO)
        cobranza = db.query(TacticalCobranza).filter(TacticalCobranza.tactical_id == tactical_id).first()
        # The collection rate is no longer required (sell-in-costo-si T5 PR A, L24): it only converted the per-sale
        # cost bonuses, and nothing applies them any more. Still accepted where a USD cost line exists, and a stored
        # one is kept when a save leaves it out, so the stored usage rows keep reading as they did.
        if data.tipo_cambio is not None and not _bonos_al_cobro(db, tactical):
            raise TacticalError(TC_COBRO_SIN_USD)
        if cobranza is None:
            cobranza = TacticalCobranza(tactical_id=tactical_id)
            db.add(cobranza)
        cobranza.fecha_cobro = data.fecha_cobro
        if data.tipo_cambio is not None:
            cobranza.tipo_cambio = data.tipo_cambio
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


class TacticalPendienteDeCobro(TacticalError):
    """A tactical waiting for approval is not collected (S16); the message is the screen's tooltip."""


SIN_APROBAR_COBRO = "Se aprueba antes de cobrar"
TC_COBRO_SIN_USD = (
    "Solo un tactical de sell in en USD con tipo de cambio al cobro y una línea en USD lleva tipo de cambio del cobro"
)


def _bonos_al_cobro(db: Session, tactical: Tactical) -> list[int]:
    """The active USD cost bonuses of a sell in USD `al_cobro` tactical: the only ones a collection rate was ever
    for (`cobrar`)."""
    if (tactical.tipo, tactical.moneda, tactical.tc_modo) != ("sell_in", "USD", "al_cobro"):
        return []
    b = SellInBonoMarca
    return [
        bid
        for (bid,) in db.query(b.id).filter(
            b.tactical_id == tactical.id, b.base == BASE_COSTO_VENTA, b.moneda == "USD", b.estado.in_(aprobacion.VIVAS)
        )
    ]


def deshacer_cobro(db: Session, tactical_id: int) -> bool:
    """Undo: delete the tactical's collection record, so it reads "Pendiente" again. False when it had none. A USD
    `al_cobro` cost line goes back to the latest BNA (a cost bonus is no longer applied per sale, L24: nothing to
    queue)."""
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
                # The rate an `al_cobro` campaign already took when the brand paid (S8: an edit warns it is discarded).
                "tc_al_cobro": c.tipo_cambio if c.tc_modo == "al_cobro" and c.tc_definido_en is not None else None,
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
    # An invoice line whose operation has no supplier invoice yet waits for it (sell in factura pendiente S4).
    pids = {b.pedido_id for b in bonos if b.alcance == "factura" and b.pedido_id is not None}
    sin_factura = (
        {
            pid
            for (pid,) in db.query(PedidoCompra.id).filter(
                PedidoCompra.id.in_(pids), PedidoCompra.fecha_factura.is_(None)
            )
        }
        if pids
        else set()
    )
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
                "esperando_factura": bono.alcance == "factura" and bono.pedido_id in sin_factura,
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
    # What costo SI took off its invoices, in the purchase's own currency (T5 PR B, L26).
    usado = generado.de_compras(db, cids)
    salida = []
    for c in compras_:
        unidades, monto = usado.get(c.id, (0, Decimal(0)))
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


def _lineas_pendientes(db: Session, ids: list[int]) -> list[dict]:
    """The invoice totals still waiting for their invoice (or voided while waiting), shaped like `_lineas_compras`:
    nothing used yet. An applied one is read as the purchase it became."""
    salida = []
    for fila, numero, estado_tactical in (
        db.query(TacticalFacturaPendiente, PedidoCompra.numero, Tactical.estado)
        .join(PedidoCompra, PedidoCompra.id == TacticalFacturaPendiente.pedido_id)
        .join(Tactical, Tactical.id == TacticalFacturaPendiente.tactical_id)
        .filter(TacticalFacturaPendiente.tactical_id.in_(ids), TacticalFacturaPendiente.estado != "aplicada")
    ):
        salida.append(
            {
                "tactical_id": fila.tactical_id,
                "id": fila.id,
                "linea": fila.tactical_linea,
                "origen": ORIGEN_PENDIENTE,
                "estado": aprobacion.estado_de_linea(estado_tactical) if fila.estado == "pendiente" else "anulada",
                "alcance": "factura",
                "item_ids": [],
                "marca": None,
                "categoria": None,
                "pedido_compra_id": fila.pedido_id,
                "pedido_numero": numero,
                "modo_monto": "monto_total",
                "valor": fila.valor,
                "reparto_criterio": None,
                "moneda": fila.moneda,
                "tope_unidades": None,
                "tope_monto": None,
                "unidades_usadas": 0,
                "monto_usado": _cents(0),
                "esperando_factura": fila.estado == "pendiente",
            }
        )
    return salida


def _cobranza(cobranza: Optional[TacticalCobranza]) -> Optional[dict]:
    if cobranza is None:
        return None
    columnas = ("fecha_cobro", "medio", *_COBRANZA_TEXTOS, "tipo_cambio", "usuario_id", "created_at", "updated_at")
    return {c: getattr(cobranza, c) for c in columnas}


def _con_facturas_elegidas(db: Session, lineas: list[dict]) -> None:
    """Each line's invoices (S5): `facturas_ct` the pick (None: every invoice of its operation, also on a line that is
    not an invoice line) and `facturas_elegidas` the picked invoices with their readable ERP number."""
    de_factura = [h for h in lineas if h["alcance"] == "factura"]
    elegidas = facturas_elegidas.de_lineas(db, [(h["tactical_id"], h["linea"]) for h in de_factura])
    pedidos = {h["pedido_compra_id"] for h in de_factura if (h["tactical_id"], h["linea"]) in elegidas}
    numeros = {
        f["ct_transaction_id"]: f["numero"]
        for facturas in facturas_elegidas.facturas_de(db, pedidos).values()
        for f in facturas
    }
    for h in lineas:
        cts = elegidas.get((h["tactical_id"], h["linea"])) if h["alcance"] == "factura" else None
        h["facturas_ct"] = sorted(cts) if cts else None
        h["facturas_elegidas"] = (
            [{"ct_transaction_id": ct, "numero": numeros.get(ct)} for ct in sorted(cts)] if cts else None
        )


def con_aprobadores(db: Session, salida: list[dict]) -> list[dict]:
    """`serializar`'s tacticals with the approver's name (`aprobado_por_nombre`, S8: "Aprobado por X el ..."), for the
    API: one query, only when some was approved."""
    ids = {t["aprobado_por"] for t in salida} - {None}
    nombres = dict(db.query(Usuario.id, Usuario.nombre).filter(Usuario.id.in_(ids))) if ids else {}
    for t in salida:
        t["aprobado_por_nombre"] = nombres.get(t["aprobado_por"])
    return salida


def serializar(db: Session, tacticals: Iterable[Tactical]) -> list[dict]:
    """Each tactical with its lines, one per child, in line order (module docstring): a few queries per page."""
    tacticals = list(tacticals)
    ids = [t.id for t in tacticals]
    lineas = (
        (_lineas_campanas(db, ids) + _lineas_bonos(db, ids) + _lineas_compras(db, ids) + _lineas_pendientes(db, ids))
        if ids
        else []
    )
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
    for linea in lineas:
        # Read off each invoice at its own rate (T5 PR B, L26): nothing is an estimate any more.
        linea["monto_estimado"] = False
    _con_facturas_elegidas(db, lineas)
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
        linea.setdefault("esperando_factura", False)
        de_tactical[linea.pop("tactical_id")].append(linea)
    columnas = (
        "id", "tipo", "nombre", "marca", "referencia", "fecha_desde", "fecha_hasta", "moneda", "tc_modo",
        "tipo_cambio", "incluye_iva", "acumulable", "todas_tiendas", "tope_compartido", "nota", "estado",
        "usuario_id", "aprobado_por", "aprobado_at", "created_at", "updated_at",
    )  # fmt: skip

    return [
        {
            **{c: getattr(t, c) for c in columnas},
            "tiendas": [{"tipo": fila.tipo, "store_id": fila.store_id} for fila in t.tiendas],
            "marcas": [fila.marca for fila in t.marcas],
            "por_factura": _hijos_por_factura(t, de_tactical[t.id]),
            # Some active invoice line still waits for its operation's invoice (sell in factura pendiente S4).
            "esperando_factura": any(
                h["esperando_factura"] and h["estado"] in aprobacion.VIVAS for h in de_tactical[t.id]
            ),
            "lineas": de_tactical[t.id],
            "cobranza": _cobranza(t.cobranza),
            # Never asked any more (sell-in-costo-si T5 PR A, L24): no cost bonus is converted per sale (`cobrar`).
            "pide_tc_cobro": False,
        }
        for t in tacticals
    ]
