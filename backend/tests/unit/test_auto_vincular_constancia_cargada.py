"""Auto-link ERP CT by pedido_factura_documentos.numero after cargada window."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.commercial_transaction import CommercialTransaction
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_factura import PedidoCompraFactura, cts_for_pedido
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tb_sale_document import SaleDocument
from app.services import compras_alertas_service, erp_matching_service


_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_facturas_compra_vigentes AS
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
    'FACTURA' AS clasificacion
FROM tb_commercial_transactions ct
JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
WHERE sd.sd_ispurchase = 1
  AND sd.sd_isannulment = 0
  AND sd.sd_ispackinglist = 0
  AND sd.sd_isquotation = 0
  AND ct.supp_id IS NOT NULL
  AND ct.ct_docnumber IS NOT NULL;
"""


@pytest.fixture(autouse=True)
def _crear_vista(db):
    db.execute(text("DROP VIEW IF EXISTS v_facturas_compra_vigentes"))
    db.execute(text(_VIEW_SQL))


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=1, nombre="EmpAutoVinc", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=1,
        nombre="ProvAutoVinc",
        origen=OrigenProveedor.ERP,
        activo=True,
        supp_id=200,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def sd_factura(db) -> SaleDocument:
    sd = SaleDocument(
        sd_id=101,
        sd_desc="Factura",
        sd_ispurchase=True,
        sd_isannulment=False,
        sd_ispackinglist=False,
        sd_isquotation=False,
        hacc_group=1,
        sd_plusorminus=1,
    )
    db.add(sd)
    db.flush()
    return sd


def _pedido(db, empresa, proveedor, user_id: int, *, numero: str) -> PedidoCompra:
    p = PedidoCompra(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        estado="aprobado",
        creado_por_id=user_id,
    )
    db.add(p)
    db.flush()
    return p


def test_auto_vincular_links_unique_ct(db, empresa, proveedor, sd_factura, active_user):
    pedido = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-1")
    doc = PedidoFacturaDocumento(
        pedido_id=pedido.id,
        numero="FA-9001",
        created_by_id=active_user.id,
        cargada=True,
    )
    db.add(doc)
    db.add(
        CommercialTransaction(
            ct_transaction=9001,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docNumber="FA-9001",
            sd_id=sd_factura.sd_id,
            ct_total=Decimal("1000"),
            curr_id_transaction=1,
            ct_date=datetime(2026, 4, 1, 12, 0, 0),
            ct_isCancelled=False,
        )
    )
    db.flush()

    ct = erp_matching_service.auto_vincular_por_constancia_cargada(db, doc)
    assert ct == 9001
    db.refresh(pedido)
    assert pedido.ct_transaction_id == 9001
    assert cts_for_pedido(db, pedido) == [(9001, date(2026, 4, 1))]
    db.refresh(doc)
    assert doc.auto_vinculo_estado == erp_matching_service.AUTO_VINCULO_OK


def test_auto_vincular_persists_sin_match(db, empresa, proveedor, active_user):
    pedido = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-NONE")
    doc = PedidoFacturaDocumento(
        pedido_id=pedido.id,
        numero="FA-MISSING",
        created_by_id=active_user.id,
        cargada=True,
    )
    db.add(doc)
    db.flush()

    assert erp_matching_service.auto_vincular_por_constancia_cargada(db, doc) is None
    db.refresh(doc)
    assert doc.auto_vinculo_estado == erp_matching_service.AUTO_VINCULO_SIN_MATCH
    assert doc.auto_vinculo_intentado_at is not None


def test_auto_vincular_persists_ambiguo(db, empresa, proveedor, sd_factura, active_user):
    pedido = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-AMB")
    doc = PedidoFacturaDocumento(
        pedido_id=pedido.id,
        numero="FA-DUP",
        created_by_id=active_user.id,
        cargada=True,
    )
    db.add(doc)
    for ct_id in (9101, 9102):
        db.add(
            CommercialTransaction(
                ct_transaction=ct_id,
                comp_id=1,
                bra_id=1,
                supp_id=proveedor.supp_id,
                ct_docNumber="FA-DUP",
                sd_id=sd_factura.sd_id,
                ct_total=Decimal("100"),
                curr_id_transaction=1,
                ct_date=datetime(2026, 4, 1, 12, 0, 0),
                ct_isCancelled=False,
            )
        )
    db.flush()

    assert erp_matching_service.auto_vincular_por_constancia_cargada(db, doc) is None
    db.refresh(doc)
    assert doc.auto_vinculo_estado == erp_matching_service.AUTO_VINCULO_AMBIGUO


def test_auto_vincular_shared_numero_across_pedidos(db, empresa, proveedor, sd_factura, active_user):
    a = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-A")
    b = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-B")
    ventana_vencida = datetime(2026, 4, 2, 11, 0, tzinfo=timezone.utc)
    for p in (a, b):
        db.add(
            PedidoFacturaDocumento(
                pedido_id=p.id,
                numero="FA-SHARED",
                created_by_id=active_user.id,
                cargada=True,
                alerta_pendiente_hasta=ventana_vencida,
            )
        )
    db.add(
        CommercialTransaction(
            ct_transaction=9002,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docNumber="FA-SHARED",
            sd_id=sd_factura.sd_id,
            ct_total=Decimal("500"),
            curr_id_transaction=1,
            ct_date=datetime(2026, 4, 2, 12, 0, 0),
            ct_isCancelled=False,
        )
    )
    db.flush()
    doc_a = db.query(PedidoFacturaDocumento).filter_by(pedido_id=a.id).one()

    erp_matching_service.auto_vincular_por_constancia_cargada(db, doc_a)
    db.refresh(a)
    db.refresh(b)
    assert a.ct_transaction_id == 9002
    assert b.ct_transaction_id == 9002
    assert db.query(PedidoCompraFactura).filter_by(ct_transaction_id=9002).count() == 2


def test_auto_vincular_skips_sister_still_in_regret_window(
    db, empresa, proveedor, sd_factura, active_user
):
    a = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-WIN-A")
    b = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-WIN-B")
    ahora = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    doc_a = PedidoFacturaDocumento(
        pedido_id=a.id,
        numero="FA-WIN",
        created_by_id=active_user.id,
        cargada=True,
        alerta_pendiente_hasta=ahora - timedelta(minutes=1),
    )
    doc_b = PedidoFacturaDocumento(
        pedido_id=b.id,
        numero="FA-WIN",
        created_by_id=active_user.id,
        cargada=True,
        alerta_pendiente_hasta=ahora + timedelta(minutes=4),
    )
    db.add_all([doc_a, doc_b])
    db.add(
        CommercialTransaction(
            ct_transaction=9004,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docNumber="FA-WIN",
            sd_id=sd_factura.sd_id,
            ct_total=Decimal("100"),
            curr_id_transaction=1,
            ct_date=datetime(2026, 4, 4, 12, 0, 0),
            ct_isCancelled=False,
        )
    )
    db.flush()

    erp_matching_service.auto_vincular_por_constancia_cargada(db, doc_a, ahora=ahora)
    db.refresh(a)
    db.refresh(b)
    assert a.ct_transaction_id == 9004
    assert b.ct_transaction_id is None


def test_disparar_alertas_also_auto_links(db, empresa, proveedor, sd_factura, active_user):
    pedido = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-FIRE")
    ahora = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    doc = PedidoFacturaDocumento(
        pedido_id=pedido.id,
        numero="FA-FIRE",
        created_by_id=active_user.id,
        cargada=True,
        alerta_pendiente_hasta=ahora - timedelta(minutes=1),
        alerta_disparada_at=None,
    )
    db.add(doc)
    db.add(
        CommercialTransaction(
            ct_transaction=9003,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docNumber="FA-FIRE",
            sd_id=sd_factura.sd_id,
            ct_total=Decimal("100"),
            curr_id_transaction=1,
            ct_date=datetime(2026, 4, 3, 12, 0, 0),
            ct_isCancelled=False,
        )
    )
    db.flush()

    with pytest.MonkeyPatch.context() as mp:
        # Recipients may be empty in unit DB; still fire + link.
        mp.setattr(
            compras_alertas_service,
            "notificar_factura_cargada",
            lambda *a, **k: [],
        )
        mp.setattr(
            compras_alertas_service,
            "_sync_espejo_antes_autolink",
            lambda *_a, **_k: None,
        )
        fired = compras_alertas_service.disparar_alertas_factura_pendientes(db, ahora=ahora)
    assert fired == 1
    db.refresh(pedido)
    assert pedido.ct_transaction_id == 9003
    db.refresh(doc)
    assert doc.alerta_disparada_at is not None


def test_disparar_alertas_marks_fired_when_auto_vincular_raises(
    db, empresa, proveedor, sd_factura, active_user
):
    pedido = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-FAIL")
    ahora = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    doc = PedidoFacturaDocumento(
        pedido_id=pedido.id,
        numero="FA-FAIL",
        created_by_id=active_user.id,
        cargada=True,
        alerta_pendiente_hasta=ahora - timedelta(minutes=1),
        alerta_disparada_at=None,
    )
    db.add(doc)
    db.flush()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            compras_alertas_service,
            "notificar_factura_cargada",
            lambda *a, **k: [],
        )
        mp.setattr(
            compras_alertas_service,
            "_sync_espejo_antes_autolink",
            lambda *_a, **_k: None,
        )
        mp.setattr(
            erp_matching_service,
            "auto_vincular_por_constancia_cargada",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        fired = compras_alertas_service.disparar_alertas_factura_pendientes(db, ahora=ahora)
    assert fired == 1
    db.refresh(doc)
    assert doc.alerta_disparada_at is not None
    db.refresh(pedido)
    assert pedido.ct_transaction_id is None


def test_disparar_retries_sin_match_after_ct_appears(
    db, empresa, proveedor, sd_factura, active_user
):
    pedido = _pedido(db, empresa, proveedor, active_user.id, numero="P-AV-RETRY")
    ahora = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    doc = PedidoFacturaDocumento(
        pedido_id=pedido.id,
        numero="FA-RETRY",
        created_by_id=active_user.id,
        cargada=True,
        alerta_pendiente_hasta=ahora - timedelta(minutes=10),
        alerta_disparada_at=ahora - timedelta(minutes=5),
        auto_vinculo_estado=erp_matching_service.AUTO_VINCULO_SIN_MATCH,
        auto_vinculo_intentado_at=ahora - timedelta(minutes=5),
    )
    db.add(doc)
    db.add(
        CommercialTransaction(
            ct_transaction=9200,
            comp_id=1,
            bra_id=1,
            supp_id=proveedor.supp_id,
            ct_docNumber="FA-RETRY",
            sd_id=sd_factura.sd_id,
            ct_total=Decimal("100"),
            curr_id_transaction=1,
            ct_date=datetime(2026, 4, 5, 12, 0, 0),
            ct_isCancelled=False,
        )
    )
    db.flush()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            compras_alertas_service,
            "_sync_espejo_antes_autolink",
            lambda *_a, **_k: None,
        )
        fired = compras_alertas_service.disparar_alertas_factura_pendientes(db, ahora=ahora)
    assert fired == 0
    db.refresh(pedido)
    assert pedido.ct_transaction_id == 9200
    db.refresh(doc)
    assert doc.auto_vinculo_estado == erp_matching_service.AUTO_VINCULO_OK
