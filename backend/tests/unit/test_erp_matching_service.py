"""
Tests unitarios de `erp_matching_service` (COMPRAS-3.5).

Cubre:
  - `validar_catalogo_populado`: raise si vacío, pasa si tiene filas.
  - `match_forward`: encuentra ct vigente y setea ct_transaction_id en pedido.
  - `match_forward`: no matchea si pedido sin numero_factura / ya matcheado /
    proveedor sin supp_id / empresa no mapeada.
  - `match_backward`: asocia múltiples cts simultáneas.
  - `match_backward`: respeta aislamiento por (comp_id, bra_id) — no cruza
    empresas.
  - `match_backward`: no pisa pedidos ya matcheados.

Las pruebas usan el engine SQLite del `conftest.py` compartido. La vista
`v_facturas_compra_vigentes` se crea ad-hoc al inicio de la suite porque
las migraciones Alembic NO corren bajo SQLite de tests.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.commercial_transaction import CommercialTransaction
from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tb_sale_document import SaleDocument
from app.services.erp_matching_service import (
    match_backward,
    match_forward,
    validar_catalogo_populado,
)


# ──────────────────────────────────────────────────────────────────────────
# Vista SQLite (las migrations Alembic no corren en tests — la creamos a mano)
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
    """Crea la vista `v_facturas_compra_vigentes` en cada tx de test.

    Se dropea y recrea por test para garantizar aislamiento ante cambios
    de schema. `CREATE VIEW IF NOT EXISTS` sería suficiente pero el rollback
    del fixture `db` la tira igual.
    """
    db.execute(text("DROP VIEW IF EXISTS v_facturas_compra_vigentes"))
    db.execute(text(_VIEW_SQL))


# ──────────────────────────────────────────────────────────────────────────
# Fixtures de datos
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa ERP Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def empresa2(db) -> Empresa:
    emp = Empresa(id=2, nombre="Empresa 2 ERP Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=18,
        nombre="JUKEBOX",
        supp_id=18,
        comp_id=1,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def proveedor_sin_supp(db) -> Proveedor:
    prov = Proveedor(
        id=99,
        nombre="Proveedor Manual sin supp_id",
        supp_id=None,
        activo=True,
        origen=OrigenProveedor.MANUAL.value,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def sd_factura(db) -> SaleDocument:
    """sd_id=101 — FACTURA de compra."""
    sd = SaleDocument(
        sd_id=101,
        sd_desc="Factura de compra",
        sd_ispurchase=True,
        sd_isinbalance=True,
        sd_istaxable=True,
        sd_plusorminus=1,
        hacc_group=10001,
    )
    db.add(sd)
    db.flush()
    return sd


@pytest.fixture
def sd_anulacion(db) -> SaleDocument:
    """sd_id=151 — ANULACION de factura."""
    sd = SaleDocument(
        sd_id=151,
        sd_desc="Anulación factura compra",
        sd_ispurchase=True,
        sd_isannulment=True,
        sd_plusorminus=-1,
        hacc_group=10001,
    )
    db.add(sd)
    db.flush()
    return sd


@pytest.fixture
def sd_contraparte(db) -> SaleDocument:
    """sd_id=161 — CONTRAPARTE de factura (sd_id mayor, plusorminus invertido)."""
    sd = SaleDocument(
        sd_id=161,
        sd_desc="Contraparte factura compra",
        sd_ispurchase=True,
        sd_isinbalance=True,
        sd_istaxable=True,
        sd_plusorminus=-1,
        hacc_group=10001,
    )
    db.add(sd)
    db.flush()
    return sd


def _crear_pedido(
    db,
    *,
    empresa_id: int,
    proveedor_id: int,
    numero: str,
    numero_factura: str | None,
    creado_por_id: int,
    monto: Decimal = Decimal("1000.00"),
    ct_transaction_id: int | None = None,
) -> PedidoCompra:
    pedido = PedidoCompra(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda="ARS",
        monto=monto,
        numero_factura=numero_factura,
        ct_transaction_id=ct_transaction_id,
        estado="aprobado",
        creado_por_id=creado_por_id,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _crear_ct(
    db,
    *,
    ct_transaction: int,
    comp_id: int,
    bra_id: int,
    supp_id: int,
    ct_docnumber: str,
    sd_id: int,
    ct_total: Decimal = Decimal("1000.00"),
) -> CommercialTransaction:
    ct = CommercialTransaction(
        ct_transaction=ct_transaction,
        comp_id=comp_id,
        bra_id=bra_id,
        supp_id=supp_id,
        ct_docNumber=ct_docnumber,
        sd_id=sd_id,
        ct_total=ct_total,
        ct_date=datetime(2026, 4, 1, 10, 0, 0),
        ct_isCancelled=False,
    )
    db.add(ct)
    db.flush()
    return ct


# ──────────────────────────────────────────────────────────────────────────
# Tests: validar_catalogo_populado
# ──────────────────────────────────────────────────────────────────────────


class TestValidarCatalogoPopulado:
    def test_catalogo_vacio_raise(self, db):
        with pytest.raises(RuntimeError, match="tb_sale_document está vacío"):
            validar_catalogo_populado(db)

    def test_catalogo_con_filas_ok(self, db, sd_factura):
        # no debe levantar
        validar_catalogo_populado(db)


# ──────────────────────────────────────────────────────────────────────────
# Tests: match_forward
# ──────────────────────────────────────────────────────────────────────────


class TestMatchForward:
    def test_matchea_ct_vigente_y_setea_pedido(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-00001",
            numero_factura="00400000",
            creado_por_id=active_user.id,
        )
        _crear_ct(
            db,
            ct_transaction=900001,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="00400000",
            sd_id=sd_factura.sd_id,
        )

        ct_id = match_forward(db, pedido_compra_id=pedido.id)

        assert ct_id == 900001
        db.refresh(pedido)
        assert pedido.ct_transaction_id == 900001

        # Evento registrado
        evento = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
                CompraEvento.tipo == "matcheado_con_erp",
            )
            .first()
        )
        assert evento is not None
        assert evento.payload["ct_transaction"] == 900001
        assert evento.payload["modo"] == "forward"

    def test_sin_numero_factura_no_matchea(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-00002",
            numero_factura=None,
            creado_por_id=active_user.id,
        )

        result = match_forward(db, pedido_compra_id=pedido.id)

        assert result is None
        db.refresh(pedido)
        assert pedido.ct_transaction_id is None

    def test_ya_matcheado_no_pisa(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-00003",
            numero_factura="00400003",
            creado_por_id=active_user.id,
            ct_transaction_id=555555,
        )
        _crear_ct(
            db,
            ct_transaction=900003,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="00400003",
            sd_id=sd_factura.sd_id,
        )

        result = match_forward(db, pedido_compra_id=pedido.id)

        assert result is None
        db.refresh(pedido)
        assert pedido.ct_transaction_id == 555555  # intocado

    def test_proveedor_sin_supp_id_no_matchea(self, db, empresa, proveedor_sin_supp, sd_factura, active_user):
        pedido = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor_sin_supp.id,
            numero="P-01-2026-00004",
            numero_factura="00400004",
            creado_por_id=active_user.id,
        )

        result = match_forward(db, pedido_compra_id=pedido.id)

        assert result is None

    def test_empresa_no_mapeada_no_matchea(self, db, proveedor, sd_factura, active_user):
        # empresa_id=999 no está en EMPRESA_A_COMP_BRA_MAP
        emp_no_map = Empresa(id=999, nombre="Emp no mapeada", activo=True, orden=0)
        db.add(emp_no_map)
        db.flush()

        pedido = _crear_pedido(
            db,
            empresa_id=999,
            proveedor_id=proveedor.id,
            numero="P-01-2026-00005",
            numero_factura="00400005",
            creado_por_id=active_user.id,
        )

        result = match_forward(db, pedido_compra_id=pedido.id)

        assert result is None

    def test_pedido_inexistente_raise(self, db):
        with pytest.raises(ValueError, match="no existe"):
            match_forward(db, pedido_compra_id=999999)

    def test_factura_anulada_no_matchea(self, db, empresa, proveedor, sd_factura, sd_anulacion, active_user):
        """Escenario contable: factura sd=101 + anulación sd=151 con mismo
        ct_docnumber — la vista excluye ambas → forward no encuentra."""
        pedido = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-00006",
            numero_factura="00389000",
            creado_por_id=active_user.id,
        )
        _crear_ct(
            db,
            ct_transaction=900006,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="00389000",
            sd_id=sd_factura.sd_id,
        )
        _crear_ct(
            db,
            ct_transaction=900007,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="00389000",
            sd_id=sd_anulacion.sd_id,
        )

        result = match_forward(db, pedido_compra_id=pedido.id)

        assert result is None  # vista filtra anuladas
        db.refresh(pedido)
        assert pedido.ct_transaction_id is None


# ──────────────────────────────────────────────────────────────────────────
# Tests: match_backward
# ──────────────────────────────────────────────────────────────────────────


class TestMatchBackward:
    def test_catalogo_vacio_raise(self, db):
        with pytest.raises(RuntimeError):
            match_backward(db, cts_synced=[123])

    def test_lista_vacia_retorna_cero(self, db, sd_factura):
        resumen = match_backward(db, cts_synced=[])
        assert resumen == {
            "cts_procesadas": 0,
            "pedidos_asociados": 0,
            "errores": 0,
        }

    def test_asocia_multiples_cts(self, db, empresa, proveedor, sd_factura, active_user):
        # 2 pedidos esperando factura
        p1 = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-01001",
            numero_factura="BACK-001",
            creado_por_id=active_user.id,
        )
        p2 = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-01002",
            numero_factura="BACK-002",
            creado_por_id=active_user.id,
        )

        # 2 ct recién sincronizadas
        _crear_ct(
            db,
            ct_transaction=910001,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="BACK-001",
            sd_id=sd_factura.sd_id,
        )
        _crear_ct(
            db,
            ct_transaction=910002,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="BACK-002",
            sd_id=sd_factura.sd_id,
        )

        resumen = match_backward(db, cts_synced=[910001, 910002])

        assert resumen["cts_procesadas"] == 2
        assert resumen["pedidos_asociados"] == 2
        assert resumen["errores"] == 0

        db.refresh(p1)
        db.refresh(p2)
        assert p1.ct_transaction_id == 910001
        assert p2.ct_transaction_id == 910002

    def test_no_pisa_pedido_ya_matcheado(self, db, empresa, proveedor, sd_factura, active_user):
        p = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-01010",
            numero_factura="BACK-010",
            creado_por_id=active_user.id,
            ct_transaction_id=777777,
        )
        _crear_ct(
            db,
            ct_transaction=910010,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="BACK-010",
            sd_id=sd_factura.sd_id,
        )

        resumen = match_backward(db, cts_synced=[910010])

        assert resumen["pedidos_asociados"] == 0
        db.refresh(p)
        assert p.ct_transaction_id == 777777

    def test_aislamiento_empresa_no_cruza(self, db, empresa, empresa2, proveedor, sd_factura, active_user):
        """Pedido de empresa=1 NO debe matchear con ct de (comp=1, bra=45)
        que corresponde a empresa=2."""
        p = _crear_pedido(
            db,
            empresa_id=1,  # → (comp=1, bra=1)
            proveedor_id=proveedor.id,
            numero="P-01-2026-01020",
            numero_factura="BACK-020",
            creado_por_id=active_user.id,
        )
        _crear_ct(
            db,
            ct_transaction=910020,
            comp_id=1,
            bra_id=45,  # ← empresa=2, no 1
            supp_id=proveedor.supp_id,
            ct_docnumber="BACK-020",
            sd_id=sd_factura.sd_id,
        )

        resumen = match_backward(db, cts_synced=[910020])

        assert resumen["pedidos_asociados"] == 0
        db.refresh(p)
        assert p.ct_transaction_id is None

    def test_ct_no_vigente_se_ignora(self, db, empresa, proveedor, sd_anulacion, sd_factura, active_user):
        """Una ct que sea anulación NO aparece en la vista → no debe producir
        match aunque coincida doc_number con un pedido."""
        p = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-01030",
            numero_factura="BACK-030",
            creado_por_id=active_user.id,
        )
        # solo la anulación, sin factura base
        _crear_ct(
            db,
            ct_transaction=910030,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="BACK-030",
            sd_id=sd_anulacion.sd_id,
        )

        resumen = match_backward(db, cts_synced=[910030])

        assert resumen["pedidos_asociados"] == 0
        db.refresh(p)
        assert p.ct_transaction_id is None

    def test_registra_evento_matcheado_con_erp(self, db, empresa, proveedor, sd_factura, active_user):
        p = _crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="P-01-2026-01040",
            numero_factura="BACK-040",
            creado_por_id=active_user.id,
        )
        _crear_ct(
            db,
            ct_transaction=910040,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docnumber="BACK-040",
            sd_id=sd_factura.sd_id,
        )

        match_backward(db, cts_synced=[910040])

        evento = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == p.id,
                CompraEvento.tipo == "matcheado_con_erp",
            )
            .first()
        )
        assert evento is not None
        assert evento.payload["modo"] == "backward"
        assert evento.payload["ct_transaction"] == 910040
