"""What the costo SI engine reads, per product (S2-S7, S11; queries from handoffs/sell-in-costo-si-t1.md).

- Start (S2): the first sell-in date: the earliest brand bonus that reaches the product (`fecha_desde`) or the earliest
  purchase invoice a Compras sell in reaches. Its cost: the `tb_item_cost_list_history` row (list 1, USD) in force at
  00:00 of that day, i.e. the last row of an earlier day, so a same-day typo corrected minutes later never counts.
- Purchases (S4): every purchase invoice (`v_facturas_compra_vigentes`, 'FACTURA') of the product, dated by the
  supplier invoice date `ct_date`, at its net unit price. FX for ARS: a PM correction (`costo_si_factura_tc`), else
  the linked Compras operation's TC (manual first), else `tipo_cambio.venta` on the invoice date (or the latest
  before it).
- Sell ins (S5, S6): the active Compras sell ins (`sell_in_compras`) of the operations the invoice is linked to, as a
  % of the item's net base; plus every active brand bonus by %, of the sale-cost kind (the loyalty: "El loyalty es
  por marca, aplica a cualquier proveedor", L7.2), on EVERY invoice of a product it reaches dated in its range, from
  any supplier and linked to Compras or not (S7).
- Available stock at 00:00 of a day (S3): principal = GBP depot 1 physical minus the units of sale orders generated
  and not invoiced at that instant (pending transfers to Full, customer 2849, do not count: the units still exist).
  Full = Mercado Libre's Full available stock, NOT GBP depot 17 (L8): the current ML Full stock of the product's
  inventory ids, walked back with ML's Full stock operations (`full_ml`). A day with a daily photo
  (`costo_si_stock_diario`) reads the photo instead.
- Combos (S11, L7.1) have no stock, purchases or sell ins of their own: the engine never computes one (`es_combo`);
  their cost is their components' at read time. A combo of the PC category is its own product (L2.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import BigInteger

from app.services.combos.pcs import pcs_entre
from app.services.costo_si import full_ml
from app.services.costo_si.engine import Compra, Inicio, SellIn

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
DEPOSITO_PRINCIPAL = 1
CLIENTE_TRANSFERENCIA_FULL = 2849
CURR_USD = 2
# Invoices dated before the start can still be entering stock after it (GBP loads them up to ~2 weeks late).
VENTANA_PREVIAS = timedelta(days=90)


def inicio_del_dia(dia: date) -> datetime:
    """00:00 of `dia`, naive, as GBP's mirror stores its timestamps (local time)."""
    return datetime.combine(dia, time.min)


def es_combo(db: Session, item_id: int) -> bool:
    """A combo that is not a PC: no costo SI of its own (S11)."""
    combo = db.execute(text("SELECT 1 FROM combo_componentes WHERE combo_item_id = :i LIMIT 1"), {"i": item_id}).first()
    return combo is not None and item_id not in pcs_entre(db, [item_id])


# ---------------------------------------------------------------------------------------------------------- start

_BONOS_SQL = text("""
    SELECT b.id, COALESCE(bi.porcentaje, b.porcentaje) AS pct, b.fecha_desde, b.fecha_hasta
    FROM sell_in_bonos_marca b
    JOIN productos_erp p ON p.item_id = :i
    LEFT JOIN sell_in_bono_items bi ON bi.bono_id = b.id AND bi.item_id = :i
    WHERE b.estado = 'activa' AND b.base = 'costo_venta' AND b.tipo = 'porcentaje' AND b.tactical_id IS NULL
      AND ((b.alcance = 'marca' AND p.marca = b.marca AND (b.categoria IS NULL OR p.categoria = b.categoria))
        OR (b.alcance = 'categoria' AND p.categoria = b.categoria)
        OR (b.alcance = 'modelos' AND bi.id IS NOT NULL))
    ORDER BY b.id
""")

_PRIMERA_FACTURA_CON_SELL_IN_SQL = text("""
    SELECT min(ct.ct_date)::date
    FROM sell_in_compra_items ci
    JOIN sell_in_compras c ON c.id = ci.compra_id AND c.estado = 'activa'
    JOIN pedido_compra_facturas pf
      ON pf.pedido_id = c.bono_pedido_id
      OR pf.pedido_id IN (SELECT cp.pedido_compra_id FROM sell_in_compra_pedidos cp WHERE cp.compra_id = c.id)
    JOIN tb_commercial_transactions ct ON ct.ct_transaction = pf.ct_transaction_id
    JOIN tb_item_transactions it ON it.ct_transaction = ct.ct_transaction AND it.item_id = ci.item_id
    WHERE ci.item_id = :i
""")

_COSTO_LISTA_SQL = text("""
    SELECT iclh_price FROM tb_item_cost_list_history
    WHERE item_id = :i AND coslis_id = 1 AND curr_id = 2 AND iclh_cd < :t
    ORDER BY iclh_cd DESC, iclh_id DESC LIMIT 1
""")


@dataclass(frozen=True)
class Bono:
    id: int
    porcentaje: Decimal
    desde: date
    hasta: date


def bonos_de(db: Session, item_id: int) -> List[Bono]:
    return [Bono(r[0], Decimal(r[1]), r[2], r[3]) for r in db.execute(_BONOS_SQL, {"i": item_id}) if r[1]]


def primera_fecha_sell_in(db: Session, item_id: int, bonos: Sequence[Bono]) -> Optional[date]:
    """S2: the date the first sell in applies, None when none does."""
    fechas = [b.desde for b in bonos]
    factura = db.execute(_PRIMERA_FACTURA_CON_SELL_IN_SQL, {"i": item_id}).scalar()
    if factura is not None:
        fechas.append(factura)
    return min(fechas) if fechas else None


def costo_lista(db: Session, item_id: int, dia: date) -> Optional[Decimal]:
    value = db.execute(_COSTO_LISTA_SQL, {"i": item_id, "t": inicio_del_dia(dia)}).scalar()
    return Decimal(value) if value is not None else None


# ------------------------------------------------------------------------------------------------------ purchases

_FACTURAS_SQL = text("""
    SELECT ct.ct_transaction, ct.ct_date::date AS fecha, min(it.it_transaction) AS orden, min(it.it_cd) AS entrada,
           sum(it.it_qty) AS cantidad, sum(it.it_qty * it.it_price) / NULLIF(sum(it.it_qty), 0) AS precio,
           max(it.curr_id) AS curr_id
    FROM v_facturas_compra_vigentes v
    JOIN tb_commercial_transactions ct ON ct.ct_transaction = v.ct_transaction
    JOIN tb_item_transactions it ON it.ct_transaction = ct.ct_transaction AND it.item_id = :i
    WHERE v.clasificacion = 'FACTURA' AND ct.ct_date >= :desde
    GROUP BY ct.ct_transaction, ct.ct_date
    ORDER BY ct.ct_date, min(it.it_transaction)
""")

_PEDIDOS_SQL = text("""
    SELECT pf.ct_transaction_id, pf.pedido_id, COALESCE(p.tipo_cambio_manual, p.tipo_cambio) AS tc
    FROM pedido_compra_facturas pf JOIN pedidos_compra p ON p.id = pf.pedido_id
    WHERE pf.ct_transaction_id = ANY(:cts)
    ORDER BY pf.ct_transaction_id, pf.pedido_id
""").bindparams(bindparam("cts", type_=ARRAY(BigInteger)))

_TC_MANUAL_SQL = text(
    "SELECT ct_transaction, tipo_cambio FROM costo_si_factura_tc WHERE ct_transaction = ANY(:cts)"
).bindparams(bindparam("cts", type_=ARRAY(BigInteger)))

_TC_FECHA_SQL = text(
    "SELECT venta FROM tipo_cambio WHERE moneda = 'USD' AND fecha <= :d AND venta > 0 ORDER BY fecha DESC LIMIT 1"
)

_SELL_IN_COMPRAS_SQL = text("""
    SELECT c.id, c.tipo, c.porcentaje, ci.cantidad, ci.costo_base_unit, ci.monto_asignado
    FROM sell_in_compras c
    JOIN sell_in_compra_items ci ON ci.compra_id = c.id AND ci.item_id = :i
    WHERE c.estado = 'activa'
      AND (c.bono_pedido_id = ANY(:pedidos)
           OR EXISTS (SELECT 1 FROM sell_in_compra_pedidos cp
                      WHERE cp.compra_id = c.id AND cp.pedido_compra_id = ANY(:pedidos)))
    ORDER BY c.id
""").bindparams(bindparam("pedidos", type_=ARRAY(BigInteger)))


@dataclass
class Factura:
    ct_transaction: int
    fecha: date
    orden: int
    entrada: datetime
    cantidad: int
    precio: Decimal
    curr_id: Optional[int]
    pedidos: List[int] = field(default_factory=list)
    tc_pedido: Optional[Decimal] = None


def facturas_de(db: Session, item_id: int, desde: date) -> List[Factura]:
    facturas = [
        Factura(r[0], r[1], r[2], r[3], int(r[4] or 0), Decimal(r[5] or 0), r[6])
        for r in db.execute(_FACTURAS_SQL, {"i": item_id, "desde": inicio_del_dia(desde)})
    ]
    por_ct = {f.ct_transaction: f for f in facturas}
    if por_ct:
        for ct, pedido, tc in db.execute(_PEDIDOS_SQL, {"cts": list(por_ct)}):
            f = por_ct[ct]
            f.pedidos.append(pedido)
            if f.tc_pedido is None and tc:
                f.tc_pedido = Decimal(tc)
    return facturas


def tipo_cambio_de(db: Session, f: Factura, manuales: Dict[int, Decimal]) -> Tuple[Optional[Decimal], str]:
    """S4 (L4.5): the PM's correction, else the Compras operation's TC, else the invoice date's."""
    if f.curr_id == CURR_USD:
        return None, "usd"
    if f.ct_transaction in manuales:
        return manuales[f.ct_transaction], "manual"
    if f.tc_pedido is not None:
        return f.tc_pedido, "pedido"
    venta = db.execute(_TC_FECHA_SQL, {"d": f.fecha}).scalar()
    return (Decimal(str(venta)) if venta else None), "fecha_factura"


def sell_ins_de(db: Session, item_id: int, f: Factura, bonos: Sequence[Bono]) -> Tuple[SellIn, ...]:
    """S5/S6: the Compras sell ins of the invoice's operations, then the brand bonuses of its date."""
    out: List[SellIn] = []
    if f.pedidos:
        for cid, tipo, pct, cantidad, base, monto in db.execute(
            _SELL_IN_COMPRAS_SQL, {"i": item_id, "pedidos": f.pedidos}
        ):
            if tipo == "porcentaje" and pct is not None:
                porcentaje = Decimal(pct)
            elif cantidad and base:
                porcentaje = Decimal(monto) / (Decimal(cantidad) * Decimal(base)) * 100
            else:
                continue
            out.append(SellIn("compra", int(cid), porcentaje.quantize(Decimal("0.0001"))))
    out.extend(SellIn("bono", b.id, b.porcentaje) for b in bonos if b.desde <= f.fecha <= b.hasta)
    return tuple(out)


# --------------------------------------------------------------------------------------------------------- stock

_FISICO_SQL = text("""
    SELECT it.it_storeprevious FROM tb_item_transactions it
    WHERE it.item_id = :i AND it.stor_id = :d AND it.it_cd >= :t
    ORDER BY it.it_transaction LIMIT 1
""")

_FISICO_ULTIMO_SQL = text("""
    SELECT COALESCE(it.it_storeprevious, 0) + CASE WHEN ct.sd_id IN (1, 2) THEN -it.it_qty ELSE it.it_qty END
    FROM tb_item_transactions it
    LEFT JOIN tb_commercial_transactions ct ON ct.ct_transaction = it.ct_transaction
    WHERE it.item_id = :i AND it.stor_id = :d
    ORDER BY it.it_transaction DESC LIMIT 1
""")

# Units of sale orders generated at :t and not invoiced yet at :t (T1 §1.1). Orders to the Full transfer customer
# do not count. The order mirror keeps stale duplicate lines: one quantity (the max) per order.
_PENDIENTE_SQL = text("""
    SELECT
      (SELECT COALESCE(sum(it.it_qty), 0)
       FROM tb_item_transactions it
       JOIN tb_commercial_transactions ct ON ct.ct_transaction = it.ct_transaction AND ct.sd_id IN (1, 2)
       WHERE it.item_id = :i AND it.stor_id = :d AND it.it_cd > :t AND ct.cust_id IS DISTINCT FROM :full
         -- the order's creation: its first history row (correlated, only for this item's lines after t)
         AND (SELECT min(hh.soh_cd) FROM tb_sale_order_header_history hh
              WHERE hh.bra_id = it.bra_id AND hh.soh_id = it.it_soh_id) <= :t)
    + (SELECT COALESCE(sum(q), 0) FROM (
         SELECT max(d.sod_qty) AS q
         FROM tb_sale_order_detail d
         JOIN tb_sale_order_header h ON h.bra_id = d.bra_id AND h.soh_id = d.soh_id
         WHERE d.item_id = :i AND d.stor_id = :d AND h.soh_statusof IS NULL AND h.soh_cd <= :t
           AND h.cust_id IS DISTINCT FROM :full
         GROUP BY d.bra_id, d.soh_id) abiertos)
    + (SELECT COALESCE(sum(q), 0) FROM (
         SELECT dh.bra_id, dh.soh_id, max(dh.sod_qty) AS q, min(hh.soh_cd) AS creado, max(hh.sohh_cd) AS cerrado
         FROM tb_sale_order_detail_history dh
         JOIN tb_sale_order_header_history hh
           ON hh.sohh_id = dh.sohh_id AND hh.bra_id = dh.bra_id AND hh.soh_id = dh.soh_id
         WHERE dh.item_id = :i AND dh.stor_id = :d AND hh.cust_id IS DISTINCT FROM :full
         GROUP BY dh.bra_id, dh.soh_id) x
       WHERE x.creado <= :t AND x.cerrado > :t
         AND NOT EXISTS (SELECT 1 FROM tb_item_transactions i2
                         WHERE i2.bra_id = x.bra_id AND i2.it_soh_id = x.soh_id AND i2.item_id = :i)
         AND NOT EXISTS (SELECT 1 FROM tb_sale_order_header h2
                         WHERE h2.bra_id = x.bra_id AND h2.soh_id = x.soh_id AND h2.soh_statusof IS NULL))
""")

_FOTO_SQL = text('SELECT principal, "full" FROM costo_si_stock_diario WHERE fecha = :f AND item_id = :i')


def principal_disponible(db: Session, item_id: int, t: datetime) -> int:
    """GBP depot 1 AVAILABLE stock at instant `t` (S3, L4.1): physical minus orders generated, not invoiced."""
    params = {"i": item_id, "d": DEPOSITO_PRINCIPAL, "t": t}
    fisico = db.execute(_FISICO_SQL, params).scalar()
    if fisico is None:
        fisico = db.execute(_FISICO_ULTIMO_SQL, params).scalar()
    pendiente = db.execute(_PENDIENTE_SQL, {**params, "full": CLIENTE_TRANSFERENCIA_FULL}).scalar()
    return int(fisico or 0) - int(pendiente or 0)


def disponible(db: Session, item_id: int, dia: date) -> int:
    """Principal + Full AVAILABLE stock at 00:00 of `dia` (S3): the day's photo when there is one."""
    foto = db.execute(_FOTO_SQL, {"f": dia, "i": item_id}).first()
    if foto is not None:
        return int(foto[0]) + int(foto[1])
    principal = principal_disponible(db, item_id, inicio_del_dia(dia))
    instante = datetime.combine(dia, time.min, tzinfo=ZONA)
    return principal + full_ml.full_disponible(db, item_id, instante)


def inicio_de(db: Session, item_id: int) -> Optional[date]:
    """The product's first sell-in date, None for a combo or a product no sell in reaches."""
    if es_combo(db, item_id):
        return None
    return primera_fecha_sell_in(db, item_id, bonos_de(db, item_id))


# --------------------------------------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Entrada:
    inicio: Inicio
    compras: List[Compra]


def entrada(db: Session, item_id: int) -> Optional[Entrada]:
    """The engine's input for `item_id`, None when no sell in applies to it or it is a combo (S11)."""
    if es_combo(db, item_id):
        return None
    bonos = bonos_de(db, item_id)
    inicio_fecha = primera_fecha_sell_in(db, item_id, bonos)
    if inicio_fecha is None:
        return None
    t0 = inicio_del_dia(inicio_fecha)
    facturas = facturas_de(db, item_id, inicio_fecha - VENTANA_PREVIAS)
    previas = [f for f in facturas if f.fecha < inicio_fecha]
    posteriores = [f for f in facturas if f.fecha >= inicio_fecha]
    # Invoiced before the start but entering stock after it: valued at the start cost, like the stock then.
    sin_entrar = sum(f.cantidad for f in previas if f.entrada is not None and f.entrada >= t0)
    inicio = Inicio(
        inicio_fecha, disponible(db, item_id, inicio_fecha) + sin_entrar, costo_lista(db, item_id, inicio_fecha)
    )
    manuales = {}
    if posteriores:
        manuales = {
            ct: Decimal(tc) for ct, tc in db.execute(_TC_MANUAL_SQL, {"cts": [f.ct_transaction for f in posteriores]})
        }
    compras = []
    for n, f in enumerate(posteriores):
        tc, fuente = tipo_cambio_de(db, f, manuales)
        if f.curr_id != CURR_USD and not tc:
            raise ValueError(f"invoice {f.ct_transaction}: no exchange rate for {f.fecha}")
        neto = f.precio if f.curr_id == CURR_USD else f.precio / tc
        compras.append(
            Compra(
                fecha=f.fecha,
                ct_transaction=f.ct_transaction,
                cantidad=f.cantidad,
                costo_neto_usd=neto,
                sell_ins=sell_ins_de(db, item_id, f, bonos),
                stock_antes=_stock_antes(db, item_id, f, previas + posteriores[:n], posteriores[n + 1 :]),
                tipo_cambio=tc,
                fuente_tc=fuente,
                en_compras=bool(f.pedidos),
            )
        )
    return Entrada(inicio, compras)


def _stock_antes(db: Session, item_id: int, f: Factura, antes: Sequence[Factura], despues: Sequence[Factura]) -> int:
    """Available stock at 00:00 of the invoice date, plus the earlier invoices already in the average whose goods
    had not entered yet, minus the later ones whose goods had already entered (T1 §2)."""
    t = inicio_del_dia(f.fecha)
    stock = disponible(db, item_id, f.fecha)
    stock += sum(g.cantidad for g in antes if g.entrada is not None and g.entrada >= t)
    stock -= sum(g.cantidad for g in despues if g.entrada is not None and g.entrada < t)
    return stock
