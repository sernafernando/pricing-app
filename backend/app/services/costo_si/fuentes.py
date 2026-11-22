"""What the costo SI engine reads, per product (S2-S7, S11; queries from handoffs/sell-in-costo-si-t1.md).

- Start (S2): the first sell-in date: the earliest brand bonus that reaches the product (`fecha_desde`) or the earliest
  purchase invoice a Compras sell in reaches. Its cost: the `tb_item_cost_list_history` row (list 1, USD) in force at
  00:00 of that day, i.e. the last row of an earlier day, so a same-day typo corrected minutes later never counts.
- Purchases (S4): every purchase invoice (`v_facturas_compra_vigentes`, 'FACTURA') of the product, dated by the
  supplier invoice date `ct_date`, at its net unit price. FX for ARS: a PM correction (`costo_si_factura_tc`), else
  the linked Compras operation's TC (manual first), else `tipo_cambio.venta` on the invoice date (or the latest
  before it).
- Sell ins (S5, S6): the active Compras sell ins (`sell_in_compras`) of the operations the invoice is linked to, as a
  % of the item's net base; plus every active sell-in line of the sale-cost kind (`sell_in_bonos_marca`, a tactical's
  included: "si algo se cargo por sell in, es sell in, no se discute", L4.2), % or per unit, on the purchases of its
  scope dated in its range, from any supplier and linked to Compras or not (S7). Without topes it is the loyalty
  (L5, L7.2: every invoice); with `tope_unidades` / `tope_monto` it covers only the first units / amount, used up over
  the scope's invoices in date order (`aplicar_topes`). A per-unit amount is taken as the % of the invoice's net it
  is. Sell-out lines (`sell_out_campanas`) are on the sale, never here (L12).
- Available stock at 00:00 of a day (S3): principal = GBP depot 1 physical minus the units of sale orders generated
  and not invoiced at that instant (pending transfers to Full, customer 2849, do not count: the units still exist).
  Full = Mercado Libre's Full available stock, NOT GBP depot 17 (L8): walked back from the next ML reading the app
  stores (the Auditoría's daily photo, else today's ML stock) with the stored Full sales and the GBP remitos into
  Full (`full_ml`, L11; no Mercado Libre call). A day with a costo SI photo (`costo_si_stock_diario`) reads it
  instead.
- Combos (S11, L7.1) have no stock, purchases or sell ins of their own: the engine never computes one (`es_combo`);
  their cost is their components' at read time. A PC (cat 47) too, with or without a bill of materials (L22:
  "las pcs son la suma de sus componentes el costo", `sin_historia`).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import BigInteger

from app.services.combos.pcs import pcs_entre
from app.services.pricing_calculator import moneda_de
from app.services.costo_si import full_ml
from app.services.costo_si import sospechas
from app.services.costo_si.engine import Compra, Inicio, Lista, SellIn

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
DEPOSITO_PRINCIPAL = 1
CLIENTE_TRANSFERENCIA_FULL = 2849
CURR_ARS = 1
CURR_USD = 2
MONEDAS = {CURR_ARS: "ARS", CURR_USD: "USD"}  # the purchase currencies costo SI knows how to convert
CURRS = {moneda: curr for curr, moneda in MONEDAS.items()}


class MonedaNoSoportada(ValueError):
    """An invoice in a currency costo SI cannot convert (or mixing currencies): the product is reported, not
    guessed."""


# Invoices dated before the start can still be entering stock after it (GBP loads them up to ~2 weeks late).
VENTANA_PREVIAS = timedelta(days=90)

# L21 (owner: "pero costo si tiene que ponderar las facturas por mas que no tengan s8" / "arranquemos desde el 01/11 y
# listo"): a product no sell in ever reached starts its average here, 00:00, with that instant's list cost and
# available stock (S2/S3), then every purchase invoice (S4) with no discount. A product with a sell in keeps its own.
INICIO_SIN_SELL_IN = date(2026, 11, 1)


def inicio_del_dia(dia: date) -> datetime:
    """00:00 of `dia`, naive, as GBP's mirror stores its timestamps (local time)."""
    return datetime.combine(dia, time.min)


def es_combo(db: Session, item_id: int) -> bool:
    """A combo, a PC included: its costo SI is its components' sum, read at read time (S11; L22 "las pcs son la suma
    de sus componentes el costo")."""
    combo = db.execute(text("SELECT 1 FROM combo_componentes WHERE combo_item_id = :i LIMIT 1"), {"i": item_id}).first()
    return combo is not None


def sin_historia(db: Session, item_id: int) -> bool:
    """No history of its own: a combo, or a PC even without a bill of materials (L22: a PC's cost is never its own
    average, never frozen at L21's start)."""
    return es_combo(db, item_id) or bool(pcs_entre(db, [item_id]))


# ---------------------------------------------------------------------------------------------------------- start

# Whether a tactical created it or not (the loyalty is bono 94, a line of tactical 38). A model's own value replaces
# the line's (`sell_in_bono_items`).
_BONOS_SQL = text("""
    SELECT b.id, b.tipo, COALESCE(bi.porcentaje, b.porcentaje) AS pct, COALESCE(bi.monto_unit, b.monto_unit) AS unit,
           b.fecha_desde, b.fecha_hasta, b.moneda, b.incluye_iva, b.tope_unidades, b.tope_monto, p.iva
    FROM sell_in_bonos_marca b
    JOIN productos_erp p ON p.item_id = :i
    LEFT JOIN sell_in_bono_items bi ON bi.bono_id = b.id AND bi.item_id = :i
    WHERE b.estado = 'activa' AND b.base = 'costo_venta' AND b.tipo IN ('porcentaje', 'por_unidad')
      AND ((b.alcance = 'marca' AND p.marca = b.marca AND (b.categoria IS NULL OR p.categoria = b.categoria))
        OR (b.alcance = 'categoria' AND p.categoria = b.categoria)
        OR (b.alcance = 'modelos' AND bi.id IS NOT NULL))
    ORDER BY b.id
""")

# The purchase lines a capped or per-unit line walks, oldest first: every invoice of its scope (`:solo` NULL) or of
# one product, dated in its range, with its own value per model, the product's VAT and the invoice's rate (S4 order:
# the PM's correction, the Compras operation's TC, the last rate on or before its date).
_LINEAS_SQL = text("""
    WITH alcance AS (
        SELECT p.item_id, COALESCE(bi.porcentaje, b.porcentaje) AS pct, COALESCE(bi.monto_unit, b.monto_unit) AS unit,
               p.iva
        FROM sell_in_bonos_marca b
        JOIN productos_erp p
          ON (b.alcance = 'marca' AND p.marca = b.marca AND (b.categoria IS NULL OR p.categoria = b.categoria))
          OR (b.alcance = 'categoria' AND p.categoria = b.categoria)
          OR b.alcance = 'modelos'
        LEFT JOIN sell_in_bono_items bi ON bi.bono_id = b.id AND bi.item_id = p.item_id
        WHERE b.id = :b AND (b.alcance <> 'modelos' OR bi.id IS NOT NULL)
          AND (CAST(:solo AS integer) IS NULL OR p.item_id = :solo)
    )
    SELECT ct.ct_transaction, it.item_id, sum(it.it_qty) AS cantidad,
           sum(it.it_qty * it.it_price) / NULLIF(sum(it.it_qty), 0) AS precio, min(it.curr_id) AS curr_id,
           a.pct, a.unit, a.iva,
           COALESCE(
             (SELECT m.tipo_cambio FROM costo_si_factura_tc m WHERE m.ct_transaction = ct.ct_transaction),
             (SELECT COALESCE(pc.tipo_cambio_manual, pc.tipo_cambio) FROM pedido_compra_facturas pf
              JOIN pedidos_compra pc ON pc.id = pf.pedido_id
              WHERE pf.ct_transaction_id = ct.ct_transaction AND COALESCE(pc.tipo_cambio_manual, pc.tipo_cambio) > 0
              ORDER BY pf.pedido_id LIMIT 1),
             (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.venta > 0
              AND tc.fecha <= ct.ct_date::date ORDER BY tc.fecha DESC LIMIT 1)) AS tc
    FROM alcance a
    JOIN tb_item_transactions it ON it.item_id = a.item_id
    JOIN tb_commercial_transactions ct ON ct.ct_transaction = it.ct_transaction
    JOIN v_facturas_compra_vigentes v ON v.ct_transaction = ct.ct_transaction AND v.clasificacion = 'FACTURA'
    WHERE ct.ct_date >= :desde AND ct.ct_date < :hasta
    GROUP BY ct.ct_transaction, ct.ct_date, it.item_id, a.pct, a.unit, a.iva
    ORDER BY ct.ct_date, min(it.it_transaction), it.item_id
""")

_PRIMERA_FACTURA_CON_SELL_IN_SQL = text("""
    SELECT min(ct.ct_date)::date
    FROM sell_in_compra_items ci
    JOIN sell_in_compras c ON c.id = ci.compra_id AND c.estado = 'activa'
    JOIN pedido_compra_facturas pf
      ON pf.pedido_id = c.bono_pedido_id
      OR pf.pedido_id IN (SELECT cp.pedido_compra_id FROM sell_in_compra_pedidos cp WHERE cp.compra_id = c.id)
    -- only the invoices that enter the average (S4): never a credit note or a voided invoice
    JOIN v_facturas_compra_vigentes v ON v.ct_transaction = pf.ct_transaction_id AND v.clasificacion = 'FACTURA'
    JOIN tb_commercial_transactions ct ON ct.ct_transaction = pf.ct_transaction_id
    JOIN tb_item_transactions it ON it.ct_transaction = ct.ct_transaction AND it.item_id = ci.item_id
    WHERE ci.item_id = :i
""")

_COSTO_LISTA_SQL = text("""
    SELECT iclh_price FROM tb_item_cost_list_history
    WHERE item_id = :i AND coslis_id = 1 AND COALESCE(curr_id, 1) = :curr AND iclh_cd < :t
    ORDER BY iclh_cd DESC, iclh_id DESC LIMIT 1
""")

# L23: every day a new list 1 cost comes in force (00:00 after the row, the S2 rule) since `t0`, up to `hoy`, with the
# cost in force at that day's 00:00, naive local time like GBP's timestamps (`inicio_del_dia`): the same row
# `_COSTO_LISTA_SQL` would pick for that day.
_CAMBIOS_LISTA_SQL = text("""
    SELECT d.dia, (
        SELECT h.iclh_price FROM tb_item_cost_list_history h
        WHERE h.item_id = :i AND h.coslis_id = 1 AND COALESCE(h.curr_id, 1) = :curr
          AND h.iclh_cd < CAST(d.dia AS timestamp)
        ORDER BY h.iclh_cd DESC, h.iclh_id DESC LIMIT 1
    )
    FROM (
        SELECT DISTINCT CAST(iclh_cd AS date) + 1 AS dia FROM tb_item_cost_list_history
        WHERE item_id = :i AND coslis_id = 1 AND COALESCE(curr_id, 1) = :curr AND iclh_cd >= :t0
    ) d
    WHERE d.dia <= :hoy
    ORDER BY d.dia
""")

_MONEDA_SQL = text("SELECT moneda_costo FROM productos_erp WHERE item_id = :i")


@dataclass(frozen=True)
class Bono:
    id: int
    porcentaje: Optional[Decimal]  # a % line; None on a per-unit one
    desde: date
    hasta: date
    monto_unit: Optional[Decimal] = None  # a per-unit line, in `moneda`
    moneda: str = "ARS"
    incluye_iva: bool = False
    tope_unidades: Optional[int] = None
    tope_monto: Optional[Decimal] = None  # in `moneda`

    @property
    def plano(self) -> bool:
        """The loyalty's shape: a % with no topes, the same % on every invoice."""
        return self.porcentaje is not None and self.tope_unidades is None and self.tope_monto is None


def sin_iva(valor: Decimal, iva: Optional[Decimal], bono_id: int, item_id: int) -> Decimal:
    """A line's value net of the product's VAT when the line says it includes it, % or per unit alike: the sale-cost
    path's rule (S33, `bonos_costo.valor_neto`). A product with no VAT rate fails: never guessed."""
    if iva is None:
        raise ValueError(f"bono {bono_id}: product {item_id} has no VAT rate")
    return valor / (1 + iva / 100)


def _dec(value) -> Optional[Decimal]:
    return Decimal(str(value)) if value is not None else None


def bonos_de(db: Session, item_id: int) -> List[Bono]:
    out = []
    for bid, tipo, pct, unit, desde, hasta, moneda, iva, tope_u, tope_m, alicuota in db.execute(
        _BONOS_SQL, {"i": item_id}
    ):
        if tipo == "porcentaje" and pct:
            pct = Decimal(pct)
            if iva and tope_u is None and tope_m is None:  # a plain line's % is used as it is: net of VAT here
                pct = sin_iva(pct, _dec(alicuota), bid, item_id).quantize(Decimal("0.0001"))
            out.append(Bono(bid, pct, desde, hasta, None, moneda, bool(iva), tope_u, _dec(tope_m)))
        elif tipo == "por_unidad" and unit:
            out.append(Bono(bid, None, desde, hasta, Decimal(unit), moneda, bool(iva), tope_u, _dec(tope_m)))
    return out


@dataclass(frozen=True)
class Linea:
    """One product's units on one purchase invoice, as a capped or per-unit line walks them."""

    ct_transaction: int
    item_id: int
    cantidad: int
    precio: Decimal  # unit net, in the invoice's currency
    curr_id: Optional[int]
    porcentaje: Optional[Decimal]
    monto_unit: Optional[Decimal]
    iva: Optional[Decimal]
    tc: Optional[Decimal]  # ARS per USD


def _en_moneda(valor: Decimal, curr_id: Optional[int], moneda: str, tc: Optional[Decimal], ct: int) -> Decimal:
    """An invoice amount in the line's currency."""
    if MONEDAS.get(curr_id) == moneda:
        return valor
    if not tc:
        raise ValueError(f"invoice {ct}: no exchange rate to bring it to {moneda}")
    return valor / tc if moneda == "USD" else valor * tc


def aplicar_topes(bono: Bono, lineas: Sequence[Linea]) -> Dict[Tuple[int, int], Decimal]:
    """Pure: the % of each (invoice, product)'s net the line takes off, walking the lines oldest first and using up its
    topes (units, then amount, in its currency) as it goes; a cap can run out in the middle of an invoice."""
    quedan_u = bono.tope_unidades
    quedan_m = bono.tope_monto
    out: Dict[Tuple[int, int], Decimal] = {}
    for ln in lineas:
        if ln.cantidad <= 0:
            continue
        # A % with no money cap needs no rate: it is the same % in any currency.
        if ln.porcentaje is not None and quedan_m is None:
            precio = ln.precio
        else:
            precio = _en_moneda(ln.precio, ln.curr_id, bono.moneda, ln.tc, ln.ct_transaction)
        if ln.porcentaje is not None:
            por_unidad = precio * ln.porcentaje / 100
        else:
            por_unidad = ln.monto_unit or Decimal(0)
        if bono.incluye_iva:
            por_unidad = sin_iva(por_unidad, ln.iva, bono.id, ln.item_id)
        unidades = ln.cantidad if quedan_u is None else max(min(ln.cantidad, quedan_u), 0)
        neto = precio * ln.cantidad
        # Never more than the purchase itself, so a money cap counts only what was really taken off.
        monto = min(por_unidad * unidades, neto)
        if quedan_m is not None:
            monto = max(min(monto, quedan_m), Decimal(0))
            quedan_m -= monto
        if quedan_u is not None:
            quedan_u -= unidades
        if monto > 0 and neto > 0:
            out[(ln.ct_transaction, ln.item_id)] = (monto / neto * 100).quantize(Decimal("0.0001"))
    return out


def lineas_de(db: Session, bono: Bono, item_id: Optional[int]) -> List[Linea]:
    """The purchase lines `bono` walks: its whole scope when it has topes (they are shared), else `item_id`'s."""
    filas = db.execute(
        _LINEAS_SQL,
        {
            "b": bono.id,
            "solo": item_id,
            "desde": inicio_del_dia(bono.desde),
            "hasta": inicio_del_dia(bono.hasta + timedelta(days=1)),
        },
    )
    return [
        Linea(ct, item, int(q or 0), Decimal(str(precio or 0)), curr, _dec(pct), _dec(unit), _dec(iva), _dec(tc))
        for ct, item, q, precio, curr, pct, unit, iva, tc in filas
    ]


def porcentajes_de_bonos(db: Session, item_id: int, bonos: Sequence[Bono]) -> Dict[int, Dict[int, Decimal]]:
    """{bono id: {ct_transaction: %}} for the lines that are not a plain % (capped or per unit)."""
    out: Dict[int, Dict[int, Decimal]] = {}
    for b in bonos:
        if b.plano:
            continue
        compartido = b.tope_unidades is not None or b.tope_monto is not None
        pct = aplicar_topes(b, lineas_de(db, b, None if compartido else item_id))
        out[b.id] = {ct: v for (ct, item), v in pct.items() if item == item_id}
    return out


def primera_fecha_sell_in(db: Session, item_id: int, bonos: Sequence[Bono]) -> Optional[date]:
    """S2: the date the first sell in applies, None when none does."""
    fechas = [b.desde for b in bonos]
    factura = db.execute(_PRIMERA_FACTURA_CON_SELL_IN_SQL, {"i": item_id}).scalar()
    if factura is not None:
        fechas.append(factura)
    return min(fechas) if fechas else None


def moneda_de_producto(db: Session, item_id: int) -> str:
    """The product's cost currency, where its costo SI lives (L18): `moneda_costo` as the screens read it (blank or
    missing is ARS, `pricing_calculator.moneda_de`)."""
    moneda = moneda_de(db.execute(_MONEDA_SQL, {"i": item_id}).scalar())
    if moneda not in CURRS:
        raise MonedaNoSoportada(f"product {item_id}: cost currency {moneda}; costo SI knows {sorted(CURRS)}")
    return moneda


def costo_lista(db: Session, item_id: int, dia: date, moneda: str = "USD") -> Optional[Decimal]:
    """The list 1 cost in force at 00:00 of `dia`, from the history rows in `moneda` only (S2 in the product's
    currency: a row in the other currency is never converted). A row <= 0 is no cost (None), like the reader."""
    value = db.execute(_COSTO_LISTA_SQL, {"i": item_id, "t": inicio_del_dia(dia), "curr": CURRS[moneda]}).scalar()
    return Decimal(value) if value is not None and value > 0 else None


def cambios_de_lista(db: Session, item_id: int, inicio: Inicio, moneda: str, hoy: Optional[date] = None) -> List[Lista]:
    """L23, for a product no sell in reaches: every list-cost change after its start re-anchors the costo SI, from
    00:00 of the day it is in force (S2), in the product's currency only. A row repeating the cost in force, or one
    <= 0 (no cost), moves nothing. A change in force tomorrow waits for tomorrow's daily recompute."""
    hoy = hoy or datetime.now(ZONA).date()
    previo = inicio.costo_usd
    listas = []
    params = {"i": item_id, "curr": CURRS[moneda], "t0": inicio_del_dia(inicio.fecha), "hoy": hoy}
    for dia, valor in db.execute(_CAMBIOS_LISTA_SQL, params):
        costo = Decimal(valor) if valor is not None and valor > 0 else None
        if costo is None or costo == previo:
            continue
        # The stock at that instant is a point-in-time reconstruction, like an invoice's: one read per change.
        listas.append(Lista(dia, costo, disponible(db, item_id, dia)))
        previo = costo
    return listas


# ------------------------------------------------------------------------------------------------------ purchases

_FACTURAS_SQL = text("""
    SELECT ct.ct_transaction, ct.ct_date::date AS fecha, min(it.it_transaction) AS orden, min(it.it_cd) AS entrada,
           sum(it.it_qty) AS cantidad, sum(it.it_qty * it.it_price) / NULLIF(sum(it.it_qty), 0) AS precio,
           min(it.curr_id) AS curr_id, count(DISTINCT it.curr_id) AS monedas
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

# Every USD rate from the last one on or before :desde through :hasta; each invoice takes the last one on or before
# its date.
_TC_FECHAS_SQL = text("""
    SELECT fecha, venta FROM tipo_cambio
    WHERE moneda = 'USD' AND venta > 0 AND fecha <= :hasta
      AND fecha >= COALESCE(
        (SELECT max(fecha) FROM tipo_cambio WHERE moneda = 'USD' AND venta > 0 AND fecha <= :desde), :desde)
    ORDER BY fecha
""")

# The product's active Compras sell ins with the Compras operations each one covers (its own and its linked ones).
_SELL_IN_COMPRAS_SQL = text("""
    SELECT c.id, c.tipo, c.porcentaje, ci.cantidad, ci.costo_base_unit, ci.monto_asignado,
           array_remove(array_append(array_agg(cp.pedido_compra_id), c.bono_pedido_id), NULL) AS pedidos
    FROM sell_in_compras c
    JOIN sell_in_compra_items ci ON ci.compra_id = c.id AND ci.item_id = :i
    LEFT JOIN sell_in_compra_pedidos cp ON cp.compra_id = c.id
    WHERE c.estado = 'activa'
    GROUP BY c.id, ci.id
    ORDER BY c.id
""")


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
    facturas = []
    for r in db.execute(_FACTURAS_SQL, {"i": item_id, "desde": inicio_del_dia(desde)}):
        if r[7] > 1 or r[6] not in MONEDAS:
            raise MonedaNoSoportada(
                f"product {item_id}: invoice {r[0]} of {r[1]} is in currency {r[6]}"
                + (" mixed with others" if r[7] > 1 else "")
                + f"; costo SI converts only {sorted(MONEDAS.values())}"
            )
        facturas.append(Factura(r[0], r[1], r[2], r[3], int(r[4] or 0), Decimal(r[5] or 0), r[6]))
    por_ct = {f.ct_transaction: f for f in facturas}
    if por_ct:
        for ct, pedido, tc in db.execute(_PEDIDOS_SQL, {"cts": list(por_ct)}):
            f = por_ct[ct]
            f.pedidos.append(pedido)
            if f.tc_pedido is None and tc:
                f.tc_pedido = Decimal(tc)
    return facturas


@dataclass(frozen=True)
class SellInCompras:
    id: int
    porcentaje: Decimal
    pedidos: frozenset


def tipos_de_cambio(db: Session, facturas: Sequence[Factura], moneda: str = "USD") -> List[Tuple[date, Decimal]]:
    """The USD rates the dates of the invoices not in `moneda` need, oldest first (one query for the whole entry)."""
    fechas = [f.fecha for f in facturas if MONEDAS[f.curr_id] != moneda]
    if not fechas:
        return []
    filas = db.execute(_TC_FECHAS_SQL, {"desde": min(fechas), "hasta": max(fechas)})
    return [(fecha, Decimal(str(venta))) for fecha, venta in filas]


def tipo_cambio_de(
    f: Factura, manuales: Dict[int, Decimal], tasas: Sequence[Tuple[date, Decimal]], moneda: str = "USD"
) -> Tuple[Optional[Decimal], str]:
    """S4 (L4.5): an invoice in the product's currency (`moneda`, L18) needs none ('usd' / 'ars'); else the PM's
    correction, else the Compras operation's TC, else the last rate on or before its date."""
    if MONEDAS[f.curr_id] == moneda:
        return None, moneda.lower()
    if f.ct_transaction in manuales:
        return manuales[f.ct_transaction], "manual"
    if f.tc_pedido is not None:
        return f.tc_pedido, "pedido"
    k = bisect_right([fecha for fecha, _ in tasas], f.fecha)
    return (tasas[k - 1][1] if k else None), "fecha_factura"


def sell_ins_compras(db: Session, item_id: int) -> List[SellInCompras]:
    """The product's active Compras sell ins as % of the net, with the operations they cover (one query)."""
    out: List[SellInCompras] = []
    for cid, tipo, pct, cantidad, base, monto, pedidos in db.execute(_SELL_IN_COMPRAS_SQL, {"i": item_id}):
        if tipo == "porcentaje" and pct is not None:
            porcentaje = Decimal(pct)
        elif cantidad and base:
            porcentaje = Decimal(monto) / (Decimal(cantidad) * Decimal(base)) * 100
        else:
            continue
        out.append(SellInCompras(int(cid), porcentaje.quantize(Decimal("0.0001")), frozenset(pedidos or ())))
    return out


def sell_ins_de(
    f: Factura,
    compras: Sequence[SellInCompras],
    bonos: Sequence[Bono],
    por_bono: Optional[Dict[int, Dict[int, Decimal]]] = None,
) -> Tuple[SellIn, ...]:
    """S5/S6: the Compras sell ins of the invoice's operations, then the sell-in lines of its date: a plain % as it
    is, a capped or per-unit one as the % `porcentajes_de_bonos` worked out for this invoice."""
    pedidos = set(f.pedidos)
    out = [SellIn("compra", c.id, c.porcentaje) for c in compras if pedidos & c.pedidos]
    for b in bonos:
        if not b.desde <= f.fecha <= b.hasta:
            continue
        pct = b.porcentaje if b.plano else (por_bono or {}).get(b.id, {}).get(f.ct_transaction)
        if pct:
            out.append(SellIn("bono", b.id, pct))
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
    """The product's start: its first sell-in date, `INICIO_SIN_SELL_IN` when no sell in reaches it (L21), None for
    a combo or a PC (S11, L22)."""
    if sin_historia(db, item_id):
        return None
    return primera_fecha_sell_in(db, item_id, bonos_de(db, item_id)) or INICIO_SIN_SELL_IN


# --------------------------------------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Entrada:
    inicio: Inicio
    compras: List[Compra]
    moneda: str = "USD"  # the product's cost currency every amount is in (L18)
    listas: List[Lista] = field(default_factory=list)  # list-cost re-anchors, no-sell-in products only (L23)
    aceptadas: FrozenSet[int] = frozenset()  # suspicious purchases a reviewer let in (L29), by invoice


def entrada(db: Session, item_id: int) -> Optional[Entrada]:
    """The engine's input for `item_id`, None for a combo or a PC (S11, L22). The start is the first sell in's date (S2), or
    `INICIO_SIN_SELL_IN` for a product no sell in reaches (L21): no bonus then, so no invoice carries a discount, and
    every later list-cost change re-anchors it (L23)."""
    if sin_historia(db, item_id):
        return None
    bonos = bonos_de(db, item_id)
    primera = primera_fecha_sell_in(db, item_id, bonos)
    inicio_fecha = primera or INICIO_SIN_SELL_IN
    t0 = inicio_del_dia(inicio_fecha)
    facturas = facturas_de(db, item_id, inicio_fecha - VENTANA_PREVIAS)
    previas = [f for f in facturas if f.fecha < inicio_fecha]
    posteriores = [f for f in facturas if f.fecha >= inicio_fecha]
    # Invoiced before the start but entering stock after it: valued at the start cost, like the stock then.
    sin_entrar = sum(f.cantidad for f in previas if f.entrada is not None and f.entrada >= t0)
    moneda = moneda_de_producto(db, item_id)
    inicio = Inicio(
        inicio_fecha,
        disponible(db, item_id, inicio_fecha) + sin_entrar,
        costo_lista(db, item_id, inicio_fecha, moneda),
    )
    manuales = {}
    if posteriores:
        manuales = {
            ct: Decimal(tc) for ct, tc in db.execute(_TC_MANUAL_SQL, {"cts": [f.ct_transaction for f in posteriores]})
        }
    tasas = tipos_de_cambio(db, posteriores, moneda)
    del_compras = sell_ins_compras(db, item_id) if any(f.pedidos for f in posteriores) else []
    por_bono = porcentajes_de_bonos(db, item_id, bonos) if posteriores else {}
    compras = []
    # The stock before each invoice is a point-in-time reconstruction (its own instant): one read per invoice.
    for n, f in enumerate(posteriores):
        tc, fuente = tipo_cambio_de(f, manuales, tasas, moneda)
        if MONEDAS[f.curr_id] != moneda and not tc:
            raise ValueError(f"invoice {f.ct_transaction}: no exchange rate for {f.fecha}")
        # Into the product's currency (L18), at the invoice's own rate: never re-converted later.
        if MONEDAS[f.curr_id] == moneda:
            neto = f.precio
        elif moneda == "USD":
            neto = f.precio / tc
        else:
            neto = f.precio * tc
        compras.append(
            Compra(
                fecha=f.fecha,
                ct_transaction=f.ct_transaction,
                cantidad=f.cantidad,
                costo_neto_usd=neto,
                sell_ins=sell_ins_de(f, del_compras, bonos, por_bono),
                stock_antes=_stock_antes(db, item_id, f, previas + posteriores[:n], posteriores[n + 1 :]),
                tipo_cambio=tc,
                fuente_tc=fuente,
                en_compras=bool(f.pedidos),
                # L29: the reference when there is no average yet, only needed while the start has no cost.
                referencia_lista=costo_lista(db, item_id, f.fecha, moneda) if inicio.costo_usd is None else None,
            )
        )
    listas = cambios_de_lista(db, item_id, inicio, moneda) if primera is None else []
    return Entrada(inicio, compras, moneda, listas, sospechas.aceptadas(db, item_id, compras))


def _stock_antes(db: Session, item_id: int, f: Factura, antes: Sequence[Factura], despues: Sequence[Factura]) -> int:
    """Available stock at 00:00 of the invoice date, plus the earlier invoices already in the average whose goods
    had not entered yet, minus the later ones whose goods had already entered (T1 §2)."""
    t = inicio_del_dia(f.fecha)
    stock = disponible(db, item_id, f.fecha)
    stock += sum(g.cantidad for g in antes if g.entrada is not None and g.entrada >= t)
    stock -= sum(g.cantidad for g in despues if g.entrada is not None and g.entrada < t)
    if f.entrada is not None and f.entrada < t:  # its own goods entered before its date: already in the stock
        stock -= f.cantidad
    return stock
