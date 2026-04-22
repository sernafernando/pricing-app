"""
Tests de `cc_proveedor_service` (COMPRAS-2.4 — base).

Cubre:
  - `insertar_mov`: validaciones + resolución de TC + inserción.
  - `calcular_saldo_por_moneda`: debe/haber/ajuste + filtros.
  - `listar_movimientos` con filtros.

`aplicar_imputacion` (F4) y `reconciliar_diario` (F3, COMPRAS-3.6) no acá.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services.cc_proveedor_service import (
    calcular_saldo_por_moneda,
    insertar_mov,
    listar_movimientos,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa CC Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def empresa2(db) -> Empresa:
    emp = Empresa(id=2, nombre="Empresa 2 CC Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Proveedor CC Test",
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def tipo_cambio_usd(db) -> None:
    """Siembra TC USD para el rango de fechas de los tests."""
    tcs = [
        TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=900.0, venta=910.0),
        TipoCambio(fecha=date(2026, 3, 1), moneda="USD", compra=1000.0, venta=1020.0),
        TipoCambio(fecha=date(2026, 4, 15), moneda="USD", compra=1100.0, venta=1110.0),
    ]
    for tc in tcs:
        db.add(tc)
    db.flush()


# ──────────────────────────────────────────────────────────────────────────
# insertar_mov
# ──────────────────────────────────────────────────────────────────────────


class TestInsertarMov:
    def test_insertar_mov_debe_ars_tc_trivial(self, db, empresa, proveedor, active_user) -> None:
        mov = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("1500.00"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=42,
            descripcion="Factura 00400000",
            creado_por_id=active_user.id,
        )
        assert mov.id is not None
        assert mov.tipo == "debe"
        assert mov.monto == Decimal("1500.00")
        assert mov.moneda == "ARS"
        assert mov.tipo_cambio_a_ars == Decimal("1")
        assert mov.signo_ajuste is None

    def test_insertar_mov_usd_resuelve_tc(self, db, empresa, proveedor, active_user, tipo_cambio_usd) -> None:
        """TC del 2026-03-10 debe ser el del 2026-03-01 (más reciente <= fecha)."""
        mov = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("100"),
            moneda="USD",
            origen_tipo="factura_erp",
            origen_id=42,
            creado_por_id=active_user.id,
        )
        # venta=1020.0 del 2026-03-01
        assert mov.tipo_cambio_a_ars == Decimal("1020.0")

    def test_insertar_mov_usd_sin_tc_loguea_none(self, db, empresa, proveedor, active_user) -> None:
        """Sin TC en la tabla, el mov se registra con tipo_cambio_a_ars=None."""
        mov = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("100"),
            moneda="USD",
            origen_tipo="factura_erp",
            origen_id=42,
            creado_por_id=active_user.id,
        )
        assert mov.tipo_cambio_a_ars is None

    def test_insertar_mov_ajuste_requiere_signo(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc_info:
            insertar_mov(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                fecha_movimiento=date(2026, 3, 10),
                tipo="ajuste",
                monto=Decimal("100"),
                moneda="ARS",
                origen_tipo="ajuste_manual",
                origen_id=None,
                creado_por_id=active_user.id,
                # signo_ajuste=None — falta
            )
        assert exc_info.value.status_code == 400
        assert "signo_ajuste" in exc_info.value.detail

    def test_insertar_mov_ajuste_con_signo_valido(self, db, empresa, proveedor, active_user) -> None:
        mov = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="ajuste",
            monto=Decimal("50"),
            moneda="ARS",
            origen_tipo="ajuste_manual",
            origen_id=None,
            creado_por_id=active_user.id,
            signo_ajuste=-1,
        )
        assert mov.tipo == "ajuste"
        assert mov.signo_ajuste == -1

    def test_insertar_mov_debe_con_signo_ajuste_raise(self, db, empresa, proveedor, active_user) -> None:
        """tipo!='ajuste' y signo_ajuste no-None → 400."""
        with pytest.raises(HTTPException) as exc_info:
            insertar_mov(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                fecha_movimiento=date(2026, 3, 10),
                tipo="debe",
                monto=Decimal("100"),
                moneda="ARS",
                origen_tipo="factura_erp",
                origen_id=1,
                creado_por_id=active_user.id,
                signo_ajuste=1,
            )
        assert exc_info.value.status_code == 400

    def test_insertar_mov_monto_negativo_raise(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc_info:
            insertar_mov(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                fecha_movimiento=date(2026, 3, 10),
                tipo="debe",
                monto=Decimal("-10"),
                moneda="ARS",
                origen_tipo="factura_erp",
                origen_id=1,
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 400
        assert "monto" in exc_info.value.detail


# ──────────────────────────────────────────────────────────────────────────
# calcular_saldo_por_moneda
# ──────────────────────────────────────────────────────────────────────────


class TestCalcularSaldo:
    def test_saldo_una_moneda_debe_menos_haber(self, db, empresa, proveedor, active_user) -> None:
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("1000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 15),
            tipo="haber",
            monto=Decimal("300"),
            moneda="ARS",
            origen_tipo="orden_pago",
            origen_id=1,
            creado_por_id=active_user.id,
        )

        saldo = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)
        assert saldo == {"ARS": Decimal("700")}

    def test_saldo_multi_moneda(self, db, empresa, proveedor, active_user, tipo_cambio_usd) -> None:
        # ARS: debe 500
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("500"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        # USD: debe 200
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("200"),
            moneda="USD",
            origen_tipo="factura_erp",
            origen_id=2,
            creado_por_id=active_user.id,
        )

        saldo = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)
        assert saldo == {"ARS": Decimal("500"), "USD": Decimal("200")}

    def test_saldo_incluye_ajustes_firmados(self, db, empresa, proveedor, active_user) -> None:
        # debe 1000 - haber 300 + ajuste (+1) 50 = 750
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("1000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 11),
            tipo="haber",
            monto=Decimal("300"),
            moneda="ARS",
            origen_tipo="orden_pago",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 12),
            tipo="ajuste",
            monto=Decimal("50"),
            moneda="ARS",
            signo_ajuste=1,
            origen_tipo="ajuste_manual",
            origen_id=None,
            creado_por_id=active_user.id,
        )

        saldo = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)
        assert saldo == {"ARS": Decimal("750")}

    def test_saldo_filtra_hasta_fecha(self, db, empresa, proveedor, active_user) -> None:
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("500"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),  # posterior
            tipo="debe",
            monto=Decimal("2000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=2,
            creado_por_id=active_user.id,
        )

        saldo_hasta_marzo = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id, hasta_fecha=date(2026, 3, 31))
        saldo_sin_corte = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)

        assert saldo_hasta_marzo == {"ARS": Decimal("500")}
        assert saldo_sin_corte == {"ARS": Decimal("2500")}

    def test_saldo_filtra_por_empresa(self, db, empresa, empresa2, proveedor, active_user) -> None:
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("500"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa2.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("2000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=2,
            creado_por_id=active_user.id,
        )

        saldo_e1 = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id, empresa_id=empresa.id)
        saldo_e2 = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id, empresa_id=empresa2.id)

        assert saldo_e1 == {"ARS": Decimal("500")}
        assert saldo_e2 == {"ARS": Decimal("2000")}

    def test_saldo_sin_movimientos_retorna_dict_vacio(self, db, empresa, proveedor) -> None:
        saldo = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)
        assert saldo == {}


# ──────────────────────────────────────────────────────────────────────────
# listar_movimientos
# ──────────────────────────────────────────────────────────────────────────


class TestListarMovimientos:
    def test_listar_con_filtros(self, db, empresa, proveedor, active_user) -> None:
        m1 = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 10),
            tipo="debe",
            monto=Decimal("100"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        m2 = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 20),
            tipo="haber",
            monto=Decimal("50"),
            moneda="ARS",
            origen_tipo="orden_pago",
            origen_id=1,
            creado_por_id=active_user.id,
        )
        _m3 = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 5),
            tipo="debe",
            monto=Decimal("300"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=2,
            creado_por_id=active_user.id,
        )

        # Filtro por rango de fechas — excluye m3.
        resultado = listar_movimientos(
            db,
            proveedor_id=proveedor.id,
            desde=date(2026, 3, 1),
            hasta=date(2026, 3, 31),
        )
        assert [m.id for m in resultado] == [m1.id, m2.id]

    def test_listar_ordenado_por_fecha_asc(self, db, empresa, proveedor, active_user) -> None:
        m_tarde = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 5, 1),
            tipo="debe",
            monto=Decimal("100"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=2,
            creado_por_id=active_user.id,
        )
        m_temprano = insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 1, 1),
            tipo="debe",
            monto=Decimal("100"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )

        resultado = listar_movimientos(db, proveedor_id=proveedor.id)
        assert [m.id for m in resultado] == [m_temprano.id, m_tarde.id]


# ──────────────────────────────────────────────────────────────────────────
# F4 — aplicar_imputacion (COMPRAS-4.7)
# ──────────────────────────────────────────────────────────────────────────


class TestAplicarImputacion:
    def test_imputacion_normal_genera_haber(self, db, empresa, proveedor, active_user) -> None:
        """Imputación no-reversal con origen='orden_pago' → haber en CC."""
        from app.models.imputacion import Imputacion  # noqa: PLC0415
        from app.services.cc_proveedor_service import aplicar_imputacion  # noqa: PLC0415

        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=1,
            destino_tipo="pedido_compra",
            destino_id=1,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()

        movs = aplicar_imputacion(db, imputacion_id=imp.id)
        assert len(movs) == 1
        assert movs[0].tipo == "haber"
        assert movs[0].monto == Decimal("500")
        assert movs[0].moneda == "ARS"
        assert movs[0].origen_tipo == "imputacion"
        assert movs[0].origen_id == imp.id

    def test_imputacion_reversal_genera_debe(self, db, empresa, proveedor, active_user) -> None:
        from app.models.imputacion import Imputacion  # noqa: PLC0415
        from app.services.cc_proveedor_service import aplicar_imputacion  # noqa: PLC0415

        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=1,
            destino_tipo="pedido_compra",
            destino_id=1,
            monto_imputado=Decimal("300"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=True,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()

        movs = aplicar_imputacion(db, imputacion_id=imp.id)
        assert len(movs) == 1
        assert movs[0].tipo == "debe"
        assert movs[0].origen_tipo == "reimputacion"

    def test_aplicar_imputacion_saldo_final_correcto(self, db, empresa, proveedor, active_user) -> None:
        """
        Flujo completo:
          - insertar DEBE por 1000 (factura)
          - imputación normal por 400 → haber (reduce deuda)
          - imputación reversal por 400 → debe (deshace imputación)
          - saldo final: 1000 (debe)
        """
        from app.models.imputacion import Imputacion  # noqa: PLC0415
        from app.services.cc_proveedor_service import (  # noqa: PLC0415
            aplicar_imputacion,
            calcular_saldo_por_moneda,
        )

        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 3, 1),
            tipo="debe",
            monto=Decimal("1000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=1,
            creado_por_id=active_user.id,
        )

        imp_normal = Imputacion(
            origen_tipo="orden_pago",
            origen_id=10,
            destino_tipo="factura_erp",
            destino_id=1,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp_normal)
        db.flush()
        aplicar_imputacion(db, imputacion_id=imp_normal.id)

        # Saldo intermedio: 1000 - 400 = 600
        saldos = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id, empresa_id=empresa.id)
        assert saldos["ARS"] == Decimal("600")

        imp_reversal = Imputacion(
            origen_tipo="orden_pago",
            origen_id=10,
            destino_tipo="factura_erp",
            destino_id=1,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=True,
            reimputada_desde_id=imp_normal.id,
            creado_por_id=active_user.id,
        )
        db.add(imp_reversal)
        db.flush()
        aplicar_imputacion(db, imputacion_id=imp_reversal.id)

        # Saldo final: 1000 - 400 + 400 = 1000
        saldos = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id, empresa_id=empresa.id)
        assert saldos["ARS"] == Decimal("1000")


# ──────────────────────────────────────────────────────────────────────────
# _resolver_empresa_id_para_imputacion — Prioridad 4 (factura_erp → bra_id)
# Fix: antes caía al fallback=1 para cualquier factura_erp → bug financiero
#      real cuando la ct pertenecía a Grupo Gauss (empresa_id=2, bra_id=45).
# ──────────────────────────────────────────────────────────────────────────


class TestResolverEmpresaFacturaErp:
    """
    Valida la prioridad 4 de `_resolver_empresa_id_para_imputacion`:
    resolver `empresa_id` para imputaciones `destino=factura_erp` usando
    `(comp_id, bra_id)` del `ct_transaction` vía `bra_a_empresa_o_ignorar`.
    """

    def _crear_imp_a_factura(
        self,
        db,
        *,
        proveedor_id: int,
        ct_transaction_id: int,
        monto: Decimal = Decimal("1000"),
        user_id: int,
    ):
        from app.models.imputacion import Imputacion  # noqa: PLC0415

        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=777,
            destino_tipo="factura_erp",
            destino_id=ct_transaction_id,
            monto_imputado=monto,
            moneda_imputada="ARS",
            proveedor_id=proveedor_id,
            es_reversal=False,
            creado_por_id=user_id,
        )
        db.add(imp)
        db.flush()
        return imp

    def _crear_ct(self, db, *, ct_transaction: int, comp_id: int, bra_id: int) -> None:
        from app.models.commercial_transaction import CommercialTransaction  # noqa: PLC0415

        ct = CommercialTransaction(
            ct_transaction=ct_transaction,
            comp_id=comp_id,
            bra_id=bra_id,
            ct_total=Decimal("1000"),
        )
        db.add(ct)
        db.flush()

    def test_resolver_empresa_factura_erp_bra_1_devuelve_empresa_1(
        self, db, empresa, proveedor, active_user
    ) -> None:
        """`ct_transaction` con (comp_id=1, bra_id=1) → empresa_id=1."""
        from app.services.cc_proveedor_service import _resolver_empresa_id_para_imputacion  # noqa: PLC0415

        self._crear_ct(db, ct_transaction=12001, comp_id=1, bra_id=1)
        imp = self._crear_imp_a_factura(
            db, proveedor_id=proveedor.id, ct_transaction_id=12001, user_id=active_user.id
        )

        empresa_id = _resolver_empresa_id_para_imputacion(db, imp)
        assert empresa_id == 1

    def test_resolver_empresa_factura_erp_bra_45_devuelve_empresa_2(
        self, db, empresa, empresa2, proveedor, active_user
    ) -> None:
        """`ct_transaction` con (comp_id=1, bra_id=45) → empresa_id=2 (Grupo Gauss).

        Este es el caso que ANTES del fix caía a fallback=1 → bug: movimiento
        CC asociado a empresa incorrecta.
        """
        from app.services.cc_proveedor_service import _resolver_empresa_id_para_imputacion  # noqa: PLC0415

        self._crear_ct(db, ct_transaction=12045, comp_id=1, bra_id=45)
        imp = self._crear_imp_a_factura(
            db, proveedor_id=proveedor.id, ct_transaction_id=12045, user_id=active_user.id
        )

        empresa_id = _resolver_empresa_id_para_imputacion(db, imp)
        assert empresa_id == 2

    def test_resolver_empresa_factura_erp_bra_no_mapeado_devuelve_1_con_warning(
        self, db, empresa, proveedor, active_user, caplog
    ) -> None:
        """
        `(comp_id=1, bra_id=37)` (sucursal interna de transferencia) no está
        en `COMP_BRA_A_EMPRESA` → `bra_a_empresa_o_ignorar` retorna None →
        fallback a 1 con log WARNING.
        """
        import logging  # noqa: PLC0415

        from app.services.cc_proveedor_service import _resolver_empresa_id_para_imputacion  # noqa: PLC0415

        self._crear_ct(db, ct_transaction=13037, comp_id=1, bra_id=37)
        imp = self._crear_imp_a_factura(
            db, proveedor_id=proveedor.id, ct_transaction_id=13037, user_id=active_user.id
        )

        # `app.core.logging.setup_logging` pone `propagate=False` en el logger
        # root `app`, por lo que los warnings no llegan al root global donde
        # caplog se engancha. Adjuntamos el handler de caplog directamente al
        # logger `app` para esta prueba (limpieza automática al salir del with).
        app_logger = logging.getLogger("app")
        app_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger="app"):
                empresa_id = _resolver_empresa_id_para_imputacion(db, imp)
        finally:
            app_logger.removeHandler(caplog.handler)

        assert empresa_id == 1
        # Alguno de los dos warnings debe aparecer: el de bra_a_empresa_o_ignorar
        # (del core map) o el del fallback final (del service).
        mensajes = " ".join(r.getMessage() for r in caplog.records)
        assert "bra_id=37" in mensajes or "13037" in mensajes

    def test_resolver_empresa_factura_erp_ct_no_existe_devuelve_1_con_warning(
        self, db, empresa, proveedor, active_user, caplog
    ) -> None:
        """
        Imputación `destino=factura_erp` con `destino_id` que no matchea ninguna
        fila en `tb_commercial_transactions` → fallback a 1 con WARNING
        específico (no crashea).
        """
        import logging  # noqa: PLC0415

        from app.services.cc_proveedor_service import _resolver_empresa_id_para_imputacion  # noqa: PLC0415

        imp = self._crear_imp_a_factura(
            db, proveedor_id=proveedor.id, ct_transaction_id=99_999_999, user_id=active_user.id
        )

        app_logger = logging.getLogger("app")
        app_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger="app"):
                empresa_id = _resolver_empresa_id_para_imputacion(db, imp)
        finally:
            app_logger.removeHandler(caplog.handler)

        assert empresa_id == 1
        mensajes = " ".join(r.getMessage() for r in caplog.records)
        assert "99999999" in mensajes and "no existe en tb_commercial_transactions" in mensajes
