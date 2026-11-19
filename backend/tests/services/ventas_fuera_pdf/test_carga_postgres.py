"""Load of the GBP sales PDFs into the ventas por fuera operations (T1: S3, S5, S6, S7, S10, S11, S12, S18, S21).

Real Postgres; anonymized copies of real captures (GRUPO GAUSS SRL, March 2025, see test_parser). Owner on loading (S5): "Verificar
que los datos no se dupliquen, pueden subirla diariamente si quieren para actualizar la vista, pero quizás abarcan 2
pdfs las mismas operaciones." Rule: the last PDF rules its salesperson and range.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import Engine, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.cur_exch_history import CurExchHistory
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.tb_item import TBItem
from app.models.tipo_cambio import TipoCambio
from app.models.venta_fuera_pdf import (
    VentaFueraCodigoMapeo,
    VentaFueraLineaOverride,
    VentaFueraOperacion,
    VentaFueraOperacionLinea,
    VentaFueraPdfAlcance,
    VentaFueraPdfCarga,
    VentaFueraPdfResumenDocumento,
)
from app.services.ventas_fuera_pdf.carga import CargaInvalida, cargar, listar_operaciones, productos_por_codigo
from app.services.ventas_fuera_pdf.parser import parse_detallada, parse_resumen
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ventas_fuera_pdf"
EMPRESA = "GRUPO GAUSS SRL"
TABLAS = [
    VentaFueraPdfCarga.__table__,
    VentaFueraOperacion.__table__,
    VentaFueraOperacionLinea.__table__,
    VentaFueraPdfAlcance.__table__,
    VentaFueraPdfResumenDocumento.__table__,
    # Read by the load since vpf-operaciones (product resolution, manual fixes re-applied).
    VentaFueraLineaOverride.__table__,
    VentaFueraCodigoMapeo.__table__,
    TBItem.__table__,
    # The ERP cost list and USD rates the load costs each line with (vpf-costo-d-erp); empty here.
    ItemCostListHistory.__table__,
    TipoCambio.__table__,
    CurExchHistory.__table__,
    ProductoERP.__table__,
    MarcaPM.__table__,
]
STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre VARCHAR(255) NOT NULL)",
    "INSERT INTO usuarios VALUES (7, 'Uploader'), (8, 'PM TP-Link')",
]


@pytest.fixture(scope="module")
def detallada():
    return parse_detallada((FIXTURES / "gbp_detallada_anonimizada.pdf").read_bytes())


@pytest.fixture(scope="module")
def resumen():
    return parse_resumen((FIXTURES / "gbp_resumen_anonimizado.pdf").read_bytes())


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("vf_pdf_carga", TABLAS, STUBS) as engine:
        yield engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield session
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE ventas_fuera_pdf_resumen_documentos, ventas_fuera_pdf_alcances, ventas_fuera_operacion_lineas, "
                "ventas_fuera_operaciones, ventas_fuera_pdf_cargas CASCADE"
            )
        )
        conn.execute(text("TRUNCATE productos_erp, marcas_pm"))


def _cargar(db: Session, detallada, resumen=None):
    return cargar(db, detallada, resumen, "detallada.pdf", "resumen.pdf" if resumen else None, usuario_id=7)


def _ops(db: Session) -> list[VentaFueraOperacion]:
    return list(db.execute(select(VentaFueraOperacion)).scalars())


def _otra(db: Session, carga_id: int, *, empresa=EMPRESA, vendedor="Carla Ejempl", fecha=date(2025, 3, 5), numero=1):
    db.add(
        VentaFueraOperacion(
            carga_id=carga_id,
            empresa=empresa,
            vendedor=vendedor,
            cliente="X",
            tipo="Fc",
            letra="A",
            punto_venta=99,
            numero=numero,
            fecha=fecha,
            importe=Decimal("121"),
            saldo=Decimal("0"),
            total_lineas=Decimal("100"),
            recargo_financiero=Decimal("0"),
        )
    )
    db.commit()


class TestCargaDeLasMuestras:
    def test_creates_one_operation_per_document_with_its_lines(self, db: Session, detallada, resumen) -> None:
        resultado = _cargar(db, detallada, resumen)

        ops = _ops(db)
        assert (resultado.documentos, len(ops)) == (166, 166)
        assert resultado.lineas == db.execute(select(func.count(VentaFueraOperacionLinea.id))).scalar_one()
        assert {op.empresa for op in ops} == {EMPRESA}
        assert resultado.total_lineas == Decimal("169632759.59")
        assert sum((op.total_lineas for op in ops), Decimal("0")) == Decimal("169632759.59")
        assert sum((op.saldo for op in ops), Decimal("0")) == Decimal("84671927.60")
        assert resultado.avisos == []

    def test_credit_notes_are_stored_negative(self, db: Session, detallada, resumen) -> None:
        _cargar(db, detallada, resumen)

        nc = [op for op in _ops(db) if op.tipo == "Nc"]
        assert len(nc) == 6
        assert all(op.total_lineas < 0 and all(ln.precio < 0 for ln in op.lineas) for op in nc)

    def test_the_cheque_surcharge_is_kept_apart_from_the_sale(self, db: Session, detallada, resumen) -> None:
        resultado = _cargar(db, detallada, resumen)

        con_recargo = {
            f"{op.punto_venta}-{op.numero}": op.recargo_financiero for op in _ops(db) if op.recargo_financiero
        }
        assert con_recargo == {
            "8-17865": Decimal("124066.59"),
            "8-17938": Decimal("12336.29"),
            "8-17942": Decimal("37364.14"),
            "8-17995": Decimal("31082.73"),
            "8-18004": Decimal("5783.45"),
            "8-18054": Decimal("263974.26"),
            "8-18212": Decimal("5783.45"),
        }
        # Per document the surcharges add to 480,390.91.
        assert resultado.recargo_financiero == Decimal("480390.91")
        cheque = next(op for op in _ops(db) if op.numero == 18054)
        assert (cheque.condicion_venta, cheque.total_lineas, cheque.importe_resumen) == (
            "CHEQUE 30 D",
            Decimal("6599356.44"),
            Decimal("6863330.70"),
        )

    def test_columns_of_a_line_and_its_document(self, db: Session, detallada, resumen) -> None:
        _cargar(db, detallada, resumen)
        # vpf-costo-d-erp: the PDF's "Precio Costo" is only a reference (`precio_costo_pdf`); with no ERP cost list
        # in this world every line's cost is 0.
        assert {ln.precio_costo for op in _ops(db) for ln in op.lineas} == {Decimal("0.00")}

        op = next(op for op in _ops(db) if (op.tipo, op.letra, op.punto_venta, op.numero) == ("Fc", "A", 8, 17982))
        assert (op.cliente, op.cliente_codigo, op.vendedor) == ("CLIENTE PRUEBA 055", "100055", "Carla Ejempl")
        assert (op.fecha, op.fecha_vencimiento, op.condicion_venta) == (
            date(2025, 3, 13),
            date(2025, 3, 13),
            "01-Contado",
        )
        assert [
            (ln.renglon, ln.codigo, ln.cantidad, ln.moneda, ln.precio, ln.precio_costo_pdf, ln.precio_costo_pp)
            for ln in op.lineas
        ] == [
            (
                1,
                "198154111069",
                Decimal("1.00"),
                "ARS",
                Decimal("1198000.66"),
                Decimal("1106663.18"),
                Decimal("1135399.28"),
            ),
            (2, None, Decimal("1.00"), "ARS", Decimal("20632.29"), Decimal("0.00"), Decimal("0.00")),
        ]


class TestReemplazo:
    def test_loading_the_same_pdfs_twice_changes_nothing(self, db: Session, detallada, resumen) -> None:
        _cargar(db, detallada, resumen)
        antes = sorted(
            (op.tipo, op.letra, op.punto_venta, op.numero, op.total_lineas, len(op.lineas)) for op in _ops(db)
        )

        segundo = _cargar(db, detallada, resumen)
        db.expire_all()

        despues = sorted(
            (op.tipo, op.letra, op.punto_venta, op.numero, op.total_lineas, len(op.lineas)) for op in _ops(db)
        )
        assert despues == antes
        assert (segundo.reemplazados, segundo.documentos) == (166, 166)
        assert db.execute(select(func.count(VentaFueraOperacionLinea.id))).scalar_one() == segundo.lineas

    def test_replaces_its_salesperson_and_range_and_leaves_the_rest(self, db: Session, detallada, resumen) -> None:
        primera = _cargar(db, detallada, resumen)
        _otra(db, primera.carga_id, numero=1)  # voided in GBP: same salesperson and range, not in the PDF
        _otra(db, primera.carga_id, numero=2, fecha=date(2025, 4, 2))  # same salesperson, another range
        _otra(db, primera.carga_id, numero=3, vendedor="Juan Perez")  # another salesperson, same range
        _otra(db, primera.carga_id, numero=4, empresa="PASTORIZA")  # another company

        _cargar(db, detallada, resumen)
        db.expire_all()

        quedan = {op.numero for op in _ops(db) if op.punto_venta == 99}
        assert quedan == {2, 3, 4}
        assert len(_ops(db)) == 166 + 3

    def test_a_pdf_for_every_salesperson_replaces_all_of_them_in_its_range(
        self, db: Session, detallada, resumen
    ) -> None:
        primera = _cargar(db, detallada, resumen)
        _otra(db, primera.carga_id, numero=3, vendedor="Juan Perez")
        _otra(db, primera.carga_id, numero=4, empresa="PASTORIZA")
        todos = dataclasses.replace(detallada, vendedor=None)

        resultado = _cargar(db, todos)
        db.expire_all()

        assert {op.numero for op in _ops(db) if op.punto_venta == 99} == {4}
        assert resultado.vendedor is None

    def test_a_document_loaded_under_another_scope_is_replaced_not_duplicated(
        self, db: Session, detallada, resumen
    ) -> None:
        primera = _cargar(db, detallada, resumen)
        db.execute(text("UPDATE ventas_fuera_operaciones SET vendedor = 'Otro Vended' WHERE numero = 17982"))
        db.commit()

        _cargar(db, detallada, resumen)
        db.expire_all()

        assert [op.vendedor for op in _ops(db) if op.numero == 17982] == ["Carla Ejempl"]
        assert primera.documentos == len(_ops(db))

    def test_a_salesperson_pdf_leaves_documents_of_other_names_that_only_share_a_prefix(
        self, db: Session, detallada, resumen
    ) -> None:
        """Documents print the salesperson cut to 12 characters; a shorter stored name is a different person, and a
        document without salesperson belongs to nobody's scope."""
        primera = _cargar(db, detallada, resumen)
        _otra(db, primera.carga_id, numero=5, vendedor="Carla")
        _otra(db, primera.carga_id, numero=6, vendedor="")

        _cargar(db, detallada, resumen)
        db.expire_all()

        assert {op.numero for op in _ops(db) if op.punto_venta == 99} == {5, 6}


class TestControlConElResumen:
    def test_without_summary_the_sale_is_loaded_and_the_surcharge_is_not_separated(
        self, db: Session, detallada
    ) -> None:
        resultado = _cargar(db, detallada)

        assert resultado.documentos == 166
        assert resultado.recargo_financiero == 0
        assert all(op.importe_resumen is None and op.condicion_venta is None for op in _ops(db))
        assert resultado.avisos == ["Falta subir el reporte de ventas (resumen) de este período."]
        assert (resultado.falta_detallada, resultado.falta_resumen) == (False, True)

    def test_a_summary_of_another_range_is_refused_and_nothing_changes(self, db: Session, detallada, resumen) -> None:
        otro = dataclasses.replace(resumen, hasta=date(2025, 3, 30))

        with pytest.raises(CargaInvalida, match="no corresponde al detallado"):
            _cargar(db, detallada, otro)

        assert _ops(db) == []

    def test_documents_missing_in_either_report_are_warned(self, db: Session, detallada, resumen) -> None:
        sin_uno = dataclasses.replace(resumen, documentos=[d for d in resumen.documentos if d.numero != 17982])
        extra = dataclasses.replace(resumen.documentos[0], numero=99999999)
        sin_uno.documentos.append(extra)

        resultado = _cargar(db, detallada, sin_uno)

        assert resultado.avisos == [
            "Fc A 00008-99999999 está en el reporte de ventas pero no en el detallado.",
            "Fc A 00008-00017982 está en el detallado pero no en el reporte de ventas.",
        ]
        assert db.get(VentaFueraPdfCarga, resultado.carga_id).avisos == resultado.avisos

    def test_a_non_cheque_amount_mismatch_is_warned(self, db: Session, detallada, resumen) -> None:
        docs = [dataclasses.replace(d, importe=d.importe + 1) if d.numero == 17982 else d for d in resumen.documentos]

        resultado = _cargar(db, detallada, dataclasses.replace(resumen, documentos=docs))

        assert resultado.avisos == [
            "Fc A 00008-00017982: el reporte de ventas dice 1218633.95 y las líneas suman 1218632.95."
        ]
        assert resultado.recargo_financiero == Decimal("480390.91")

    def test_a_summary_with_taxes_does_not_separate_a_surcharge(self, db: Session, detallada, resumen) -> None:
        """With "Con Impuestos: Si" the summary Importe carries VAT: the difference is not the cheque surcharge."""
        con_iva = dataclasses.replace(
            resumen,
            con_impuestos=True,
            documentos=[
                dataclasses.replace(d, importe=(d.importe * Decimal("1.21")).quantize(Decimal("0.01")))
                for d in resumen.documentos
            ],
        )

        resultado = _cargar(db, detallada, con_iva)

        assert resultado.recargo_financiero == 0
        assert all(op.recargo_financiero == 0 for op in _ops(db))
        assert resultado.avisos == [
            "El reporte de ventas está exportado con impuestos: los importes no se pueden comparar."
        ]

    @pytest.mark.parametrize(
        ("importe_resumen", "aviso"),
        [
            (
                Decimal("3111664.66"),
                "Fc A 00008-00017865: el recargo del cheque es 10000.00 y el 4% de las líneas es 124066.59.",
            ),
            (
                Decimal("3091664.66"),
                "Fc A 00008-00017865: el recargo del cheque es -10000.00 y el 4% de las líneas es 124066.59.",
            ),
        ],
    )
    def test_a_cheque_surcharge_that_is_not_4_percent_is_warned_and_still_stored(
        self, db: Session, detallada, resumen, importe_resumen, aviso
    ) -> None:
        """Verifier advisory (b): the surcharge is the summary Importe minus the lines; when it is negative or not
        close to 4% of the lines the load says so, and the difference is still kept apart from the sale."""
        docs = [dataclasses.replace(d, importe=importe_resumen) if d.numero == 17865 else d for d in resumen.documentos]

        resultado = _cargar(db, detallada, dataclasses.replace(resumen, documentos=docs))

        assert resultado.avisos == [aviso]
        op = next(op for op in _ops(db) if op.numero == 17865)
        assert op.recargo_financiero == importe_resumen - Decimal("3101664.66")

    def test_the_seven_sample_surcharges_are_4_percent_and_not_warned(self, db: Session, detallada, resumen) -> None:
        assert _cargar(db, detallada, resumen).avisos == []


class TestAlcanceReemplazado:
    def test_a_later_load_that_replaces_a_scopes_operations_is_shown_on_that_scope(
        self, db: Session, detallada, resumen
    ) -> None:
        """GGA: a "Todos" upload over the same range replaces the salesperson scope's operations; that scope must say
        so instead of still looking complete."""
        vendedora = _cargar(db, detallada, resumen)

        _cargar(db, dataclasses.replace(detallada, vendedor=None))

        alcance = db.get(VentaFueraPdfAlcance, vendedora.alcance_id)
        db.refresh(alcance)
        assert alcance.avisos[0] == (
            "166 comprobantes de este período se reemplazaron por una carga posterior (Todos, 01/03/2025-31/03/2025)."
        )


class TestProducto:
    def test_lines_join_their_product_by_code_and_unknown_codes_are_sin_producto(
        self, db: Session, detallada, resumen
    ) -> None:
        db.add(ProductoERP(item_id=501, codigo="198154111069", marca="LENOVO", categoria="Notebooks"))
        db.add(MarcaPM(marca="LENOVO", categoria="Notebooks", usuario_id=8))
        db.commit()
        _cargar(db, detallada, resumen)

        productos = productos_por_codigo(db, {"198154111069", "1210002613118"})

        assert set(productos) == {"198154111069"}
        p = productos["198154111069"]
        assert (p.item_id, p.marca, p.categoria, p.pm_usuario_id, p.pm_nombre) == (
            501,
            "LENOVO",
            "Notebooks",
            8,
            "PM TP-Link",
        )

    def test_each_line_stores_the_item_id_of_its_code_and_unknown_or_manual_lines_none(
        self, db: Session, detallada, resumen
    ) -> None:
        """VPF T4: offsets and sell in / sell out read the PDF lines by product (`item_id`)."""
        db.add(ProductoERP(item_id=501, codigo="198154111069", marca="LENOVO", categoria="Notebooks"))
        db.commit()
        _cargar(db, detallada, resumen)

        filas = db.execute(
            select(VentaFueraOperacionLinea.codigo, VentaFueraOperacionLinea.item_id).where(
                or_(
                    VentaFueraOperacionLinea.codigo.in_(["198154111069", "1210002613118"]),
                    VentaFueraOperacionLinea.codigo.is_(None),
                )
            )
        ).all()

        por_codigo = {codigo: {item for c, item in filas if c == codigo} for codigo, _ in filas}
        assert por_codigo == {"198154111069": {501}, "1210002613118": {None}, None: {None}}

    def test_listing_filters_by_company_and_range(self, db: Session, detallada, resumen) -> None:
        primera = _cargar(db, detallada, resumen)
        _otra(db, primera.carga_id, numero=4, empresa="PASTORIZA")

        gauss = listar_operaciones(db, EMPRESA, date(2025, 3, 1), date(2025, 3, 31))
        pastoriza = listar_operaciones(db, "PASTORIZA", date(2025, 3, 1), date(2025, 3, 31))
        un_dia = listar_operaciones(db, EMPRESA, date(2025, 3, 13), date(2025, 3, 13))

        assert (len(gauss), [op.numero for op in pastoriza]) == (166, [4])
        assert len(listar_operaciones(db, EMPRESA, date(2025, 3, 1), date(2025, 3, 31), "Carla Ejemplo")) == 166
        assert len(listar_operaciones(db, EMPRESA, date(2025, 3, 1), date(2025, 3, 31), "Carla Ejempl")) == 166
        assert listar_operaciones(db, EMPRESA, date(2025, 3, 1), date(2025, 3, 31), "Carla") == []
        assert un_dia and all(op.fecha == date(2025, 3, 13) for op in un_dia)
