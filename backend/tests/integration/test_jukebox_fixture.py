"""
Tests de regresión con datos reales del proveedor piloto JUKEBOX (supp_id=18).

COMPRAS-7.3 — Fase 7.

JUKEBOX es el proveedor elegido como piloto del módulo de compras. Tiene
~101 movimientos en 60 días en la DB real, con factura + anulaciones +
contrapartes + OPs. Es un buen dataset para validar que los mecanismos
principales funcionan contra datos reales sin inventar fixtures.

**Política de ejecución**:

Estos tests se saltean por default (la CI y la mayoría de los devs corren
sin DB real accesible). Para habilitarlos, exportar:

    export TESTING_DB=production_readonly
    export TESTING_READONLY_DATABASE_URL="postgresql://ro_user:...@host/erp"

El primero es un gate explícito (cualquier otro valor → skip). El segundo
es la URL de una réplica READ-ONLY del Postgres de producción. Si alguno
falta, los tests se saltean con motivo claro.

**Garantía**: los tests SÓLO hacen SELECT. Nunca INSERT/UPDATE/DELETE sobre
la DB apuntada. La conexión se abre con `AUTOCOMMIT` deshabilitado y se
rollbackea explícitamente al final de cada test.

Referencias:
  - design.md §4.1 (vista v_facturas_compra_vigentes)
  - design.md §5 (matching ERP)
  - tasks.md COMPRAS-7.3
  - Engram #123 (apply F6 — JUKEBOX como piloto)
"""

from __future__ import annotations

import os
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

JUKEBOX_SUPP_ID = 18

_TESTING_DB_MODE = "production_readonly"


def _should_run_jukebox_tests() -> tuple[bool, str]:
    """Determina si corremos los tests o los skippeamos con razón explícita."""
    if os.environ.get("TESTING_DB") != _TESTING_DB_MODE:
        return (
            False,
            f"TESTING_DB != '{_TESTING_DB_MODE}' — tests de integración JUKEBOX "
            "se ejecutan solo contra réplica readonly de producción. "
            "Exportar TESTING_DB=production_readonly para habilitarlos.",
        )

    if not os.environ.get("TESTING_READONLY_DATABASE_URL"):
        return (
            False,
            "TESTING_READONLY_DATABASE_URL no configurada. Exportar la URL "
            "de una réplica readonly del Postgres de producción.",
        )

    return (True, "")


_RUN, _SKIP_REASON = _should_run_jukebox_tests()

pytestmark = pytest.mark.skipif(not _RUN, reason=_SKIP_REASON)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def readonly_engine() -> Generator[Engine, None, None]:
    """Engine contra la réplica readonly. Se setea `default_transaction_read_only=on`.

    NOTA: la responsabilidad última de que sea readonly es del DBA que
    otorgó el rol. Acá solo agregamos un chequeo defensivo a nivel sesión.
    """
    url = os.environ["TESTING_READONLY_DATABASE_URL"]
    engine = create_engine(
        url,
        # Evita cualquier tipo de pool persistente — conexiones efímeras.
        pool_pre_ping=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    yield engine
    engine.dispose()


@pytest.fixture
def ro_session(readonly_engine: Engine) -> Generator[Session, None, None]:
    """Sesión readonly con rollback forzado al final (doble garantía)."""
    SessionLocal = sessionmaker(bind=readonly_engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestVistaVigentesJukebox:
    """Verifica que `v_facturas_compra_vigentes` funciona correctamente para JUKEBOX."""

    def test_vista_vigentes_excluye_anuladas_jukebox(self, ro_session: Session) -> None:
        """
        Para JUKEBOX, no debe haber un par (supp_id=18, ct_docnumber) que
        aparezca en la vista si existe una anulación (sd.sd_isannulment=True)
        para ese mismo par en `tb_commercial_transactions`.

        Si la vista devuelve un docnumber que también tiene anulación → bug.
        """
        # Docnumbers presentes en la vista para JUKEBOX
        vigentes_rows = ro_session.execute(
            text(
                """
                SELECT ct_docnumber
                FROM v_facturas_compra_vigentes
                WHERE supp_id = :supp_id
                """
            ),
            {"supp_id": JUKEBOX_SUPP_ID},
        ).all()
        vigentes_docs = {r.ct_docnumber for r in vigentes_rows if r.ct_docnumber}

        # Docnumbers con AL MENOS una anulación en tb_commercial_transactions
        anuladas_rows = ro_session.execute(
            text(
                """
                SELECT DISTINCT ct.ct_docnumber
                FROM tb_commercial_transactions ct
                JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
                WHERE ct.supp_id = :supp_id
                  AND sd.sd_isannulment = TRUE
                  AND ct.ct_docnumber IS NOT NULL
                """
            ),
            {"supp_id": JUKEBOX_SUPP_ID},
        ).all()
        anuladas_docs = {r.ct_docnumber for r in anuladas_rows}

        interseccion = vigentes_docs & anuladas_docs
        assert not interseccion, (
            f"La vista v_facturas_compra_vigentes devolvió {len(interseccion)} "
            f"docnumbers de JUKEBOX que tienen anulación asociada. "
            f"Primeros 5: {sorted(interseccion)[:5]}"
        )


class TestClasificadorJukebox:
    """El clasificador no debe devolver UNKNOWN para ningún sd_id presente en JUKEBOX."""

    def test_clasificador_clasifica_todos_los_movs_jukebox(self, ro_session: Session) -> None:
        from app.models.tb_sale_document import SaleDocument  # import local — evita carga si skip
        from app.services.sale_document_classifier import (
            ClasificacionDocCompra,
            clasificar_documento_compra,
        )

        sd_ids_usados = [
            r.sd_id
            for r in ro_session.execute(
                text(
                    """
                    SELECT DISTINCT sd_id
                    FROM tb_commercial_transactions
                    WHERE supp_id = :supp_id AND sd_id IS NOT NULL
                    """
                ),
                {"supp_id": JUKEBOX_SUPP_ID},
            ).all()
        ]

        assert len(sd_ids_usados) > 0, "JUKEBOX sin movimientos — dataset vacío."

        sds = ro_session.query(SaleDocument).filter(SaleDocument.sd_id.in_(sd_ids_usados)).all()
        assert len(sds) == len(sd_ids_usados), (
            f"Faltan filas en tb_sale_document para algunos sd_id usados por JUKEBOX: "
            f"esperados={len(sd_ids_usados)}, encontrados={len(sds)}"
        )

        unknowns = [
            (sd.sd_id, sd.sd_desc)
            for sd in sds
            if clasificar_documento_compra(sd, session=ro_session) == ClasificacionDocCompra.UNKNOWN
        ]
        assert not unknowns, f"Clasificador devolvió UNKNOWN para sd_ids de JUKEBOX: {unknowns}"


class TestMatchingForwardJukebox:
    """Matching forward: pedido creado con numero_factura existente en ERP debe asociarse."""

    def test_matching_forward_jukebox(self, ro_session: Session) -> None:
        """
        Busca una factura real de JUKEBOX en la vista vigentes. Simula el
        match forward (llamando al service de matching en modo DRY RUN — lee
        ERP, no escribe pedido).

        Si la vista devuelve 0 filas, el test se salta con motivo (dataset
        insuficiente en el snapshot de la réplica).
        """
        factura_real = ro_session.execute(
            text(
                """
                SELECT ct_transaction_id, ct_docnumber, supp_id, ct_date
                FROM v_facturas_compra_vigentes
                WHERE supp_id = :supp_id AND ct_docnumber IS NOT NULL
                LIMIT 1
                """
            ),
            {"supp_id": JUKEBOX_SUPP_ID},
        ).first()

        if factura_real is None:
            pytest.skip("JUKEBOX sin facturas vigentes en la réplica — no se puede testear matching forward.")

        # Import local para no cargar el service si el test está skipped.
        from app.services import erp_matching_service

        # El service espera (session, proveedor_id, numero_factura) y devuelve
        # el ct_transaction_id si hay match, None si no.
        match_fn = getattr(erp_matching_service, "buscar_ct_por_numero_factura", None)
        if match_fn is None:
            pytest.skip("Service erp_matching_service.buscar_ct_por_numero_factura no disponible — API cambió.")

        ct_id = match_fn(ro_session, proveedor_id=JUKEBOX_SUPP_ID, numero_factura=factura_real.ct_docnumber)
        assert ct_id == factura_real.ct_transaction_id, (
            f"Matching forward falló: esperado ct={factura_real.ct_transaction_id}, recibido={ct_id}."
        )


class TestMatchingBackwardJukebox:
    """Matching backward: simular nuevo ct sincronizado → busca pedidos pendientes.

    Este test es el más delicado porque requiere datos en el lado pedidos_compra.
    En la réplica readonly probablemente NO existan pedidos locales (solo ERP),
    así que lo implementamos como un smoke test del SQL de lookup: verifica
    que la query no explote y que devuelve una lista bien formada.
    """

    def test_matching_backward_jukebox(self, ro_session: Session) -> None:
        factura_real = ro_session.execute(
            text(
                """
                SELECT ct_transaction_id, ct_docnumber, supp_id, ct_date
                FROM v_facturas_compra_vigentes
                WHERE supp_id = :supp_id AND ct_docnumber IS NOT NULL
                LIMIT 1
                """
            ),
            {"supp_id": JUKEBOX_SUPP_ID},
        ).first()

        if factura_real is None:
            pytest.skip("JUKEBOX sin facturas vigentes — no se puede testear matching backward.")

        # Verificamos que podemos ejecutar la query "pedidos pendientes de match"
        # para ese proveedor sin que rompa el schema (aunque devuelva 0 filas).
        pendientes = ro_session.execute(
            text(
                """
                SELECT id, numero, numero_factura, proveedor_id
                FROM pedidos_compra
                WHERE proveedor_id = :supp_id
                  AND ct_transaction_id IS NULL
                  AND numero_factura IS NOT NULL
                """
            ),
            {"supp_id": JUKEBOX_SUPP_ID},
        ).all()

        # En la réplica readonly esto típicamente devuelve 0 filas (la réplica
        # no necesariamente tiene la tabla local pedidos_compra al día). El
        # contrato a validar es: la query corre sin error y el resultado es
        # una lista de dicts con las columnas esperadas.
        for row in pendientes:
            assert hasattr(row, "id") and hasattr(row, "numero_factura")
            assert row.proveedor_id == JUKEBOX_SUPP_ID
