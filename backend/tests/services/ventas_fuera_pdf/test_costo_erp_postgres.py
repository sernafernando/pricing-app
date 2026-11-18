"""vpf-costo-d-erp: a PDF line's cost comes from the ERP cost list, like Ventas por Fuera (anterior).

Owner L3 (fix B): "calcular desde la lista de costos del ERP": Costo D = ERP cost list x FX x 1.065, exactly like
Ventas por Fuera (anterior); the PDF "Precio Costo" is NOT used as cost (keep it only as reference if shown) ... and
the manual cost override keeps working.
Rule of (anterior) (`scripts/agregar_metricas_fuera_ml.py`): the item's last cost of list 1 created on or before the
sale date; pesos as is, dollars x `tipo_cambio` USD venta of the sale date (else `tb_cur_exch_history`, else 1); no
cost -> 0. The line stores `precio_costo` = that x cantidad; the screens add Costo D (x 1.065) on top.

Real Postgres, documents built in code; every code, article and amount is INVENTED.
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
    costo_erp,
    doc,
    linea,
    lineas,
    producto,
    reporte,
)

pytestmark = pytest.mark.postgres

VENTA = date(2026, 10, 5)
NB, MOUSE, OTRO = "7790000000101", "7790000000202", "7790000000303"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("vf_pdf_costo_erp", TABLAS, STUBS) as engine:
        yield engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield session
    with engine.begin() as conn:
        conn.execute(text(TRUNCATE))


@pytest.fixture
def mundo(engine: Engine) -> None:
    """Notebook 701 at USD 1,000 since 2026-10-01; USD 1,500 on 2026-10-04."""
    with engine.begin() as conn:
        producto(conn, 701, NB, "NOTEBOOK EJEMPLO")
        producto(conn, 702, MOUSE, "MOUSE EJEMPLO")
        producto(conn, 703, OTRO, "OTRO EJEMPLO")
        costo_erp(conn, 701, "1000", datetime(2026, 10, 1, 9, 30))
        cambio(conn, date(2026, 10, 4), 1500)


def _cargar(db: Session, *documentos):
    return cargar(db, reporte(*documentos), None, "detallada.pdf", None, usuario_id=7)


def _costo(engine: Engine, numero: int, renglon: int = 1) -> Decimal:
    return lineas(engine)[(numero, renglon)]["precio_costo"]


class TestCargaCuestaConElErp:
    def test_two_invoices_of_the_same_product_and_day_get_the_same_costo_d_whatever_the_pdf_says(
        self, engine: Engine, db: Session, mundo: None
    ) -> None:
        # Shape of the owner's L2 example: the PDF gave each invoice a different cost (~7% over USD x rate).
        _cargar(
            db,
            doc(1, [linea(NB, "NOTEBOOK EJEMPLO", cantidad="1", precio="1700000", costo="1605000")], fecha=VENTA),
            doc(2, [linea(NB, "NOTEBOOK EJEMPLO", cantidad="3", precio="5100000", costo="4830000")], fecha=VENTA),
        )

        filas = lineas(engine)
        assert filas[(1, 1)]["precio_costo"] == Decimal("1500000.00")  # 1,000 USD x 1,500 x 1
        assert filas[(2, 1)]["precio_costo"] == Decimal("4500000.00")  # x 3
        # The PDF's cost is kept only as a reference.
        assert (filas[(1, 1)]["precio_costo_pdf"], filas[(2, 1)]["precio_costo_pdf"]) == (
            Decimal("1605000.00"),
            Decimal("4830000.00"),
        )
        costo_d_unitario = {
            n: filas[(n, 1)]["precio_costo"] * COSTO_D_FACTOR / filas[(n, 1)]["cantidad"] for n in (1, 2)
        }
        assert costo_d_unitario[1] == costo_d_unitario[2] == Decimal("1597500")

    def test_a_cost_created_after_the_sale_date_even_the_same_day_is_not_used(
        self, engine: Engine, db: Session, mundo: None
    ) -> None:
        with engine.begin() as conn:
            costo_erp(conn, 701, "2000", datetime(2026, 10, 5, 10, 0))  # same day, after midnight
            costo_erp(conn, 701, "3000", datetime(2026, 10, 6))

        _cargar(db, doc(1, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=VENTA))

        assert _costo(engine, 1) == Decimal("1500000.00")

    def test_the_highest_iclh_id_on_or_before_the_date_of_list_1_wins(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 701, NB)
            cambio(conn, date(2026, 10, 4), 1500)
            costo_erp(conn, 701, "900", datetime(2026, 10, 2), iclh_id=20)
            costo_erp(
                conn, 701, "800", datetime(2026, 10, 3), iclh_id=10
            )  # later date, lower id: (anterior) orders by id
            costo_erp(conn, 701, "5", datetime(2026, 10, 3), iclh_id=30, coslis_id=2)  # another cost list

        _cargar(db, doc(1, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=VENTA))

        assert _costo(engine, 1) == Decimal("1350000.00")  # 900 x 1,500

    @pytest.mark.parametrize("curr_id", [1, None])
    def test_a_cost_in_pesos_is_not_converted(self, engine: Engine, db: Session, curr_id) -> None:
        with engine.begin() as conn:
            producto(conn, 702, MOUSE)
            cambio(conn, date(2026, 10, 4), 1500)
            costo_erp(conn, 702, "12345.67", datetime(2026, 10, 1), curr_id=curr_id)

        _cargar(db, doc(1, [linea(MOUSE, "MOUSE EJEMPLO", cantidad="2")], fecha=VENTA))

        assert _costo(engine, 1) == Decimal("24691.34")

    def test_the_rate_is_the_latest_on_or_before_the_sale_date(self, engine: Engine, db: Session, mundo: None) -> None:
        with engine.begin() as conn:
            cambio(conn, date(2026, 10, 6), 9999)

        _cargar(db, doc(1, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=VENTA))

        assert _costo(engine, 1) == Decimal("1500000.00")

    def test_without_tipo_cambio_the_erp_rate_is_used_and_without_any_rate_1(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 701, NB)
            costo_erp(conn, 701, "1000", datetime(2026, 10, 1))
            conn.execute(
                text(
                    "INSERT INTO tb_cur_exch_history (ceh_id, comp_id, curr_id_1, curr_id_2, ceh_cd, ceh_exchange) "
                    "VALUES (1, 1, 2, 1, '2026-10-02 12:00', 1400), (2, 1, 2, 1, '2026-10-05 12:00', 9999)"
                )
            )

        _cargar(
            db,
            doc(1, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=VENTA),
            doc(2, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=date(2026, 10, 1)),
        )

        assert _costo(engine, 1) == Decimal("1400000.00")
        assert _costo(engine, 2) == Decimal("1000.00")  # no rate on or before 2026-10-01: x 1, like (anterior)

    def test_no_erp_cost_or_no_product_costs_0_and_the_pdf_cost_is_not_used(
        self, engine: Engine, db: Session, mundo: None
    ) -> None:
        _cargar(
            db,
            doc(
                1,
                [
                    linea(MOUSE, "MOUSE EJEMPLO", costo="5000"),
                    linea(None, "Servicio Tecnico (Manual)", costo="7000"),
                ],
                fecha=VENTA,
            ),
        )

        filas = lineas(engine)
        assert (filas[(1, 1)]["precio_costo"], filas[(1, 2)]["precio_costo"]) == (Decimal("0.00"), Decimal("0.00"))
        assert (filas[(1, 1)]["precio_costo_pdf"], filas[(1, 2)]["precio_costo_pdf"]) == (
            Decimal("5000.00"),
            Decimal("7000.00"),
        )

    def test_a_credit_note_line_keeps_its_negative_quantity_and_cost(
        self, engine: Engine, db: Session, mundo: None
    ) -> None:
        _cargar(db, doc(1, [linea(NB, "NOTEBOOK EJEMPLO", cantidad="-2", precio="-3400000")], tipo="Nc", fecha=VENTA))

        assert _costo(engine, 1) == Decimal("-3000000.00")


class TestCorreccionesManuales:
    def _linea_id(self, engine: Engine, numero: int = 1, renglon: int = 1) -> int:
        return lineas(engine)[(numero, renglon)]["id"]

    def test_a_manual_cost_still_wins_and_survives_a_reupload(self, engine: Engine, db: Session, mundo: None) -> None:
        documento = doc(1, [linea(NB, "NOTEBOOK EJEMPLO")], fecha=VENTA)
        _cargar(db, documento)

        overrides.guardar(db, self._linea_id(engine), {"costo_unitario": 1200000}, False, 7)
        assert _costo(engine, 1) == Decimal("1200000.00")

        _cargar(db, documento)
        assert _costo(engine, 1) == Decimal("1200000.00")

    def test_a_manual_product_without_cost_takes_that_products_erp_cost(
        self, engine: Engine, db: Session, mundo: None
    ) -> None:
        with engine.begin() as conn:
            costo_erp(conn, 703, "20", datetime(2026, 10, 1))
        _cargar(db, doc(1, [linea(None, "ARTICULO SIN CODIGO", cantidad="2")], fecha=VENTA))

        overrides.guardar(db, self._linea_id(engine), {"item_id": 703}, False, 7)

        assert _costo(engine, 1) == Decimal("60000.00")  # 20 USD x 1,500 x 2

    def test_removing_the_fix_goes_back_to_the_erp_cost(self, engine: Engine, db: Session, mundo: None) -> None:
        _cargar(db, doc(1, [linea(NB, "NOTEBOOK EJEMPLO", costo="1605000")], fecha=VENTA))
        overrides.guardar(db, self._linea_id(engine), {"costo_unitario": 1200000}, False, 7)

        overrides.quitar(db, self._linea_id(engine))

        assert _costo(engine, 1) == Decimal("1500000.00")

    def test_a_remembered_product_gives_the_sibling_lines_its_erp_cost(
        self, engine: Engine, db: Session, mundo: None
    ) -> None:
        _cargar(
            db,
            doc(1, [linea(None, "NB SIN CODIGO EJEMPLO", costo="1")], fecha=VENTA),
            doc(2, [linea(None, "NB SIN CODIGO EJEMPLO", cantidad="2", costo="2")], fecha=VENTA),
        )

        overrides.guardar(db, self._linea_id(engine, 1), {"item_id": 701}, True, 7)

        assert (_costo(engine, 1), _costo(engine, 2)) == (Decimal("1500000.00"), Decimal("3000000.00"))


class TestRecostear:
    """Lines loaded before vpf-costo-d-erp keep the PDF's cost until recomputed (owner L3: "ask me with the impact
    before doing it"): `recostear` reports by default and writes only with `aplicar=True`."""

    def _pdf_como_costo(self, engine: Engine) -> None:
        # What a pre-fix load stored: the PDF's "Precio Costo" as precio_costo.
        with engine.begin() as conn:
            conn.execute(text("UPDATE ventas_fuera_operacion_lineas SET precio_costo = precio_costo_pdf"))

    def test_dry_run_reports_the_changes_and_writes_nothing(self, engine: Engine, db: Session, mundo: None) -> None:
        _cargar(
            db,
            doc(1, [linea(NB, "NOTEBOOK EJEMPLO", costo="1605000"), linea(None, "SIN CODIGO", costo="7")], fecha=VENTA),
        )
        self._pdf_como_costo(engine)

        cambios = recostear(db)

        assert [(c.antes, c.despues) for c in cambios] == [
            (Decimal("1605000.00"), Decimal("1500000.00")),
            (Decimal("7.00"), Decimal("0")),
        ]
        assert (_costo(engine, 1, 1), _costo(engine, 1, 2)) == (Decimal("1605000.00"), Decimal("7.00"))

    def test_aplicar_writes_the_erp_cost_and_keeps_manual_costs(self, engine: Engine, db: Session, mundo: None) -> None:
        _cargar(
            db,
            doc(1, [linea(NB, "NOTEBOOK EJEMPLO", costo="1605000")], fecha=VENTA),
            doc(2, [linea(NB, "NOTEBOOK EJEMPLO", costo="1605000")], fecha=VENTA),
        )
        overrides.guardar(db, lineas(engine)[(2, 1)]["id"], {"costo_unitario": 1200000}, False, 7)
        self._pdf_como_costo(engine)
        with engine.begin() as conn:
            # The manual cost stays as it was saved.
            conn.execute(
                text(
                    "UPDATE ventas_fuera_operacion_lineas l SET precio_costo = 1200000 "
                    "FROM ventas_fuera_operaciones o WHERE o.id = l.operacion_id AND o.numero = 2"
                )
            )

        cambios = recostear(db, aplicar=True)

        assert [c.antes for c in cambios] == [Decimal("1605000.00")]
        assert (_costo(engine, 1), _costo(engine, 2)) == (Decimal("1500000.00"), Decimal("1200000.00"))

    def test_the_date_range_limits_the_lines(self, engine: Engine, db: Session, mundo: None) -> None:
        _cargar(
            db,
            doc(1, [linea(NB, "NOTEBOOK EJEMPLO", costo="1605000")], fecha=VENTA),
            doc(2, [linea(NB, "NOTEBOOK EJEMPLO", costo="1605000")], fecha=date(2026, 10, 9)),
        )
        self._pdf_como_costo(engine)

        cambios = recostear(db, desde=date(2026, 10, 6), aplicar=True)

        assert [c.fecha for c in cambios] == [date(2026, 10, 9)]
        assert (_costo(engine, 1), _costo(engine, 2)) == (Decimal("1605000.00"), Decimal("1500000.00"))
