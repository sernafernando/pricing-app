"""vpf-operaciones S3a / S3b / S3: how a PDF line finds its product at load.

S3a (L1): the product match trims both sides (prod `productos_erp.codigo` is padded with trailing spaces).
S3b (L1): "a line with no code resolves by the FIRST whitespace token of `articulo` (btrim, case-insensitive, exact)
against productos_erp.codigo, then tb_item.item_code. A code not found in productos_erp also tries tb_item.item_code.
Ambiguous (>1 match) = unresolved."
S3: "assign the real product (and remember the mapping so the next uploads of that code resolve automatically)".
Order: mapping > productos_erp by code > tb_item by code > first-token prefix (productos_erp, then tb_item).

Real Postgres, documents built in code; every code, article and amount is INVENTED.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.ventas_fuera_pdf.carga import cargar
from app.services.ventas_fuera_pdf.resolucion import clave_mapeo, primer_token, resolver
from tests.services.sell._schema import throwaway_schema
from tests.services.ventas_fuera_pdf._mundo import STUBS, TABLAS, TRUNCATE, doc, item, linea, lineas, producto, reporte

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("vf_pdf_resolucion", TABLAS, STUBS) as engine:
        yield engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield session
    with engine.begin() as conn:
        conn.execute(text(TRUNCATE))


def _cargar(db: Session, *documentos):
    return cargar(db, reporte(*documentos), None, "detallada.pdf", None, usuario_id=7)


def _sql(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


class TestPorCodigo:
    def test_a_code_padded_with_trailing_spaces_in_productos_erp_is_found(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 501, "7790000000017    ")

        resultado = _cargar(db, doc(1, [linea("7790000000017", "MONITOR EJEMPLO 24")]))

        fila = lineas(engine)[(1, 1)]
        assert (fila["item_id"], fila["item_origen"]) == (501, "codigo")
        assert resultado.sin_producto["lineas"] == 0

    def test_a_code_not_in_productos_erp_tries_tb_item_item_code(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            item(conn, 601, "CODEJ-100 ")
            item(conn, 601, "CODEJ-100", comp_id=2)

        _cargar(db, doc(1, [linea("CODEJ-100", "CABLE EJEMPLO")]))

        fila = lineas(engine)[(1, 1)]
        assert (fila["item_id"], fila["item_origen"]) == (601, "codigo")

    def test_an_unknown_code_stays_sin_producto(self, engine: Engine, db: Session) -> None:
        resultado = _cargar(db, doc(1, [linea("7790000099999", "CABLE DESCONOCIDO")]))

        fila = lineas(engine)[(1, 1)]
        assert (fila["item_id"], fila["item_origen"]) == (None, None)
        assert resultado.sin_producto["lineas"] == 1


class TestPorPrefijo:
    def test_a_line_without_code_resolves_by_the_first_token_of_its_article(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 502, " pcej4-8u ")
            item(conn, 603, "NBEJ5-8")

        _cargar(
            db,
            doc(
                1,
                [
                    linea(None, "PCEJ4-8U PC Ejemplo i3 8GB"),
                    linea(None, "  nbej5-8   Notebook Ejemplo"),
                    linea(None, "Servicio Tecnico (Manual)"),
                ],
            ),
        )

        filas = lineas(engine)
        assert [(filas[(1, r)]["item_id"], filas[(1, r)]["item_origen"]) for r in (1, 2, 3)] == [
            (502, "prefijo"),
            (603, "prefijo"),
            (None, None),
        ]

    def test_productos_erp_wins_over_tb_item(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 502, "PCEJ4-8U")
            item(conn, 699, "PCEJ4-8U")

        _cargar(db, doc(1, [linea(None, "PCEJ4-8U PC Ejemplo")]))

        assert lineas(engine)[(1, 1)]["item_id"] == 502

    def test_an_ambiguous_prefix_is_unresolved(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            item(conn, 604, "CTEJ-1200")
            item(conn, 605, "ctej-1200 ")

        _cargar(db, doc(1, [linea(None, "CTEJ-1200 Cartucho Ejemplo")]))

        assert lineas(engine)[(1, 1)]["item_id"] is None

    def test_the_prefix_never_applies_to_a_line_with_a_code(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 502, "PCEJ4-8U")

        _cargar(db, doc(1, [linea("7790000099999", "PCEJ4-8U PC Ejemplo")]))

        assert lineas(engine)[(1, 1)]["item_id"] is None


class TestMapeo:
    def test_a_remembered_mapping_resolves_the_next_upload_first(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 501, "7790000000017")
            producto(conn, 777, "7790000000777")
        _sql(engine, "INSERT INTO ventas_fuera_codigo_mapeos (clave, item_id) VALUES ('c:7790000000017', 777)")
        _sql(engine, "INSERT INTO ventas_fuera_codigo_mapeos (clave, item_id) VALUES ('a:ENVIO EJEMPLO', 501)")

        _cargar(db, doc(1, [linea(" 7790000000017", "MONITOR"), linea(None, " envio ejemplo ")]))

        filas = lineas(engine)
        assert [(filas[(1, r)]["item_id"], filas[(1, r)]["item_origen"]) for r in (1, 2)] == [
            (777, "mapeo"),
            (501, "mapeo"),
        ]


class TestFunciones:
    def test_clave_de_mapeo(self) -> None:
        assert clave_mapeo(" 77900ab ", "x") == "c:77900AB"
        assert clave_mapeo(None, "  Envio Ejemplo ") == "a:ENVIO EJEMPLO"
        assert clave_mapeo("   ", "Envio") == "a:ENVIO"

    def test_primer_token(self) -> None:
        assert primer_token("  PCEJ4-8U  PC") == "PCEJ4-8U"
        assert primer_token("   ") is None

    def test_resolver_reports_none_for_unresolved(self, engine: Engine, db: Session) -> None:
        with engine.begin() as conn:
            producto(conn, 501, "7790000000017")

        resueltas = resolver(db, [("7790000000017", "MONITOR"), (None, "Flete (Manual)")])

        assert resueltas[("7790000000017", "MONITOR")].item_id == 501
        assert resueltas[(None, "Flete (Manual)")] is None
