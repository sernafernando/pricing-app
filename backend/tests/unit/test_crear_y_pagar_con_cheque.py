"""
Tests unitarios — cheque propio integrado en crear_y_pagar / ejecutar_pago.

TDD Strict — FR-1.2, FR-1.3, FR-1.4:
  - crear_y_pagar con cheque: emite cheque, crea OrdenPagoCheque, imputa CC (haber).
  - Cheque diferido → estado 'diferido'.
  - Anulación de cheque de OP → revierte movimiento CC.
  - Regresión: sin cheques → comportamiento idéntico al anterior.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.banco_empresa import BancoEmpresa
from app.models.caja import Caja
from app.models.cheque import Cheque, OrdenPagoCheque
from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=60, nombre="EmpresaChequeOP", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=60,
        nombre="ProveedorChequeOP",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=600,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def tipos_doc_caja(db) -> None:
    from app.models.caja import CajaTipoDocumento

    for nombre in ("Orden de Pago", "Orden de Pago Anulada"):
        db.add(CajaTipoDocumento(nombre=nombre, descripcion=nombre, activo=True))
    db.flush()


@pytest.fixture
def caja(db, empresa, tipos_doc_caja) -> Caja:
    c = Caja(
        nombre="CajaChequeOP",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_actual=Decimal("5000000"),
        saldo_inicial=Decimal("5000000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=60,
        banco="BancoChequeOP",
        moneda="ARS",
        empresa_id=empresa.id,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def cheque_payload(banco) -> dict:
    """Payload base de un cheque propio ARS al día (monto=1_000_000)."""
    return {
        "banco_empresa_id": banco.id,
        "chequera_id": None,
        "instrumento": "echeq",
        "numero": "ECH-001",
        "monto": Decimal("1000000"),
        "moneda": "ARS",
        "fecha_emision": date(2026, 6, 19),
        "fecha_pago": date(2026, 6, 19),
    }


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestCrearYPagarConCheque:
    """FR-1.2 / FR-1.3 — cheque propio integrado en crear_y_pagar."""

    def test_cheque_100_pct_emite_linkea_imputa_cc(
        self, db, empresa, proveedor, banco, active_user, cheque_payload
    ) -> None:
        """
        OP ARS 1_000_000. Cheque ARS 1_000_000 (100% cobertura).
        Caja=None (solo cheque). No hay items de pedido.
        Verifica: cheque emitido, OrdenPagoCheque creado, movimiento CC haber.
        """
        from app.models.cc_proveedor_movimiento import CCProveedorMovimiento

        # Cheque cubre 100% — no hay items de cash (pago_a_cuenta=0, base_items=0).
        # monto_total = cheques_op_moneda (1_000_000) → balance ok.
        # Usamos modo 'a_cuenta' sin items porque no hay pedido que imputar.
        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[cheque_payload],
        )

        assert op.estado == "pagado"

        # Cheque emitido con estado correcto
        cheque = db.query(Cheque).filter(Cheque.numero == "ECH-001").one()
        assert cheque.estado == "emitido"
        assert cheque.proveedor_id == proveedor.id
        assert cheque.orden_pago_id == op.id

        # OrdenPagoCheque link creado
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.orden_pago_id == op.id).one()
        assert link.cheque_id == cheque.id
        assert link.monto_op_moneda == Decimal("1000000")

        # Movimiento CC tipo 'haber' por el cheque
        movs = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor.id,
                CCProveedorMovimiento.origen_tipo == "cheque",
            )
            .all()
        )
        assert len(movs) == 1
        assert movs[0].tipo == "haber"
        assert Decimal(str(movs[0].monto)) == Decimal("1000000")

    def test_cheque_mas_caja_combinados(self, db, empresa, proveedor, caja, banco, active_user, cheque_payload) -> None:
        """
        OP ARS 1_000_000. Cheque 700_000 + caja 300_000 → OK.
        """
        payload_700k = {
            "banco_empresa_id": banco.id,
            "chequera_id": None,
            "instrumento": "echeq",
            "numero": "ECH-002",
            "monto": Decimal("700000"),
            "moneda": "ARS",
            "fecha_emision": date(2026, 6, 19),
            "fecha_pago": date(2026, 6, 19),
        }

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pago_a_cuenta", "id": None, "monto": Decimal("300000")}],
            caja_id=caja.id,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[payload_700k],
        )

        assert op.estado == "pagado"
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.orden_pago_id == op.id).one()
        assert link.monto_op_moneda == Decimal("700000")

    def test_cheque_diferido_estado_diferido(self, db, empresa, proveedor, banco, active_user) -> None:
        """Cheque con fecha_pago > fecha_emision → estado 'diferido'."""
        payload_dif = {
            "banco_empresa_id": banco.id,
            "chequera_id": None,
            "instrumento": "echeq",
            "numero": "ECH-DIF-001",
            "monto": Decimal("1000000"),
            "moneda": "ARS",
            "fecha_emision": date(2026, 6, 19),
            "fecha_pago": date(2026, 6, 19) + timedelta(days=60),
        }

        ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[payload_dif],
        )

        cheque = db.query(Cheque).filter(Cheque.numero == "ECH-DIF-001").one()
        assert cheque.estado == "diferido"

    def test_sin_cheques_regresion(self, db, empresa, proveedor, caja, active_user) -> None:
        """Sin cheques → comportamiento existente (regresión)."""
        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("10000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pago_a_cuenta", "id": None, "monto": Decimal("10000")}],
            caja_id=caja.id,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
        )
        assert op.estado == "pagado"
        links = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.orden_pago_id == op.id).all()
        assert len(links) == 0


class TestAnularChequeOP:
    """FR-1.4 / Escenario 1.4.a — anular cheque de OP revierte CC."""

    def _crear_op_con_cheque(self, db, empresa, proveedor, banco, active_user, cheque_payload):
        """Helper: crea una OP con un cheque."""
        return ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[{**cheque_payload}],  # copy to avoid mutation issues
        )

    def test_anular_cheque_revierte_cc(self, db, empresa, proveedor, banco, active_user, cheque_payload) -> None:
        """
        Cheque emitido con la OP → anular → reversal CC (debe) + estado anulado.
        """
        from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
        from app.services import cheques_service

        op = self._crear_op_con_cheque(db, empresa, proveedor, banco, active_user, cheque_payload)

        cheque = db.query(Cheque).filter(Cheque.orden_pago_id == op.id).one()
        assert cheque.estado in ("emitido", "diferido")

        # Count CC movs before
        movs_antes = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).count()

        # Anular
        cheques_service.transicionar_cheque(
            db,
            cheque,
            "anular",
            usuario_id=active_user.id,
            motivo="Test anulacion",
            empresa_id=empresa.id,
        )

        assert cheque.estado == "anulado"

        # CC reversal added (debe)
        movs_despues = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).all()
        assert len(movs_despues) == movs_antes + 1
        reversal = movs_despues[-1]
        assert reversal.tipo in ("debe", "ajuste")


# ──────────────────────────────────────────────────────────────────────────
# New tests — cheque con pedido_id (imputación al pedido, no haber directo CC)
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa_p(db) -> "Empresa":
    from app.models.empresa import Empresa

    e = Empresa(id=70, nombre="EmpresaChequeConPedido", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor_p(db) -> "Proveedor":
    p = Proveedor(
        id=70,
        nombre="ProveedorChequeConPedido",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=700,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_1m(db, empresa_p, proveedor_p, active_user):
    """Pedido ARS 1_000_000 en estado aprobado."""
    from app.models.pedido_compra import PedidoCompra

    p = PedidoCompra(
        id=70,
        numero="PC-70-2026-00001",
        empresa_id=empresa_p.id,
        proveedor_id=proveedor_p.id,
        moneda="ARS",
        monto=Decimal("1000000"),
        tipo_cambio=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco_p(db, empresa_p) -> "BancoEmpresa":
    b = BancoEmpresa(
        id=70,
        banco="BancoChequeConPedido",
        moneda="ARS",
        empresa_id=empresa_p.id,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def tipos_doc_caja_p(db) -> None:
    from app.models.caja import CajaTipoDocumento

    for nombre in ("Orden de Pago", "Orden de Pago Anulada"):
        existing = db.query(CajaTipoDocumento).filter(CajaTipoDocumento.nombre == nombre).first()
        if not existing:
            db.add(CajaTipoDocumento(nombre=nombre, descripcion=nombre, activo=True))
    db.flush()


@pytest.fixture
def caja_p(db, empresa_p, tipos_doc_caja_p) -> "Caja":
    c = Caja(
        nombre="CajaChequeConPedido",
        empresa_id=empresa_p.id,
        moneda="ARS",
        saldo_actual=Decimal("5000000"),
        saldo_inicial=Decimal("5000000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


class TestChequeConPedidoId:
    """Imputación al pedido cuando el cheque lleva pedido_id."""

    def _cheque_payload(self, banco_p, numero: str, monto: Decimal, pedido_id: int | None = None) -> dict:
        payload: dict = {
            "banco_empresa_id": banco_p.id,
            "chequera_id": None,
            "instrumento": "echeq",
            "numero": numero,
            "monto": monto,
            "moneda": "ARS",
            "fecha_emision": date(2026, 6, 19),
            "fecha_pago": date(2026, 6, 19),
        }
        if pedido_id is not None:
            payload["pedido_id"] = pedido_id
        return payload

    def test_item_neto_mas_cheque_con_pedido_id_saldo_cero(
        self, db, empresa_p, proveedor_p, caja_p, banco_p, pedido_1m, active_user
    ) -> None:
        """
        CRÍTICO: OP con pedido 1_000_000.
        Item neto 300_000 + cheque 700_000 CON pedido_id.
        Tras pagar: calcular_saldo_pendiente_pedido == 0.
        No debe crear haber directo CC por el cheque (evita doble conteo).
        """
        from app.models.imputacion import Imputacion
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido

        ch_payload = self._cheque_payload(banco_p, "ECH-P-001", Decimal("700000"), pedido_id=pedido_1m.id)

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor_p.id,
            empresa_id=empresa_p.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_1m.id, "monto": Decimal("300000")}],
            caja_id=caja_p.id,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[ch_payload],
        )

        assert op.estado == "pagado"

        # Saldo del pedido debe ser 0
        saldo = calcular_saldo_pendiente_pedido(db, pedido_1m.id)
        assert saldo == Decimal("0"), f"Se esperaba saldo=0, got {saldo}"

        # La imputación cheque→pedido debe existir
        imp = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "cheque",
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == pedido_1m.id,
                Imputacion.es_reversal.is_(False),
            )
            .one_or_none()
        )
        assert imp is not None, "Debe existir una Imputacion cheque→pedido_compra"
        assert imp.monto_imputado == Decimal("700000")

    def test_cheque_100pct_con_pedido_id_saldo_cero(
        self, db, empresa_p, proveedor_p, banco_p, pedido_1m, active_user
    ) -> None:
        """
        Pedido 100% con cheque (item neto 0 + cheque 1_000_000 con pedido_id).
        Saldo pedido = 0.
        """
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido

        ch_payload = self._cheque_payload(banco_p, "ECH-P-002", Decimal("1000000"), pedido_id=pedido_1m.id)

        # 100% cheque coverage: no cash items needed. mode=a_cuenta (no pedido item in items[]).
        # The cheque carries pedido_id to target the specific pedido.
        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor_p.id,
            empresa_id=empresa_p.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[ch_payload],
        )

        assert op.estado == "pagado"
        saldo = calcular_saldo_pendiente_pedido(db, pedido_1m.id)
        assert saldo == Decimal("0"), f"Se esperaba saldo=0, got {saldo}"

    def test_cheque_sin_pedido_id_no_crea_imputacion_pedido(
        self, db, empresa_p, proveedor_p, banco_p, active_user
    ) -> None:
        """
        'A cuenta' (cheque sin pedido_id): NO crea Imputacion al pedido,
        solo haber directo CC del proveedor.
        """
        from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
        from app.models.imputacion import Imputacion

        ch_payload = self._cheque_payload(banco_p, "ECH-P-003", Decimal("1000000"), pedido_id=None)

        ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor_p.id,
            empresa_id=empresa_p.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[ch_payload],
        )

        # No Imputacion creada con origen cheque hacia pedido
        imp = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "cheque",
                Imputacion.destino_tipo == "pedido_compra",
            )
            .one_or_none()
        )
        assert imp is None, "No debe crearse Imputacion cheque→pedido en modo a_cuenta"

        # Haber directo CC creado
        mov = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor_p.id,
                CCProveedorMovimiento.origen_tipo == "cheque",
                CCProveedorMovimiento.tipo == "haber",
            )
            .one_or_none()
        )
        assert mov is not None, "Debe existir haber directo CC en modo a_cuenta"


# ──────────────────────────────────────────────────────────────────────────
# Fix 1 — anular OP pagada con cheque PROPIO no revertía nada
# ──────────────────────────────────────────────────────────────────────────
#
# Escenarios (TDD strict — RED→GREEN):
#   A. Propio con pedido_id: saldo restaurado, cheque anulado, imputacion revertida.
#   B. Propio "a cuenta" (sin pedido_id): haber CC revertido (debe neto = 0).


class TestAnularOPConChequePropio:
    """Bug fix: anular OP pagada con cheque PROPIO debe revertir la imputación
    y transicionar el cheque a 'anulado'."""

    def _crear_op_con_cheque_propio(
        self,
        db,
        *,
        empresa_p,
        proveedor_p,
        banco_p,
        active_user,
        pedido_id,
        monto: Decimal,
        numero: str,
    ):
        """Crea y paga una OP 100% con cheque propio. Devuelve (op, cheque)."""
        items = []
        if pedido_id is not None:
            items = []  # 100% cheque, modo a_cuenta
        payload = {
            "banco_empresa_id": banco_p.id,
            "chequera_id": None,
            "instrumento": "echeq",
            "numero": numero,
            "monto": monto,
            "moneda": "ARS",
            "fecha_emision": date(2026, 6, 19),
            "fecha_pago": date(2026, 6, 19),
        }
        if pedido_id is not None:
            payload["pedido_id"] = pedido_id

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor_p.id,
            empresa_id=empresa_p.id,
            moneda="ARS",
            monto_total=monto,
            modo_imputacion="a_cuenta",
            items=items,
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[payload],
        )
        cheque = db.query(Cheque).filter(Cheque.numero == numero).one()
        return op, cheque

    def test_anular_op_propio_con_pedido_restaura_saldo(
        self,
        db,
        empresa_p,
        proveedor_p,
        banco_p,
        pedido_1m,
        active_user,
    ) -> None:
        """
        Caso A (con pedido_id):
          1. Pagar OP 1_000_000 con cheque propio linkeado al pedido.
          2. Saldo del pedido baja a 0.
          3. Anular la OP.
          4. Asserts:
             - saldo_pendiente_pedido vuelve a 1_000_000.
             - cheque.estado == 'anulado'.
             - La imputación cheque→pedido fue revertida (es_reversal=True existe).
        """
        from app.models.imputacion import Imputacion
        from app.services import ordenes_pago_service as ops
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido

        op, cheque = self._crear_op_con_cheque_propio(
            db,
            empresa_p=empresa_p,
            proveedor_p=proveedor_p,
            banco_p=banco_p,
            active_user=active_user,
            pedido_id=pedido_1m.id,
            monto=Decimal("1000000"),
            numero="ECH-ANUL-A-001",
        )

        # Precondición: saldo del pedido es 0.
        saldo_pre = calcular_saldo_pendiente_pedido(db, pedido_1m.id)
        assert saldo_pre == Decimal("0"), f"Saldo antes de anular debe ser 0, got {saldo_pre}"

        # Anular la OP.
        ops.anular(db, orden_pago_id=op.id, motivo="Test fix anular propio con pedido", user_id=active_user.id)

        db.expire_all()

        # 1. Saldo del pedido restaurado.
        saldo_post = calcular_saldo_pendiente_pedido(db, pedido_1m.id)
        assert saldo_post == Decimal("1000000"), (
            f"Saldo del pedido debe volver a 1_000_000 tras anular la OP, got {saldo_post}"
        )

        # 2. Cheque propio queda anulado.
        db.refresh(cheque)
        assert cheque.estado == "anulado", f"El cheque propio debe quedar 'anulado', got '{cheque.estado}'"

        # 3. Existe el reversal de la imputación cheque→pedido.
        reversal = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "cheque",
                Imputacion.origen_id == cheque.id,
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.es_reversal.is_(True),
            )
            .one_or_none()
        )
        assert reversal is not None, "Debe existir el reversal de la imputación cheque→pedido_compra"

    def test_anular_op_propio_a_cuenta_revierte_haber_cc(
        self,
        db,
        empresa_p,
        proveedor_p,
        banco_p,
        active_user,
    ) -> None:
        """
        Caso B (sin pedido_id, a cuenta):
          1. Pagar OP 500_000 con cheque propio sin pedido_id.
          2. Haber directo CC insertado.
          3. Anular la OP.
          4. Asserts:
             - El movimiento CC neto del proveedor es 0 (haber cancelado por debe).
             - cheque.estado == 'anulado'.
        """
        from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
        from app.services import ordenes_pago_service as ops

        op, cheque = self._crear_op_con_cheque_propio(
            db,
            empresa_p=empresa_p,
            proveedor_p=proveedor_p,
            banco_p=banco_p,
            active_user=active_user,
            pedido_id=None,
            monto=Decimal("500000"),
            numero="ECH-ANUL-B-001",
        )

        # Precondición: hay un haber CC del cheque.
        movs_pre = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor_p.id,
                CCProveedorMovimiento.origen_tipo == "cheque",
            )
            .all()
        )
        assert len(movs_pre) == 1
        assert movs_pre[0].tipo == "haber"

        # Anular la OP.
        ops.anular(db, orden_pago_id=op.id, motivo="Test fix anular propio a cuenta", user_id=active_user.id)

        db.expire_all()

        # 1. Cheque anulado.
        db.refresh(cheque)
        assert cheque.estado == "anulado", f"El cheque propio debe quedar 'anulado', got '{cheque.estado}'"

        # 2. El neto CC del proveedor (haber - debe) es 0.
        movs_post = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor_p.id).all()
        neto = sum((Decimal(str(m.monto)) if m.tipo == "haber" else -Decimal(str(m.monto))) for m in movs_post)
        assert neto == Decimal("0"), f"El saldo neto CC debe ser 0 tras revertir, got {neto}"


class TestChequeConPedidoIdAnular:
    """Reversal de cheque propio via cheques_service.transicionar_cheque (no via anular OP)."""

    def _cheque_payload(self, banco_p, numero: str, monto: Decimal, pedido_id: int | None = None) -> dict:
        payload: dict = {
            "banco_empresa_id": banco_p.id,
            "chequera_id": None,
            "instrumento": "echeq",
            "numero": numero,
            "monto": monto,
            "moneda": "ARS",
            "fecha_emision": date(2026, 6, 19),
            "fecha_pago": date(2026, 6, 19),
        }
        if pedido_id is not None:
            payload["pedido_id"] = pedido_id
        return payload

    def test_anular_cheque_imputado_a_pedido_restaura_saldo(
        self, db, empresa_p, proveedor_p, caja_p, banco_p, pedido_1m, active_user
    ) -> None:
        """
        Cheque con pedido_id → pagar → saldo=0.
        Anular el cheque → saldo del pedido vuelve a la obligación pendiente.
        """
        from app.services import cheques_service
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido

        ch_payload = self._cheque_payload(banco_p, "ECH-P-004", Decimal("700000"), pedido_id=pedido_1m.id)

        ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor_p.id,
            empresa_id=empresa_p.id,
            moneda="ARS",
            monto_total=Decimal("1000000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_1m.id, "monto": Decimal("300000")}],
            caja_id=caja_p.id,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 19),
            creado_por_id=active_user.id,
            cheques=[ch_payload],
        )

        # After payment: saldo = 0
        assert calcular_saldo_pendiente_pedido(db, pedido_1m.id) == Decimal("0")

        # Anular el cheque
        cheque = db.query(Cheque).filter(Cheque.numero == "ECH-P-004").one()
        cheques_service.transicionar_cheque(
            db,
            cheque,
            "anular",
            usuario_id=active_user.id,
            motivo="Test reversal pedido",
            empresa_id=empresa_p.id,
        )

        # Saldo del pedido debe haberse restaurado al monto del cheque (700_000)
        saldo_post = calcular_saldo_pendiente_pedido(db, pedido_1m.id)
        assert saldo_post == Decimal("700000"), f"Se esperaba saldo=700000, got {saldo_post}"
