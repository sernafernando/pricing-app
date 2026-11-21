"""sell-in-costo-si T3 PR 9: the GBP sales of Ventas por fuera (anterior) and Tienda Nube cost their product's costo SI,
Costo D (x 1.065) on top: the metric crons (`agregar_metricas_fuera_ml`, `agregar_metricas_tienda_nube`) and the live
listings (`GET /ventas-fuera-ml`, `GET /ventas-tienda-nube`).

Owner L6.2 "costo d va a aplicar sobre costo si"; L18: the cost is in the product's currency; S11: a combo = its
components x quantity; L19: "claro si el combo trae el desglose no tomarlo, si no lo trae sí". The GBP shapes are the
ones read on prod (read-only, 2026-11-20): a combo sold as an association group is a principal line (`it_order` 1,
no item, price 0) plus its component lines; a standalone line has `it_isassociationgroup` false. Invented data.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from decimal import Decimal
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.endpoints import ventas_fuera_ml as ep_fuera
from app.api.endpoints import ventas_tienda_nube as ep_tn
from app.models.combo_componente import ComboComponente
from app.models.commercial_transaction import CommercialTransaction
from app.models.costo_si import CostoSiPaso
from app.models.cur_exch_history import CurExchHistory
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.item_transaction import ItemTransaction
from app.models.item_transaction_detail import ItemTransactionDetail
from app.models.pricing_constants import PricingConstants
from app.models.producto import ProductoERP
from app.models.tb_branch import TBBranch
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_customer import TBCustomer
from app.models.tb_document_file import TBDocumentFile
from app.models.tb_fiscal_class import TBFiscalClass
from app.models.tb_item import TBItem
from app.models.tb_item_taxes import TBItemTaxes
from app.models.tb_salesman import TBSalesman
from app.models.tb_state import TBState
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_tax_name import TBTaxName
from app.models.tb_tax_number_type import TBTaxNumberType
from app.models.tipo_cambio import TipoCambio
from app.models.vendedor_excluido import VendedorExcluido
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.scripts import agregar_metricas_fuera_ml as cron_fuera
from app.scripts import agregar_metricas_tienda_nube as cron_tn
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

TABLAS = [
    t.__table__
    for t in (
        ItemTransaction,
        CommercialTransaction,
        TBItem,
        ProductoERP,
        TBBrand,
        TBCategory,
        TBSubCategory,
        TBBranch,
        TBSalesman,
        TBCustomer,
        TBDocumentFile,
        TBItemTaxes,
        ItemTransactionDetail,
        TBTaxName,
        TBFiscalClass,
        TBState,
        TBTaxNumberType,
        CurExchHistory,
        TipoCambio,
        ItemCostListHistory,
        CostoSiPaso,
        ComboComponente,
        VendedorExcluido,
        PricingConstants,
        VentaFueraMLMetrica,
        VentaTiendaNubeMetrica,
    )
]
STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)"]

DIA = datetime(2026, 10, 5)
DESDE, HASTA = "2026-10-01", "2026-10-31"
DF_FUERA, DF_TN = 1, 113
# NB (USD) costo SI 10 USD, list 12; MOUSE (ARS product, L18) costo SI 5,000 ARS; SIN_SI (USD) list 3 only;
# COMBO = NB + 2 MOUSE (= 20,000 ARS); PC (cat 47) = NB + MOUSE, its own list cost 50 USD. USD at 1,000.
NB, MOUSE, SIN_SI, COMBO, PC = 801, 802, 803, 810, 811
NB_ARS, MOUSE_ARS, COMBO_ARS = Decimal("10000"), Decimal("5000"), Decimal("20000")
D = Decimal("1.065")

_ids = itertools.count(9_000_001)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("vf_tn_costo_si", TABLAS, STUBS) as engine:
        yield engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    _mundo(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield session
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE tb_item_transactions, tb_commercial_transactions, tb_item, productos_erp, tipo_cambio,"
                " tb_item_cost_list_history, costo_si_pasos, combo_componentes, ventas_fuera_ml_metricas,"
                " ventas_tienda_nube_metricas"
            )
        )


def _run(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def _producto(engine: Engine, item_id: int, moneda: str, lista: Optional[str] = None, cat_id: int = 3) -> None:
    _run(
        engine,
        "INSERT INTO productos_erp (item_id, codigo, descripcion, moneda_costo, costo) VALUES (:i, :c, 'Producto', :m, :l)",
        i=item_id,
        c=f"C{item_id}",
        m=moneda,
        l=lista,
    )
    _run(
        engine,
        "INSERT INTO tb_item (comp_id, item_id, item_code, item_desc, cat_id) VALUES (1, :i, :c, 'Producto Ejemplo', :k)",
        i=item_id,
        c=f"C{item_id}",
        k=cat_id,
    )
    if lista is not None:
        _run(
            engine,
            "INSERT INTO tb_item_cost_list_history (iclh_id, comp_id, coslis_id, item_id, iclh_price, curr_id, iclh_cd)"
            " VALUES (:id, 1, 1, :i, :p, :cu, '2026-09-01')",
            id=next(_ids),
            i=item_id,
            p=Decimal(lista),
            cu=2 if moneda == "USD" else 1,
        )


def _paso(engine: Engine, item_id: int, promedio: str, moneda: str) -> None:
    _run(
        engine,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd, moneda) VALUES (:i, 0, 'inicio', '2026-10-01', 0, 0, 0, 0, :p, :m)",
        i=item_id,
        p=Decimal(promedio),
        m=moneda,
    )


def _mundo(engine: Engine) -> None:
    _producto(engine, NB, "USD", "12")
    _producto(engine, MOUSE, "ARS", "6000")
    _producto(engine, SIN_SI, "USD", "3")
    _producto(engine, COMBO, "USD")
    _producto(engine, PC, "USD", "50", cat_id=47)
    _paso(engine, NB, "10", "USD")
    _paso(engine, MOUSE, "5000", "ARS")
    _run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES"
        f" ({COMBO}, {NB}, 1), ({COMBO}, {MOUSE}, 2), ({PC}, {NB}, 1), ({PC}, {MOUSE}, 1)",
    )
    _run(engine, "INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES ('2026-10-01', 'USD', 1000, 1000)")


def _venta(engine: Engine, df_id: int, lineas: list[dict]) -> list[int]:
    """One GBP invoice of `DIA` with `lineas` (`item`, `qty`, `precio`, `grupo`, `asoc`, `orden`); their it_transaction."""
    ct = next(_ids)
    _run(
        engine,
        "INSERT INTO tb_commercial_transactions (comp_id, bra_id, ct_transaction, ct_date, cust_id, sm_id, df_id, sd_id,"
        " ct_docnumber) VALUES (1, 1, :ct, :d, 500, 50, :df, 1, 'A-0001')",
        ct=ct,
        d=DIA,
        df=df_id,
    )
    ids = []
    for ln in lineas:
        it = next(_ids)
        _run(
            engine,
            "INSERT INTO tb_item_transactions (comp_id, bra_id, it_transaction, ct_transaction, item_id, it_qty,"
            " it_price, it_isassociationgroup, it_isassociation, it_order) VALUES (1, 1, :it, :ct, :i, :q, :p, :g, :a, :o)",
            it=it,
            ct=ct,
            i=ln.get("item"),
            q=Decimal(ln.get("qty", "1")),
            p=Decimal(ln.get("precio", "100000")),
            g=ln.get("grupo", False),
            a=ln.get("asoc", False),
            o=ln.get("orden", 1),
        )
        ids.append(it)
    return ids


def _grupo(combo: Optional[int], partes: list[tuple[int, str]]) -> list[dict]:
    """A combo as GBP sends it: the principal line (price 0) plus one priced line per component."""
    principal = {"item": combo, "precio": "0", "grupo": True, "asoc": True, "orden": 1}
    return [principal] + [
        {"item": i, "qty": q, "precio": "50000", "grupo": True, "asoc": True, "orden": n}
        for n, (i, q) in enumerate(partes, start=2)
    ]


def _cron(db: Session, modulo) -> dict[int, tuple[Decimal, Decimal]]:
    obtener = cron_fuera.obtener_ventas_fuera_ml if modulo is cron_fuera else cron_tn.obtener_ventas_tienda_nube
    filas = obtener(db, f"{DESDE} 00:00:00", f"{HASTA} 23:59:59")
    return {f.it_transaction: (Decimal(f.costo_unitario or 0), Decimal(f.costo_total or 0)) for f in filas}


def _listado(db: Session, endpoint) -> dict[int, Decimal]:
    if endpoint is ep_fuera:
        filas = ep_fuera.get_ventas_fuera_ml(
            from_date=DESDE,
            to_date=HASTA,
            sucursal=None,
            vendedor=None,
            marca=None,
            cliente=None,
            limit=1000,
            offset=0,
            db=db,
            current_user={},
        )
    else:
        filas = ep_tn.get_ventas_tienda_nube(
            from_date=DESDE,
            to_date=HASTA,
            sucursal=None,
            vendedor=None,
            marca=None,
            cliente=None,
            limit=1000,
            offset=0,
            db=db,
            current_user={},
        )
    filas = [f if isinstance(f, dict) else f.model_dump() for f in filas]
    return {int(f["id_operacion"]): Decimal(str(f["costo_pesos_sin_iva"])) for f in filas}


CANALES = [pytest.param(cron_fuera, DF_FUERA, id="fuera"), pytest.param(cron_tn, DF_TN, id="tienda_nube")]
LISTADOS = [pytest.param(ep_fuera, DF_FUERA, id="fuera"), pytest.param(ep_tn, DF_TN, id="tienda_nube")]


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_line_costs_costo_si_in_pesos_with_costo_d_on_top(engine: Engine, db: Session, cron, df_id) -> None:
    nb, mouse, sin_si = _venta(engine, df_id, [{"item": NB, "qty": "2"}, {"item": MOUSE, "qty": "3"}, {"item": SIN_SI}])

    costos = _cron(db, cron)

    assert costos[nb] == (NB_ARS * D, NB_ARS * D * 2)  # 10 USD x 1,000 (list 12 would be 12,780)
    assert costos[mouse] == (MOUSE_ARS * D, MOUSE_ARS * D * 3)  # ARS product: no rate (L18)
    assert costos[sin_si] == (Decimal("3000") * D, Decimal("3000") * D)  # no costo SI: list cost (Q1)


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_combo_line_without_its_breakdown_costs_its_components(engine: Engine, db: Session, cron, df_id) -> None:
    """L19 "si no lo trae sí": a combo product sold as one line."""
    (combo,) = _venta(engine, df_id, [{"item": COMBO}])

    assert _cron(db, cron)[combo] == (COMBO_ARS * D, COMBO_ARS * D)


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_combo_line_with_its_breakdown_costs_0(engine: Engine, db: Session, cron, df_id) -> None:
    """L19 "si el combo trae el desglose no tomarlo": the components are lines of the same sale."""
    combo, nb, mouse = _venta(engine, df_id, [{"item": COMBO}, {"item": NB}, {"item": MOUSE, "qty": "2"}])

    costos = _cron(db, cron)

    assert costos[combo] == (Decimal(0), Decimal(0))
    assert (costos[nb][1], costos[mouse][1]) == (NB_ARS * D, MOUSE_ARS * D * 2)


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_combo_line_with_only_one_loose_component_is_not_broken_down(
    engine: Engine, db: Session, cron, df_id, caplog: pytest.LogCaptureFixture
) -> None:
    """L19: one extra mouse sold next to the combo is not its breakdown: the combo keeps its components' cost."""
    combo, mouse = _venta(engine, df_id, [{"item": COMBO}, {"item": MOUSE}])

    costos = _cron(db, cron)

    assert (costos[combo][1], costos[mouse][1]) == (COMBO_ARS * D, MOUSE_ARS * D)
    # the possible double count of the mouse is logged with the group (GBP transaction), never silent
    (ct,) = db.execute(
        text("SELECT ct_transaction FROM tb_item_transactions WHERE it_transaction = :i"), {"i": combo}
    ).one()
    avisos = [r.getMessage() for r in caplog.records if "partially broken down" in r.getMessage()]
    assert avisos == [
        f"{cron.__name__.split('.')[-1].replace('agregar_metricas_', 'ventas_')}: combo {COMBO} partially broken down"
        f" in group {ct} (missing components [{NB}]): costed whole and its loose components too"
    ]


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_a_full_breakdown_or_a_combo_alone_logs_nothing(
    engine: Engine, db: Session, cron, df_id, caplog: pytest.LogCaptureFixture
) -> None:
    _venta(engine, df_id, [{"item": COMBO}, {"item": NB}, {"item": MOUSE, "qty": "2"}])
    _venta(engine, df_id, [{"item": COMBO}])

    _cron(db, cron)

    assert [r for r in caplog.records if "partially broken down" in r.getMessage()] == []


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_group_whose_principal_is_the_combo_sums_only_the_breakdown(
    engine: Engine, db: Session, cron, df_id
) -> None:
    """L19 inside an association group: the principal line names the combo and its components follow."""
    principal, *_ = _venta(engine, df_id, _grupo(COMBO, [(NB, "1"), (MOUSE, "2")]))

    assert _cron(db, cron)[principal][1] == (NB_ARS + 2 * MOUSE_ARS) * D  # the combo itself is not added again


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_group_as_gbp_sends_it_today_costs_its_components(engine: Engine, db: Session, cron, df_id) -> None:
    """The prod shape (principal without item, cost 0): the group = its components' costo SI."""
    principal, *_ = _venta(engine, df_id, _grupo(None, [(NB, "1"), (MOUSE, "2")]))

    assert _cron(db, cron)[principal][1] == (NB_ARS + 2 * MOUSE_ARS) * D


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_group_total_without_costo_si_stays_what_it_was(engine: Engine, db: Session, cron, df_id) -> None:
    """Regression: components with list cost only and a principal that cost 0 -> today's total (list x rate)."""
    _run(engine, "DELETE FROM costo_si_pasos")
    principal, *_ = _venta(engine, df_id, _grupo(None, [(NB, "1"), (SIN_SI, "2")]))

    assert _cron(db, cron)[principal][1] == (Decimal("12000") + 2 * Decimal("3000")) * D


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_a_pc_keeps_its_own_cost_as_today(engine: Engine, db: Session, cron, df_id) -> None:
    """A PC (cat 47) is its own product: never its components, never skipped (as before)."""
    (pc,) = _venta(engine, df_id, [{"item": PC}])

    assert _cron(db, cron)[pc][1] == Decimal("50000") * D


@pytest.mark.parametrize("cron,df_id", CANALES)
def test_cron_a_pc_sold_with_its_parts_still_keeps_its_own_cost(engine: Engine, db: Session, cron, df_id) -> None:
    """L19 is for combos: a PC's own line is never dropped, even when its parts are lines of the same sale."""
    pc, *_ = _venta(engine, df_id, [{"item": PC}, {"item": NB}, {"item": MOUSE}])

    assert _cron(db, cron)[pc][1] == Decimal("50000") * D


def test_cron_stores_the_costo_si_cost_and_currency(engine: Engine, db: Session) -> None:
    (mouse,) = _venta(engine, DF_FUERA, [{"item": MOUSE, "qty": "2", "precio": "20000"}])

    cron_fuera.process_and_insert(db, cron_fuera.obtener_ventas_fuera_ml(db, f"{DESDE} 00:00:00", f"{HASTA} 23:59:59"))

    fila = db.execute(
        text("SELECT costo_total, moneda_costo FROM ventas_fuera_ml_metricas WHERE it_transaction = :i"), {"i": mouse}
    ).one()
    assert (Decimal(fila.costo_total), fila.moneda_costo) == (MOUSE_ARS * D * 2, "ARS")


@pytest.mark.parametrize("endpoint,df_id", LISTADOS)
def test_live_listing_costs_costo_si_with_costo_d_and_l19(engine: Engine, db: Session, endpoint, df_id) -> None:
    nb, sin_si = _venta(engine, df_id, [{"item": NB, "qty": "2"}, {"item": SIN_SI}])
    (combo,) = _venta(engine, df_id, [{"item": COMBO}])  # alone: no component in its sale
    principal, *_ = _venta(engine, df_id, _grupo(COMBO, [(NB, "1"), (MOUSE, "2")]))
    combo_suelto, nb2, mouse2 = _venta(engine, df_id, [{"item": COMBO}, {"item": NB}, {"item": MOUSE, "qty": "2"}])

    costos = _listado(db, endpoint)

    assert costos[nb] == NB_ARS * D * 2
    assert costos[sin_si] == Decimal("3000") * D
    assert costos[combo] == COMBO_ARS * D  # no breakdown in its sale
    assert costos[principal] == (NB_ARS + 2 * MOUSE_ARS) * D  # group: the combo line is not added again
    assert costos[combo_suelto] == Decimal(0)  # its breakdown is in the same sale
    assert (costos[nb2], costos[mouse2]) == (NB_ARS * D, MOUSE_ARS * D * 2)
