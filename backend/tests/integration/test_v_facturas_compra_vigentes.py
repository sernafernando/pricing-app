"""
Tests de integración de la vista `v_facturas_compra_vigentes` (COMPRAS-3.3).

Escenarios JUKEBOX canónicos (design §4.1 + RD3):

  1. **Factura sola vigente**: ct con sd_id=101 aparece en la vista.
  2. **Factura anulada**: factura (sd=101) + anulación (sd=151) con mismo
     (supp_id, ct_docnumber) → ambas se excluyen (anulada).
  3. **Factura con contraparte**: factura (sd=101) + contraparte (sd=161)
     con mismo (supp_id, ct_docnumber) + mismo hacc_group + sd_plusorminus
     invertido → aparece SOLO la de sd_id menor (convenio).
  4. **Factura cancelada** (`ct_isCancelled=true`): la vista NO la filtra
     explícitamente por el flag `ct_isCancelled` (D4 + RD3 no lo incluye),
     así que debería aparecer. Documentamos la conducta — si en producción
     aparecen cts cancelled causando ruido, hay que decidir si agregamos
     el filtro en migration compras_015.

Los tests crean la vista ad-hoc en SQLite (las migrations Alembic no
corren bajo SQLite). Mantener este SQL en sync con la migration real
(`backend/alembic/versions/compras_014_vista_facturas_vigentes.py`).

Los tests se ejecutan contra SQLite (conftest shared). Cuando el
proyecto agregue `pyproject.toml` con `[tool.pytest.ini_options]` se
puede registrar una mark `integration` para excluirlos en corridas
rápidas de unit tests.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.commercial_transaction import CommercialTransaction
from app.models.tb_sale_document import SaleDocument


# ──────────────────────────────────────────────────────────────────────────
# Definición de vista (duplicada del migration para poder correr en SQLite)
# ──────────────────────────────────────────────────────────────────────────

_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_facturas_compra_vigentes AS
WITH anuladas AS (
    SELECT DISTINCT ct.supp_id, ct.ct_docnumber
    FROM tb_commercial_transactions ct
    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
    WHERE sd.sd_isannulment = 1
      AND ct.supp_id IS NOT NULL
      AND ct.ct_docnumber IS NOT NULL
),
base AS (
    SELECT
        ct.ct_transaction,
        ct.comp_id,
        ct.bra_id,
        ct.supp_id,
        ct.ct_docnumber,
        ct.ct_total,
        ct.curr_id_transaction,
        ct.ct_date,
        ct.sd_id,
        sd.sd_desc,
        sd.hacc_group,
        sd.sd_plusorminus,
        CASE
            WHEN sd.sd_iscreditnote = 1 THEN 'NC'
            WHEN sd.sd_isdebitnote = 1 THEN 'ND'
            WHEN sd.sd_isreceipt = 1 THEN 'ORDEN_PAGO'
            WHEN sd.sd_isinbalance = 1 AND sd.sd_istaxable = 1 THEN 'FACTURA'
            ELSE 'OTRO'
        END AS clasificacion
    FROM tb_commercial_transactions ct
    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
    WHERE sd.sd_ispurchase = 1
      AND sd.sd_isannulment = 0
      AND sd.sd_ispackinglist = 0
      AND sd.sd_isquotation = 0
      AND COALESCE(ct.ct_kindof, '') <> 'X'
      AND ct.supp_id IS NOT NULL
      AND ct.ct_docnumber IS NOT NULL
),
contrapartes AS (
    SELECT b1.ct_transaction
    FROM base b1
    JOIN base b2
      ON b1.supp_id      = b2.supp_id
     AND b1.ct_docnumber = b2.ct_docnumber
     AND b1.comp_id      = b2.comp_id
     AND b1.bra_id       = b2.bra_id
     AND b1.hacc_group   = b2.hacc_group
     AND b1.sd_plusorminus = -b2.sd_plusorminus
     AND b1.ct_transaction <> b2.ct_transaction
    WHERE b1.sd_id > b2.sd_id
)
SELECT b.*
FROM base b
LEFT JOIN anuladas a
       ON a.supp_id = b.supp_id AND a.ct_docnumber = b.ct_docnumber
WHERE a.supp_id IS NULL
  AND b.ct_transaction NOT IN (SELECT ct_transaction FROM contrapartes);
"""


@pytest.fixture(autouse=True)
def _crear_vista(db):
    db.execute(text("DROP VIEW IF EXISTS v_facturas_compra_vigentes"))
    db.execute(text(_VIEW_SQL))


# ──────────────────────────────────────────────────────────────────────────
# Fixtures JUKEBOX
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def jukebox_sds(db):
    """Seed mínimo de sd_id necesarios para los escenarios JUKEBOX."""
    sds = [
        SaleDocument(
            sd_id=101,
            sd_desc="Factura compra",
            sd_ispurchase=True,
            sd_isinbalance=True,
            sd_istaxable=True,
            sd_plusorminus=1,
            hacc_group=10001,
        ),
        SaleDocument(
            sd_id=151,
            sd_desc="Anulación factura compra",
            sd_ispurchase=True,
            sd_isannulment=True,
            sd_plusorminus=-1,
            hacc_group=10001,
        ),
        SaleDocument(
            sd_id=161,
            sd_desc="Contraparte factura compra",
            sd_ispurchase=True,
            sd_isinbalance=True,
            sd_istaxable=True,
            sd_plusorminus=-1,
            hacc_group=10001,
        ),
    ]
    for sd in sds:
        db.add(sd)
    db.flush()
    return {sd.sd_id: sd for sd in sds}


def _crear_ct(
    db,
    *,
    ct_transaction: int,
    sd_id: int,
    ct_docnumber: str,
    supp_id: int = 18,
    comp_id: int = 1,
    bra_id: int = 1,
    ct_total: Decimal = Decimal("1000.00"),
    ct_iscancelled: bool = False,
) -> CommercialTransaction:
    ct = CommercialTransaction(
        ct_transaction=ct_transaction,
        comp_id=comp_id,
        bra_id=bra_id,
        supp_id=supp_id,
        ct_docNumber=ct_docnumber,
        sd_id=sd_id,
        ct_total=ct_total,
        ct_date=datetime(2026, 4, 1, 10, 0),
        ct_isCancelled=ct_iscancelled,
    )
    db.add(ct)
    db.flush()
    return ct


def _consultar_vista(db) -> list[dict]:
    return [dict(row._mapping) for row in db.execute(text("SELECT * FROM v_facturas_compra_vigentes")).all()]


# ──────────────────────────────────────────────────────────────────────────
# Escenarios
# ──────────────────────────────────────────────────────────────────────────


class TestEscenario1FacturaSolaVigente:
    """sd_id=101 aislada debe aparecer en la vista."""

    def test_factura_sola_aparece(self, db, jukebox_sds):
        _crear_ct(db, ct_transaction=700001, sd_id=101, ct_docnumber="TEST-001")

        filas = _consultar_vista(db)

        assert len(filas) == 1
        assert filas[0]["ct_transaction"] == 700001
        assert filas[0]["sd_id"] == 101
        assert filas[0]["ct_docnumber"] == "TEST-001"
        assert filas[0]["clasificacion"] == "FACTURA"


class TestEscenario2FacturaAnulada:
    """Factura + anulación con mismo (supp_id, ct_docnumber) → nada en vista."""

    def test_factura_anulada_no_aparece(self, db, jukebox_sds):
        # Base (sd=101) + anulación (sd=151), mismo docnumber
        _crear_ct(db, ct_transaction=700010, sd_id=101, ct_docnumber="TEST-002")
        _crear_ct(db, ct_transaction=700011, sd_id=151, ct_docnumber="TEST-002")

        filas = _consultar_vista(db)
        docs = {f["ct_docnumber"] for f in filas}

        assert "TEST-002" not in docs

    def test_otra_factura_no_afectada(self, db, jukebox_sds):
        """Anular TEST-002 NO debe ocultar TEST-003 del mismo proveedor."""
        _crear_ct(db, ct_transaction=700020, sd_id=101, ct_docnumber="TEST-002")
        _crear_ct(db, ct_transaction=700021, sd_id=151, ct_docnumber="TEST-002")
        _crear_ct(db, ct_transaction=700022, sd_id=101, ct_docnumber="TEST-003")

        filas = _consultar_vista(db)
        docs = {f["ct_docnumber"] for f in filas}

        assert "TEST-002" not in docs
        assert "TEST-003" in docs


class TestEscenario3FacturaConContraparte:
    """sd=101 + sd=161 (contraparte) con mismo docnumber + hacc_group +
    plusorminus invertido → aparece solo sd_id menor (101)."""

    def test_solo_base_aparece_no_contraparte(self, db, jukebox_sds):
        _crear_ct(db, ct_transaction=700030, sd_id=101, ct_docnumber="TEST-003")
        _crear_ct(db, ct_transaction=700031, sd_id=161, ct_docnumber="TEST-003")

        filas = _consultar_vista(db)
        sd_ids = {f["sd_id"] for f in filas if f["ct_docnumber"] == "TEST-003"}

        assert sd_ids == {101}

    def test_contraparte_con_distinto_docnumber_ambas_aparecen(self, db, jukebox_sds):
        """La heurística de contraparte requiere MISMO ct_docnumber —
        si los docnumber difieren, NO son contraparte y ambas vigentes."""
        _crear_ct(db, ct_transaction=700040, sd_id=101, ct_docnumber="TEST-004A")
        _crear_ct(db, ct_transaction=700041, sd_id=161, ct_docnumber="TEST-004B")

        filas = _consultar_vista(db)
        ct_ids = {f["ct_transaction"] for f in filas}

        assert 700040 in ct_ids
        # sd=161 con sd_plusorminus=-1 NO es anulación pero SÍ es documento
        # de compra válido → debe aparecer igual si no hay par invertido.
        assert 700041 in ct_ids


class TestEscenario4FacturaCancelada:
    """`ct_isCancelled=true` — la vista actual NO filtra por ese flag.

    La conducta actual: la ct aparece igual. Documentamos este
    comportamiento para que si en datos reales aparecen cts canceladas
    contaminando el listado, se decida agregar el filtro vía migration
    compras_015.
    """

    def test_ct_cancelled_aparece_en_vista(self, db, jukebox_sds):
        _crear_ct(
            db,
            ct_transaction=700050,
            sd_id=101,
            ct_docnumber="TEST-005",
            ct_iscancelled=True,
        )

        filas = _consultar_vista(db)

        # Conducta documentada: SÍ aparece (la vista no filtra ct_isCancelled).
        # Si cambia en compras_015, actualizar este test.
        assert any(f["ct_transaction"] == 700050 for f in filas)


class TestMultipleFacturasDistintas:
    def test_cinco_facturas_distintas_aparecen_todas(self, db, jukebox_sds):
        for i in range(5):
            _crear_ct(
                db,
                ct_transaction=700100 + i,
                sd_id=101,
                ct_docnumber=f"MULT-{i:03d}",
            )

        filas = _consultar_vista(db)
        docs = {f["ct_docnumber"] for f in filas if f["ct_docnumber"].startswith("MULT-")}

        assert len(docs) == 5
