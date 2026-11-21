"""A throwaway Postgres world for the legacy ML metrics (`ml_ventas_metricas`, /ventas-ml) costed at costo SI
(sell-in-costo-si T3 PR 8): the GBP mirror of ML orders the crons read, the costo SI reader's tables, offsets and the
low-markup notification. Invented data only."""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator, Optional

from sqlalchemy import Engine, text

from app.models.combo_componente import ComboComponente
from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.commercial_transaction import CommercialTransaction
from app.models.costo_si import CostoSiBackup, CostoSiPaso
from app.models.cur_exch_history import CurExchHistory
from app.models.item_cost_list import ItemCostList
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.marca_pm import MarcaPM
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.notificacion import Notificacion
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.pricing_constants import PricingConstants
from app.models.producto import ProductoERP, ProductoPricing
from app.models.sale_order_header import SaleOrderHeader
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_item import TBItem
from app.models.tb_item_taxes import TBItemTaxes
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_tax_name import TBTaxName
from app.models.tipo_cambio import TipoCambio
from app.models.usuario import Usuario
from tests.services.sell._schema import throwaway_schema

STUBS = ["CREATE TABLE roles (id INTEGER PRIMARY KEY)"]

TABLES = [
    Usuario.__table__,
    ProductoERP.__table__,
    ProductoPricing.__table__,
    TBItem.__table__,
    ComboComponente.__table__,
    TipoCambio.__table__,
    CurExchHistory.__table__,
    ItemCostList.__table__,
    ItemCostListHistory.__table__,
    CostoSiPaso.__table__,
    CostoSiBackup.__table__,
    MercadoLibreOrderHeader.__table__,
    MercadoLibreOrderDetail.__table__,
    MercadoLibreOrderShipping.__table__,
    MercadoLibreItemPublicado.__table__,
    SaleOrderHeader.__table__,
    CommercialTransaction.__table__,
    TBCategory.__table__,
    TBSubCategory.__table__,
    TBBrand.__table__,
    TBItemTaxes.__table__,
    TBTaxName.__table__,
    SubcategoriaGrupo.__table__,
    ComisionVersion.__table__,
    ComisionBase.__table__,
    ComisionAdicionalCuota.__table__,
    MLVentaMetrica.__table__,
    OffsetGrupo.__table__,
    OffsetGanancia.__table__,
    OffsetGrupoConsumo.__table__,
    OffsetGrupoResumen.__table__,
    OffsetIndividualConsumo.__table__,
    OffsetIndividualResumen.__table__,
    Notificacion.__table__,
    PricingConstants.__table__,
    MarcaPM.__table__,
]

_ids = itertools.count(700_000)


@contextmanager
def world(prefix: str) -> Iterator[Engine]:
    with throwaway_schema(prefix, TABLES, STUBS) as engine:
        yield engine


def clean(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in reversed(TABLES):
            if table.name == "combo_componentes":
                conn.execute(text("DELETE FROM combo_componentes WHERE combo_item_id <> 999999001"))
            else:
                conn.execute(text(f"DELETE FROM {table.name}"))


def run(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def rows(engine: Engine, sql: str, **params) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params)]


def producto(
    engine: Engine, item_id: int, moneda: str = "USD", costo: Optional[str] = None, cat_id: int = 3, iva: float = 21
) -> None:
    """A product whose cost currency is `moneda` and current list cost `costo` (productos_erp + tb_item)."""
    run(
        engine,
        "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, moneda_costo, costo, iva) "
        "VALUES (:i, :c, 'Producto', 'MARCA DEMO', 'CAMARAS', :m, :costo, :iva)",
        i=item_id,
        c=f"C{item_id}",
        m=moneda,
        costo=float(costo) if costo is not None else None,
        iva=iva,
    )
    run(
        engine,
        "INSERT INTO tb_item (comp_id, item_id, item_code, item_desc, cat_id) VALUES (1, :i, :c, 'Producto', :cat)",
        i=item_id,
        c=f"C{item_id}",
        cat=cat_id,
    )


def combo(engine: Engine, combo_item_id: int, componentes: dict) -> None:
    for componente, cantidad in componentes.items():
        run(
            engine,
            "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :i, :q)",
            c=combo_item_id,
            i=componente,
            q=cantidad,
        )


def paso(engine: Engine, item_id: int, orden: int, fecha: date, promedio: str, moneda: str = "USD") -> None:
    """A costo SI step: the average `promedio` (in `moneda`) in force from `fecha`."""
    run(
        engine,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd, moneda) VALUES (:i, :o, 'compra', :f, 0, 0, 0, 0, :p, :m)",
        i=item_id,
        o=orden,
        f=fecha,
        p=Decimal(promedio),
        m=moneda,
    )


def costo_lista(
    engine: Engine, item_id: int, cuando: datetime, precio: str, curr_id: int = 2, coslis_id: int = 1
) -> None:
    """A list-cost history row (the pre-costo-SI cost the crons used) and the current list cost row."""
    run(
        engine,
        "INSERT INTO tb_item_cost_list_history (iclh_id, coslis_id, item_id, iclh_price, curr_id, iclh_cd) "
        "VALUES (:id, :l, :i, :p, :curr, :cd)",
        id=next(_ids),
        l=coslis_id,
        i=item_id,
        p=Decimal(precio),
        curr=curr_id,
        cd=cuando,
    )
    run(
        engine,
        "DELETE FROM tb_item_cost_list WHERE comp_id = 1 AND item_id = :i AND coslis_id = :l",
        i=item_id,
        l=coslis_id,
    )
    run(
        engine,
        "INSERT INTO tb_item_cost_list (comp_id, coslis_id, item_id, coslis_price, curr_id) VALUES (1, :l, :i, :p, :c)",
        l=coslis_id,
        i=item_id,
        p=Decimal(precio),
        c=curr_id,
    )


def tipo_cambio(engine: Engine, fecha: date, venta: float) -> None:
    run(engine, "INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (:f, 'USD', :v, :v)", f=fecha, v=venta)


def venta_ml(engine: Engine, item_id: int, cuando: datetime, cantidad: int = 1, precio: str = "100000") -> int:
    """An ML order of one line (GBP mirror, naive local time as GBP stores it). Returns its mlo_id."""
    mlo_id = next(_ids)
    run(
        engine,
        "INSERT INTO tb_mercadolibre_orders_header (comp_id, mlo_id, mlo_cd, mlo_status, ml_id, mlo_ismshops) "
        "VALUES (1, :o, :cd, 'paid', :ml, false)",
        o=mlo_id,
        cd=cuando,
        ml=str(mlo_id),
    )
    run(
        engine,
        "INSERT INTO tb_mercadolibre_orders_detail (comp_id, mlod_id, mlo_id, item_id, mlo_quantity, mlo_unit_price) "
        "VALUES (1, :d, :o, :i, :q, :p)",
        d=next(_ids),
        o=mlo_id,
        i=item_id,
        q=cantidad,
        p=Decimal(precio),
    )
    return mlo_id


def metrica(engine: Engine, mlo_id: int) -> dict:
    with engine.connect() as conn:
        fila = conn.execute(
            text(
                "SELECT costo_unitario_sin_iva, costo_total_sin_iva, ganancia, markup_porcentaje, monto_limpio, "
                "monto_total, comision_ml, costo_envio_ml FROM ml_ventas_metricas WHERE id_operacion = :o"
            ),
            {"o": mlo_id},
        ).one()
    return dict(fila._mapping)
