"""sell-in-costo-si T3 PR 9: a PDF line of Ventas por fuera costs its product's costo SI, Costo D on top.

Owner L6.2: "costo d va a aplicar sobre costo si"; S13: costo SI is THE cost everywhere; S10/L18: it is in the product's
cost currency (an ARS product averages in ARS, never re-converted at a rate); S11: a combo = its components x
quantity; owner L19: "claro si el combo trae el desglose no tomarlo, si no lo trae sí". Products without costo SI keep
the list cost (`test_costo_erp_postgres.py`). Real Postgres, documents built in code; every code and amount is INVENTED.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.ventas_fuera_pdf import overrides
from app.services.ventas_fuera_pdf.carga import cargar
from app.services.ventas_fuera_pdf.costo_erp import recostear
from app.services.ventas_fuera_pdf.ventas import COSTO_D_FACTOR
from tests.services.sell._schema import throwaway_schema
from tests.services.ventas_fuera_pdf._mundo import (
    STUBS,
    TABLAS,
    TRUNCATE,
    cambio,
    componente,
    costo_erp,
    doc,
    linea,
    lineas,
    paso,
    producto,
    reporte,
)

pytestmark = pytest.mark.postgres

VENTA = date(2026, 10, 5)
NB, MOUSE, COMBO, SIN_SI = "7790000000101", "7790000000202", "7790000000909", "7790000000303"
P_NB, P_MOUSE, P_COMBO, P_SIN_SI = 701, 702, 710, 703


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("vf_pdf_costo_si", TABLAS, STUBS) as engine:
        yield engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield session
    with engine.begin() as conn:
        conn.execute(text(TRUNCATE))


@pytest.fixture
def mundo(engine: Engine) -> None:
    """Notebook (USD): list 1,200, costo SI 1,000 from 10-01 and 800 from 10-07. Mouse (ARS product): costo SI ARS
    50,000 from 10-01. Combo 710 = 1 notebook + 2 mice. USD at 1,500 from 10-04."""
    with engine.begin() as conn:
        producto(conn, P_NB, NB, "NOTEBOOK EJEMPLO", costo="1200", moneda_costo="USD")
        producto(conn, P_MOUSE, MOUSE, "MOUSE EJEMPLO", costo="60000", moneda_costo="ARS")
        producto(conn, P_COMBO, COMBO, "COMBO EJEMPLO")
        producto(conn, P_SIN_SI, SIN_SI, "SIN COSTO SI EJEMPLO", moneda_costo="USD")
        costo_erp(conn, P_NB, "1200", datetime(2026, 9, 1))
        costo_erp(conn, P_SIN_SI, "300", datetime(2026, 9, 1))
        paso(conn, P_NB, date(2026, 10, 1), "1000")
        paso(conn, P_NB, date(2026, 10, 7), "800", orden=1)
        paso(conn, P_MOUSE, date(2026, 10, 1), "50000", moneda="ARS")
        componente(conn, P_COMBO, P_NB, "1")
        componente(conn, P_COMBO, P_MOUSE, "2")
        cambio(conn, date(2026, 10, 4), 1500)


def _cargar(db: Session, *documentos):
    return cargar(db, reporte(*documentos), None, "detallada.pdf", None, usuario_id=7)


def _costo(engine: Engine, numero: int, renglon: int = 1) -> Decimal:
    return lineas(engine)[(numero, renglon)]["precio_costo"]


def test_the_line_costs_the_costo_si_not_the_list_cost_and_costo_d_goes_on_top(
    engine: Engine, db: Session, mundo: None
) -> None:
    _cargar(db, doc(1, [linea(NB, "NOTEBOOK EJEMPLO", cantidad="2", precio="4000000")], fecha=VENTA))

    assert _costo(engine, 1) == Decimal("3000000.00")  # 1,000 USD x 1,500 x 2 (list 1,200 would be 3,600,000)
    assert _costo(engine, 1) * COSTO_D_FACTOR == Decimal("3195000.0000")


def test_the_costo_si_in_force_on_the_sale_date_is_used(engine: Engine, db: Session, mundo: None) -> None:
    _cargar(
        db,
        doc(1, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=date(2026, 10, 6)),
        doc(2, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=date(2026, 10, 7)),
    )

    assert (_costo(engine, 1), _costo(engine, 2)) == (Decimal("1500000.00"), Decimal("1200000.00"))


def test_an_ars_product_costs_its_ars_costo_si_whatever_the_rate(engine: Engine, db: Session, mundo: None) -> None:
    """Owner L18: an ARS product's costo SI is in pesos; no rate touches it."""
    with engine.begin() as conn:
        cambio(conn, date(2026, 10, 5), 9999)

    _cargar(db, doc(1, [linea(MOUSE, "MOUSE EJEMPLO", cantidad="3")], fecha=VENTA))

    assert _costo(engine, 1) == Decimal("150000.00")  # 50,000 ARS x 3


def test_without_costo_si_the_line_keeps_the_list_cost(engine: Engine, db: Session, mundo: None) -> None:
    _cargar(db, doc(1, [linea(SIN_SI, "SIN COSTO SI EJEMPLO")], fecha=VENTA))

    assert _costo(engine, 1) == Decimal("450000.00")  # list 300 USD x 1,500


def test_a_combo_without_its_breakdown_costs_its_components_costo_si(engine: Engine, db: Session, mundo: None) -> None:
    """L19 "si no lo trae sí": the document has only the combo line."""
    _cargar(db, doc(1, [linea(COMBO, "COMBO EJEMPLO", precio="2000000"), linea(None, "FLETE")], fecha=VENTA))

    assert _costo(engine, 1) == Decimal("1600000.00")  # 1,000 USD x 1,500 + 2 x 50,000 ARS


def test_a_combo_broken_down_in_its_document_costs_0_and_its_components_carry_the_cost(
    engine: Engine, db: Session, mundo: None
) -> None:
    """L19 "si el combo trae el desglose no tomarlo", the shape GBP prints: the combo at price 0, then its parts."""
    _cargar(
        db,
        doc(
            1,
            [
                linea(COMBO, "COMBO EJEMPLO", precio="0"),
                linea(NB, "NOTEBOOK EJEMPLO", precio="1800000"),
                linea(MOUSE, "MOUSE EJEMPLO", cantidad="2", precio="200000"),
            ],
            fecha=VENTA,
        ),
        doc(2, [linea(COMBO, "COMBO EJEMPLO", precio="2000000")], fecha=VENTA),  # another document: not broken down
    )

    assert [_costo(engine, 1, r) for r in (1, 2, 3)] == [Decimal("0.00"), Decimal("1500000.00"), Decimal("100000.00")]
    assert _costo(engine, 2) == Decimal("1600000.00")


def test_a_combo_with_only_one_loose_component_in_its_document_is_not_broken_down(
    engine: Engine, db: Session, mundo: None
) -> None:
    """L19: one extra mouse next to the combo is not its breakdown (the notebook is missing): the combo costs its
    components and the loose mouse its own."""
    _cargar(
        db,
        doc(
            1,
            [linea(COMBO, "COMBO EJEMPLO", precio="2000000"), linea(MOUSE, "MOUSE EJEMPLO", precio="100000")],
            fecha=VENTA,
        ),
    )

    assert [_costo(engine, 1, r) for r in (1, 2)] == [Decimal("1600000.00"), Decimal("50000.00")]


def test_a_credit_note_line_keeps_its_negative_quantity_and_cost(engine: Engine, db: Session, mundo: None) -> None:
    _cargar(db, doc(1, [linea(NB, "NOTEBOOK EJEMPLO", cantidad="-2", precio="-3400000")], tipo="Nc", fecha=VENTA))

    assert _costo(engine, 1) == Decimal("-3000000.00")


def test_a_product_assigned_by_hand_costs_that_products_costo_si(engine: Engine, db: Session, mundo: None) -> None:
    _cargar(db, doc(1, [linea(None, "NOTEBOOK SIN CODIGO EJEMPLO")], fecha=VENTA))
    assert _costo(engine, 1) == Decimal("0.00")

    overrides.guardar(db, lineas(engine)[(1, 1)]["id"], {"item_id": P_NB}, False, 7)

    assert _costo(engine, 1) == Decimal("1500000.00")


def test_recostear_by_product_and_date_recosts_only_those_lines(engine: Engine, db: Session, mundo: None) -> None:
    _cargar(
        db,
        doc(1, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=VENTA),
        doc(2, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=date(2026, 10, 8)),
        doc(3, [linea(MOUSE, "MOUSE EJEMPLO")], fecha=date(2026, 10, 8)),
    )
    with engine.begin() as conn:
        conn.execute(text("UPDATE costo_si_pasos SET promedio_usd = promedio_usd / 2"))

    cambios = recostear(db, desde=date(2026, 10, 6), items=[P_NB], aplicar=True)

    assert [(c.fecha, c.antes, c.despues) for c in cambios] == [
        (date(2026, 10, 8), Decimal("1200000.00"), Decimal("600000.00"))
    ]
    assert [_costo(engine, n) for n in (1, 2, 3)] == [
        Decimal("1500000.00"),
        Decimal("600000.00"),
        Decimal("50000.00"),
    ]
