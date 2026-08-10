"""
T1.2 — Tests unitarios para el helper compartido `imputar_nc_a_pedido`.

Cubre:
  - Happy path: NC aprobada, pedido aprobado, misma moneda, monto ≤ saldo → retorna Imputacion.
  - Fails 403: nc.proveedor_id != pedido.proveedor_id.
  - Fails 409: nc.estado == 'aplicada'.
  - Fails 422: nc.estado == 'rechazada'.
  - Fails 422: nc.estado == 'pendiente'.
  - Fails 422: pedido.estado == 'cancelado'.
  - Fails 422: monto > nc.saldo_disponible.
  - Cross-moneda NC→pedido: convierte por la cadena NC → OP → pedido y graba
    las dos patas (origen en moneda NC, destino en moneda pedido).
  - Fails 422: cross-moneda NC↔OP sin TC resolvable (ni override ni op.tipo_cambio).
  - `tipo_cambio_override` por NC gana sobre `op_tipo_cambio`.
  - NC state transitions: monto == saldo_disponible → nc.estado = 'aplicada'.
  - monto < saldo_disponible → nc.estado = 'aplicada_parcial'.
  - nc.monto_ya_aplicado incrementado correctamente.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=20, nombre="EmpresaF7Helper", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=20,
        nombre="ProveedorF7",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=200,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def proveedor_otro(db) -> Proveedor:
    p = Proveedor(
        id=21,
        nombre="OtroProveedorF7",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=201,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_ars(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=20,
        numero="PC-20-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("20000"),
        tipo_cambio=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_usd(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=21,
        numero="PC-20-2026-00002",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("500"),
        tipo_cambio=Decimal("1400"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_cancelado(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=22,
        numero="PC-20-2026-00003",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        tipo_cambio=None,
        estado="cancelado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _make_nc(
    db,
    *,
    id: int,
    proveedor_id: int,
    empresa_id: int,
    estado: str,
    monto: Decimal,
    moneda: str = "ARS",
    creado_por_id: int,
) -> NotaCreditoLocal:
    nc = NotaCreditoLocal(
        id=id,
        numero=f"NC-20-2026-{id:05d}",
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda=moneda,
        monto=monto,
        fecha_emision=date(2026, 1, 10),
        motivo="Test helper",
        estado=estado,
        tipo="credito",
        creado_por_id=creado_por_id,
    )
    db.add(nc)
    db.flush()
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestImputarNcAPedidoHelper:
    """T1.2 — Tests para imputar_nc_a_pedido helper."""

    def test_happy_path_retorna_imputacion(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """NC aprobada, pedido aprobado, misma moneda, monto <= saldo → retorna Imputacion."""
        nc = _make_nc(
            db,
            id=200,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )

        imp = ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=None,
        )

        assert isinstance(imp, Imputacion)
        assert imp.origen_tipo == "nota_credito_local"
        assert imp.origen_id == nc.id
        assert imp.destino_tipo == "pedido_compra"
        assert imp.destino_id == pedido_ars.id
        assert imp.monto_imputado == Decimal("5000")

    def test_fails_403_proveedor_mismatch(
        self, db, empresa, proveedor, proveedor_otro, pedido_ars, active_user
    ) -> None:
        """nc.proveedor_id != pedido.proveedor_id → 403."""
        nc = _make_nc(
            db,
            id=201,
            proveedor_id=proveedor_otro.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )
        # pedido_ars belongs to proveedor, nc belongs to proveedor_otro

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
                op_moneda="ARS",
                op_tipo_cambio=None,
            )
        assert exc_info.value.status_code == 403

    def test_fails_409_nc_aplicada(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """nc.estado == 'aplicada' → 409."""
        nc = _make_nc(
            db,
            id=202,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aplicada",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
                op_moneda="ARS",
                op_tipo_cambio=None,
            )
        assert exc_info.value.status_code == 409

    def test_fails_422_nc_rechazada(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """nc.estado == 'rechazado' → 422."""
        nc = _make_nc(
            db,
            id=203,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="rechazado",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
                op_moneda="ARS",
                op_tipo_cambio=None,
            )
        assert exc_info.value.status_code == 422

    def test_fails_422_nc_pendiente(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """nc.estado == 'pendiente_aprobacion' → 422."""
        nc = _make_nc(
            db,
            id=204,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="pendiente_aprobacion",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
                op_moneda="ARS",
                op_tipo_cambio=None,
            )
        assert exc_info.value.status_code == 422

    def test_fails_422_pedido_cancelado(self, db, empresa, proveedor, pedido_cancelado, active_user) -> None:
        """pedido.estado == 'cancelado' → 422."""
        nc = _make_nc(
            db,
            id=205,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_cancelado,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
                op_moneda="ARS",
                op_tipo_cambio=None,
            )
        assert exc_info.value.status_code == 422

    def test_fails_422_monto_excede_saldo(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """monto > nc.saldo_disponible → 422."""
        nc = _make_nc(
            db,
            id=206,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("3000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("9999"),
                creado_por_id=active_user.id,
                op_moneda="ARS",
                op_tipo_cambio=None,
            )
        assert exc_info.value.status_code == 422

    def test_cross_moneda_nc_ars_pedido_usd_convierte_con_tc_de_la_op(
        self, db, empresa, proveedor, pedido_usd, active_user
    ) -> None:
        """NC ARS + OP ARS + pedido USD → imputa en USD con el TC de la OP.

        Invertido: antes la combinación se rechazaba con 422 ("cross-moneda no
        soportado en v1"). La NC es un medio de pago que vive en la moneda de la
        OP, así que viaja por la misma conversión OP→pedido que los items.
        """
        nc = _make_nc(
            db,
            id=207,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            moneda="ARS",
            creado_por_id=active_user.id,
        )

        imp = ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_usd,
            monto=Decimal("1400"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=Decimal("1400"),
        )

        # Pata destino: 1400 ARS / 1400 = 1,00 USD, denominada en la moneda del pedido.
        assert imp.monto_imputado == Decimal("1.00")
        assert imp.moneda_imputada == "USD"
        # Pata origen: lo que la NC entrega, en su propia moneda.
        assert imp.monto_origen == Decimal("1400")
        assert imp.moneda_origen == "ARS"
        # TC origen↔destino: ARS por USD real, apto para el TC ponderado del pedido.
        assert imp.tipo_cambio == Decimal("1400")

    def test_cross_moneda_nc_vs_op_sin_tc_resolvable_422(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """NC USD + OP ARS sin TC (ni override ni op.tipo_cambio) → 422 nombrando ambas monedas."""
        nc = _make_nc(
            db,
            id=211,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("100"),
            moneda="USD",
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("100"),
                creado_por_id=active_user.id,
                op_moneda="ARS",
                op_tipo_cambio=None,
            )
        assert exc_info.value.status_code == 422
        detalle = str(exc_info.value.detail)
        assert "USD" in detalle and "ARS" in detalle

    def test_cross_moneda_nc_usd_op_ars_pedido_ars_usa_tc_de_la_op(
        self, db, empresa, proveedor, pedido_ars, active_user
    ) -> None:
        """NC USD + OP ARS + pedido ARS → convierte con `op_tipo_cambio` cuando no hay override."""
        nc = _make_nc(
            db,
            id=212,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("100"),
            moneda="USD",
            creado_por_id=active_user.id,
        )

        imp = ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("10"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=Decimal("1400"),
        )

        assert imp.monto_imputado == Decimal("14000.00")
        assert imp.moneda_imputada == "ARS"
        assert imp.monto_origen == Decimal("10")
        assert imp.moneda_origen == "USD"
        assert imp.tipo_cambio == Decimal("1400")

    def test_cross_moneda_nc_usd_op_ars_honra_tipo_cambio_override(
        self, db, empresa, proveedor, pedido_ars, active_user
    ) -> None:
        """El `tipo_cambio_override` por NC gana sobre `op_tipo_cambio`.

        Este parámetro venía llegando del frontend desde el día uno pero Pydantic
        lo descartaba en la puerta: la columna "TC (opcional)" nunca hizo nada.
        """
        nc = _make_nc(
            db,
            id=213,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("100"),
            moneda="USD",
            creado_por_id=active_user.id,
        )

        imp = ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("10"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=Decimal("1400"),
            tipo_cambio_override=Decimal("1500"),
        )

        assert imp.monto_imputado == Decimal("15000.00")
        assert imp.tipo_cambio == Decimal("1500")
        assert imp.monto_origen == Decimal("10")
        assert imp.moneda_origen == "USD"

    def test_cross_moneda_nc_ars_op_usd_pedido_usd_espejo(
        self, db, empresa, proveedor, pedido_usd, active_user
    ) -> None:
        """Espejo: NC ARS + OP USD + pedido USD → la conversión ocurre en la pata NC→OP."""
        nc = _make_nc(
            db,
            id=214,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("28000"),
            moneda="ARS",
            creado_por_id=active_user.id,
        )

        imp = ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_usd,
            monto=Decimal("14000"),
            creado_por_id=active_user.id,
            op_moneda="USD",
            op_tipo_cambio=Decimal("1400"),
        )

        assert imp.monto_imputado == Decimal("10.00")
        assert imp.moneda_imputada == "USD"
        assert imp.monto_origen == Decimal("14000")
        assert imp.moneda_origen == "ARS"
        assert imp.tipo_cambio == Decimal("1400")

    def test_nc_y_pedido_misma_moneda_distinta_de_la_op_es_identidad(
        self, db, empresa, proveedor, pedido_usd, active_user
    ) -> None:
        """NC USD + OP ARS + pedido USD → identidad, aunque el override difiera del TC de la OP.

        Las dos patas de la cadena se cancelan: la fila vincula USD con USD, y la
        invariante de `crear_imputacion` exige que en same-moneda ambas patas sean
        el mismo número. El override sólo describe cómo se fondeó la NC contra la
        OP — igual que el TC caja↔OP en `ejecutar_pago`, que tampoco entra en la
        imputación. La varianza FX se deriva aparte (`calcular_varianza_tc`).
        """
        nc = _make_nc(
            db,
            id=215,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("100"),
            moneda="USD",
            creado_por_id=active_user.id,
        )

        imp = ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_usd,
            monto=Decimal("100"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=Decimal("1500"),
            tipo_cambio_override=Decimal("1520"),
        )

        assert imp.monto_imputado == Decimal("100")
        assert imp.moneda_imputada == "USD"
        assert imp.monto_origen == Decimal("100")
        assert imp.moneda_origen == "USD"
        assert imp.tipo_cambio is None

    def test_saldo_nc_baja_por_el_monto_NATIVO_en_cross_moneda(
        self, db, empresa, proveedor, pedido_usd, active_user
    ) -> None:
        """Una NC de 1.000 ARS gastada entera contra un pedido USD queda 'aplicada'.

        Éste es el bug que la etapa 1 (compras_038) existió para hacer arreglable:
        midiendo el consumo con la pata destino, la NC quedaba en
        'aplicada_parcial' con ~999,34 ARS de saldo fantasma, gastable de nuevo.
        """
        from app.services import ncs_locales_service

        nc = _make_nc(
            db,
            id=216,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("1000"),
            moneda="ARS",
            creado_por_id=active_user.id,
        )

        ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_usd,
            monto=Decimal("1000"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=Decimal("1500"),
        )
        db.flush()
        db.refresh(nc)

        assert ncs_locales_service.calcular_saldo_pendiente(db, nc.id) == Decimal("0")
        assert nc.estado == "aplicada"

    def test_nc_estado_cambia_a_aplicada_cuando_saldo_agotado(
        self, db, empresa, proveedor, pedido_ars, active_user
    ) -> None:
        """Monto == saldo_disponible → nc.estado debe ser 'aplicada' después."""
        nc = _make_nc(
            db,
            id=208,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=None,
        )
        db.flush()
        db.refresh(nc)
        # The state is managed by ncs_locales_service via imputaciones_service
        # After imputación completa (monto = saldo), estado should be 'aplicada'
        assert nc.estado == "aplicada"

    def test_nc_estado_parcial_cuando_saldo_no_agotado(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """Monto < saldo_disponible → nc.estado es 'aplicada_parcial'."""
        nc = _make_nc(
            db,
            id=209,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )

        ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("3000"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=None,
        )
        db.flush()
        db.refresh(nc)
        assert nc.estado == "aplicada_parcial"

    def test_saldo_disponible_reducido_tras_imputar(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """El saldo disponible de la NC se reduce en el monto imputado."""
        from app.services import ncs_locales_service

        nc = _make_nc(
            db,
            id=210,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )
        saldo_antes = ncs_locales_service.calcular_saldo_pendiente(db, nc.id)

        ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("4000"),
            creado_por_id=active_user.id,
            op_moneda="ARS",
            op_tipo_cambio=None,
        )
        db.flush()

        saldo_despues = ncs_locales_service.calcular_saldo_pendiente(db, nc.id)
        assert saldo_antes - saldo_despues == Decimal("4000")
