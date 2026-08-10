"""
Lecturas ORIGIN-SIDE de `imputaciones` (compras_038, etapa 1).

El saldo de un documento ORIGEN (NC local, dinero a cuenta) se calcula
restándole lo que ya consumió. Ese "lo que ya consumió" es la pata ORIGEN
(`monto_origen`), NO la pata destino (`monto_imputado`), que en cross-moneda
es otro número y otra moneda.

Antes de compras_038 estas agregaciones sumaban `monto_imputado` sin filtro de
moneda. Con cross-moneda habilitado (etapa 2) eso significa que una NC de
1.000 ARS imputada a un pedido USD descontaría 0,66 de su saldo en vez de
1.000 — la misma NC se podría gastar ~1.500 veces.

Las filas cross-moneda se construyen acá con `Imputacion(...)` directo, a
propósito: `imputar_nc_a_pedido` todavía rechaza cross-moneda NC↔pedido (eso
se levanta en etapa 2), pero las LECTURAS ya tienen que estar bien, si no la
etapa 2 aterriza sobre un cálculo roto.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.dinero_a_cuenta import DineroACuenta
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import (
    cc_proveedor_service,
    dinero_a_cuenta_service,
    imputaciones_service,
    ncs_locales_service,
)

# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=1, nombre="EmpresaTest", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db, empresa) -> Proveedor:
    p = Proveedor(id=1, nombre="Prov", activo=True, origen=OrigenProveedor.ERP.value, supp_id=42)
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def nc_ars_1000(db, empresa, proveedor, active_user):
    """NC local aprobada de 1.000 ARS."""
    nc = ncs_locales_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        fecha_emision=date.today(),
        motivo="test saldo origen",
        creado_por_id=active_user.id,
    )
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)
    return nc


def _imputacion_cross_moneda(
    db,
    *,
    origen_tipo: str,
    origen_id: int,
    proveedor_id: int,
    user_id: int,
    monto_origen: Decimal,
    moneda_origen: str,
    monto_imputado: Decimal,
    moneda_imputada: str,
    es_reversal: bool = False,
) -> Imputacion:
    """Construye la fila directo, saltando el veto de negocio de etapa 1."""
    imp = Imputacion(
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        destino_tipo="pedido_compra",
        destino_id=999,
        monto_imputado=monto_imputado,
        moneda_imputada=moneda_imputada,
        monto_origen=monto_origen,
        moneda_origen=moneda_origen,
        tipo_cambio=Decimal("1500"),
        proveedor_id=proveedor_id,
        es_reversal=es_reversal,
        creado_por_id=user_id,
    )
    db.add(imp)
    db.flush()
    return imp


# ──────────────────────────────────────────────────────────────────────────
# ncs_locales_service.calcular_saldo_pendiente
# ──────────────────────────────────────────────────────────────────────────


class TestSaldoNCLocalUsaLaPataOrigen:
    def test_same_moneda_sin_cambios(self, db, nc_ars_1000, proveedor, active_user) -> None:
        """Regresión: en same-moneda el resultado es idéntico a pre-compras_038."""
        _imputacion_cross_moneda(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
        )

        saldo = ncs_locales_service.calcular_saldo_pendiente(db, nc_ars_1000.id)
        assert saldo == Decimal("600")

    def test_cross_moneda_descuenta_los_ars_no_los_usd(self, db, nc_ars_1000, proveedor, active_user) -> None:
        """NC de 1.000 ARS que cubre 0,27 USD de un pedido USD consumió 400 ARS
        de sí misma, no 0,27."""
        _imputacion_cross_moneda(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("0.27"),
            moneda_imputada="USD",
        )

        saldo = ncs_locales_service.calcular_saldo_pendiente(db, nc_ars_1000.id)
        assert saldo == Decimal("600")
        assert saldo != Decimal("999.73"), "está leyendo la pata destino"

    def test_cross_moneda_reversal_devuelve_los_ars(self, db, nc_ars_1000, proveedor, active_user) -> None:
        """El reversal tiene que devolver el importe ORIGEN al origen."""
        for es_reversal in (False, True):
            _imputacion_cross_moneda(
                db,
                origen_tipo="nota_credito_local",
                origen_id=nc_ars_1000.id,
                proveedor_id=proveedor.id,
                user_id=active_user.id,
                monto_origen=Decimal("400"),
                moneda_origen="ARS",
                monto_imputado=Decimal("0.27"),
                moneda_imputada="USD",
                es_reversal=es_reversal,
            )

        saldo = ncs_locales_service.calcular_saldo_pendiente(db, nc_ars_1000.id)
        assert saldo == Decimal("1000")

    def test_fila_legacy_sin_pata_origen_cae_a_monto_imputado(self, db, nc_ars_1000, proveedor, active_user) -> None:
        """Filas escritas por una instancia pre-compras_038 durante un deploy
        rolling: la lectura no puede tratarlas como 0."""
        imp = Imputacion(
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            destino_tipo="pedido_compra",
            destino_id=999,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            monto_origen=None,
            moneda_origen=None,
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()

        saldo = ncs_locales_service.calcular_saldo_pendiente(db, nc_ars_1000.id)
        assert saldo == Decimal("600")


# ──────────────────────────────────────────────────────────────────────────
# imputaciones_service._validar_origen_nc_local_disponible
# ──────────────────────────────────────────────────────────────────────────


class TestValidacionOrigenNCUsaLaPataOrigen:
    def test_saldo_consumido_se_mide_en_la_moneda_de_la_nc(self, db, nc_ars_1000, proveedor, active_user) -> None:
        """Tras consumir 400 de 1.000 ARS vía una imputación cross-moneda, la NC
        no puede aceptar otra imputación de 700 ARS."""
        _imputacion_cross_moneda(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("0.27"),
            moneda_imputada="USD",
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            imputaciones_service.crear_imputacion(
                db,
                origen_tipo="nota_credito_local",
                origen_id=nc_ars_1000.id,
                destino_tipo="pedido_compra",
                destino_id=888,
                monto_imputado=Decimal("700"),
                moneda_imputada="ARS",
                monto_origen=Decimal("700"),
                moneda_origen="ARS",
                proveedor_id=proveedor.id,
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400
        assert "excede el saldo pendiente" in exc.value.detail

    def test_permite_imputar_exactamente_el_saldo_restante(self, db, nc_ars_1000, proveedor, active_user) -> None:
        _imputacion_cross_moneda(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("0.27"),
            moneda_imputada="USD",
        )

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            destino_tipo="pedido_compra",
            destino_id=888,
            monto_imputado=Decimal("600"),
            moneda_imputada="ARS",
            monto_origen=Decimal("600"),
            moneda_origen="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        assert imp.id is not None


# ──────────────────────────────────────────────────────────────────────────
# cc_proveedor_service._calcular_componente_nc (batch)
# ──────────────────────────────────────────────────────────────────────────


class TestComponenteNCEnCCUsaLaPataOrigen:
    def test_componente_nc_descuenta_la_pata_origen(self, db, empresa, nc_ars_1000, proveedor, active_user) -> None:
        _imputacion_cross_moneda(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("0.27"),
            moneda_imputada="USD",
        )

        total = cc_proveedor_service._calcular_componente_nc(
            db,
            proveedor_id=proveedor.id,
            moneda="ARS",
            empresa_id=empresa.id,
        )
        assert total == Decimal("600")


# ──────────────────────────────────────────────────────────────────────────
# dinero_a_cuenta_service — saldo simple y batch
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def dac_ars_1000(db, empresa, proveedor, active_user) -> DineroACuenta:
    op = OrdenPago(
        numero="OP-DAC-1",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("1000"),
        modo_imputacion="a_cuenta",
        estado="pagado",
        creado_por_id=active_user.id,
    )
    db.add(op)
    db.flush()
    dac = DineroACuenta(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        monto=Decimal("1000"),
        moneda="ARS",
        origen_op_id=op.id,
        estado="disponible",
        creado_por_id=active_user.id,
    )
    db.add(dac)
    db.flush()
    return dac


class TestSaldoDineroACuentaUsaLaPataOrigen:
    def test_cross_moneda_descuenta_la_pata_origen(self, db, dac_ars_1000, proveedor, active_user) -> None:
        _imputacion_cross_moneda(
            db,
            origen_tipo="dinero_a_cuenta",
            origen_id=dac_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("0.27"),
            moneda_imputada="USD",
        )

        saldo = dinero_a_cuenta_service.calcular_saldo_disponible(db, dac_ars_1000.id)
        assert saldo == Decimal("600")

    def test_batch_coincide_con_el_calculo_simple(self, db, dac_ars_1000, proveedor, active_user) -> None:
        _imputacion_cross_moneda(
            db,
            origen_tipo="dinero_a_cuenta",
            origen_id=dac_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("0.27"),
            moneda_imputada="USD",
        )

        batch = dinero_a_cuenta_service.calcular_saldos_disponibles_batch(
            db,
            [dac_ars_1000.id],
            {dac_ars_1000.id: Decimal("1000")},
        )
        assert batch[dac_ars_1000.id] == Decimal("600")
        assert batch[dac_ars_1000.id] == dinero_a_cuenta_service.calcular_saldo_disponible(db, dac_ars_1000.id)

    def test_fila_legacy_sin_pata_origen_cae_a_monto_imputado(self, db, dac_ars_1000, proveedor, active_user) -> None:
        imp = Imputacion(
            origen_tipo="dinero_a_cuenta",
            origen_id=dac_ars_1000.id,
            destino_tipo="pedido_compra",
            destino_id=999,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            monto_origen=None,
            moneda_origen=None,
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()

        assert dinero_a_cuenta_service.calcular_saldo_disponible(db, dac_ars_1000.id) == Decimal("600")
        batch = dinero_a_cuenta_service.calcular_saldos_disponibles_batch(
            db, [dac_ars_1000.id], {dac_ars_1000.id: Decimal("1000")}
        )
        assert batch[dac_ars_1000.id] == Decimal("600")


# ──────────────────────────────────────────────────────────────────────────
# El panel de NCs disponibles — el que motivó todo esto
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_permiso_ordenes_compra():
    """Fuerza `PermisosService.tiene_permiso → True` (mismo patrón que
    `tests/integration/test_administracion_compras_router.py`): `require_permiso`
    captura la clase en una closure al registrar el router, así que hay que
    parchear el método sobre la clase ya importada."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


class TestPanelNCsDisponiblesUsaLaPataOrigen:
    def test_saldo_del_panel_coincide_con_el_saldo_del_servicio(
        self,
        db,
        client,
        auth_headers,
        con_permiso_ordenes_compra,
        empresa,
        nc_ars_1000,
        proveedor,
        active_user,
    ) -> None:
        _imputacion_cross_moneda(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_ars_1000.id,
            proveedor_id=proveedor.id,
            user_id=active_user.id,
            monto_origen=Decimal("400"),
            moneda_origen="ARS",
            monto_imputado=Decimal("0.27"),
            moneda_imputada="USD",
        )
        db.commit()

        resp = client.get(
            f"/api/administracion/compras/ncs-locales/disponibles?proveedor_id={proveedor.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        filas = {f["id"]: f for f in resp.json()}
        assert nc_ars_1000.id in filas
        assert Decimal(filas[nc_ars_1000.id]["saldo_pendiente"]) == Decimal("600")
