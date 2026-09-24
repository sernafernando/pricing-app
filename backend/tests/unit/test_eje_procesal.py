"""PR1 — eje_procesal mapper + visibility chip batches + OP P-numbers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.compra_adjunto import CompraAdjunto
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.oc_match_job import OcMatchJob
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.usuario import Usuario
from app.services import pedidos_service


@pytest.mark.parametrize(
    ("tipo", "estado", "faltantes_resuelto_en", "expected"),
    [
        ("servicio", "aprobado", None, "n_a_servicio"),
        ("servicio", "pagado", None, "n_a_servicio"),
        ("mercaderia", "pagado", None, "por_recibir"),
        ("mercaderia", "en_cuenta_corriente", None, "por_recibir"),
        ("mercaderia", "recibido", None, "recibido"),
        ("mercaderia", "con_faltantes", None, "faltantes_sin_res"),
        ("mercaderia", "con_faltantes", datetime(2026, 1, 1, tzinfo=timezone.utc), "faltantes_con_res"),
        ("mercaderia", "controlado", None, "controlado"),
        ("mercaderia", "aprobado", None, None),
        ("mercaderia", "borrador", None, None),
    ],
)
def test_calcular_eje_procesal_mapping(tipo, estado, faltantes_resuelto_en, expected) -> None:
    assert pedidos_service.calcular_eje_procesal(tipo, estado, faltantes_resuelto_en) == expected


def test_aprobado_is_not_procesal_pendiente() -> None:
    """Financial aprobado stays off the procesal axis (badge is not renamed Pendiente)."""
    assert pedidos_service.calcular_eje_procesal("mercaderia", "aprobado", None) is None


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Eje", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Proveedor Eje",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=200,
    )
    db.add(prov)
    db.flush()
    return prov


def _pedido(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user: Usuario,
    *,
    numero: str,
    oc_poh_id: int | None = None,
) -> PedidoCompra:
    pedido = PedidoCompra(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000.00"),
        estado="pagado",
        creado_por_id=user.id,
        oc_poh_id=oc_poh_id,
    )
    db.add(pedido)
    db.flush()
    return pedido


class TestChipsVisibilidadBatch:
    def test_factura_and_latest_match(self, db, empresa, proveedor, active_user) -> None:
        p1 = _pedido(db, empresa, proveedor, active_user, numero="P-01-2026-00001", oc_poh_id=11)
        p2 = _pedido(db, empresa, proveedor, active_user, numero="P-01-2026-00002")
        db.add(
            PedidoFacturaDocumento(
                pedido_id=p1.id,
                numero="FA-1",
                created_by_id=active_user.id,
                cargada=True,
            )
        )
        adj_old = CompraAdjunto(
            entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
            entidad_id=p1.id,
            nombre_archivo="old.pdf",
            path_archivo=f"pedido_compra/{p1.id}/old.pdf",
            mime_type="application/pdf",
        )
        adj_new = CompraAdjunto(
            entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
            entidad_id=p1.id,
            nombre_archivo="new.pdf",
            path_archivo=f"pedido_compra/{p1.id}/new.pdf",
            mime_type="application/pdf",
        )
        db.add_all([adj_old, adj_new])
        db.flush()
        db.add(
            OcMatchJob(
                pedido_id=p1.id,
                attachment_id=adj_old.id,
                status=OcMatchJob.STATUS_QUEUED,
            )
        )
        db.flush()
        db.add(
            OcMatchJob(
                pedido_id=p1.id,
                attachment_id=adj_new.id,
                status=OcMatchJob.STATUS_DONE,
            )
        )
        db.flush()

        chips = pedidos_service.chips_visibilidad_batch(db, [p1.id, p2.id])
        assert chips[p1.id]["factura_cargada"] is True
        assert chips[p1.id]["tiene_numero_factura"] is True
        assert chips[p1.id]["oc_match_status"] == OcMatchJob.STATUS_DONE
        assert chips[p2.id]["factura_cargada"] is False
        assert chips[p2.id]["tiene_numero_factura"] is False
        assert chips[p2.id]["oc_match_status"] is None


class TestPedidosNumerosPorOp:
    def test_two_p_numbers_and_a_cuenta_empty(self, db, empresa, proveedor, active_user) -> None:
        p1 = _pedido(db, empresa, proveedor, active_user, numero="P-01-2026-00001")
        p2 = _pedido(db, empresa, proveedor, active_user, numero="P-01-2026-00002")
        op_linked = OrdenPago(
            numero="OP-01-2026-00001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("2000.00"),
            modo_imputacion="especifica",
            estado="pendiente",
            creado_por_id=active_user.id,
        )
        op_cuenta = OrdenPago(
            numero="OP-01-2026-00002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("500.00"),
            modo_imputacion="a_cuenta",
            estado="pendiente",
            creado_por_id=active_user.id,
        )
        db.add_all([op_linked, op_cuenta])
        db.flush()
        db.add_all(
            [
                Imputacion(
                    origen_tipo="orden_pago",
                    origen_id=op_linked.id,
                    destino_tipo="pedido_compra",
                    destino_id=p1.id,
                    monto_imputado=Decimal("1000.00"),
                    moneda_imputada="ARS",
                    monto_origen=Decimal("1000.00"),
                    moneda_origen="ARS",
                    proveedor_id=proveedor.id,
                    es_reversal=False,
                    creado_por_id=active_user.id,
                ),
                Imputacion(
                    origen_tipo="orden_pago",
                    origen_id=op_linked.id,
                    destino_tipo="pedido_compra",
                    destino_id=p2.id,
                    monto_imputado=Decimal("1000.00"),
                    moneda_imputada="ARS",
                    monto_origen=Decimal("1000.00"),
                    moneda_origen="ARS",
                    proveedor_id=proveedor.id,
                    es_reversal=False,
                    creado_por_id=active_user.id,
                ),
            ]
        )
        db.flush()

        nums = pedidos_service.pedidos_numeros_por_op_batch(db, [op_linked.id, op_cuenta.id])
        assert nums[op_linked.id] == ["P-01-2026-00001", "P-01-2026-00002"]
        assert nums[op_cuenta.id] == []
