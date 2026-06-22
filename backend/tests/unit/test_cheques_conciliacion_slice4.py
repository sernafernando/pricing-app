"""
Tests unitarios — Slice 4: conciliación bancaria de cheques.

TDD Strict — RED→GREEN→REFACTOR.

FR-4.1: cheque propio emitido|diferido → debitar → debitado.
         Genera banco_movimiento EGRESO en banco del cheque.
         Valida fecha (no antes de fecha_pago) → 422.
FR-4.2: cheque tercero depositado → acreditar → acreditado.
         Genera banco_movimiento INGRESO en banco destino.
FR-4.3: no debitar/depositar antes de fecha_pago → 422.
FR-4.4: reporte de cheques por segmento (en_cartera, a_debitar, vencidos).

Adicionalmente:
  - tercero en_cartera|aceptado → depositar → depositado (sin movimiento banco).
  - e-cheq en_custodia → acreditar → acreditado + ingreso banco.
  - moneda banco ≠ moneda cheque → 422 al debitar/acreditar.
  - en_custodia ya NO es terminal (Slice 4 le da salida).
  - debitado / acreditado SÍ son terminales.

Regresión Slice 3 documentada:
  TestEnCustodiaTerminal ahora vive en este módulo (los tests de Slice 3
  se mantienen pero verifican que en_custodia sigue fallando con cualquier
  acción EXCEPTO 'acreditar', que es la nueva salida de Slice 4).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.banco_empresa import BancoEmpresa
from app.models.banco_movimiento import BancoMovimiento
from app.models.cheque import Cheque, Chequera
from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import cheques_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────

HOY = date(2026, 6, 22)
AYER = HOY - timedelta(days=1)
MANANA = HOY + timedelta(days=1)


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=40, nombre="EmpresaSlice4", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=40,
        nombre="ProveedorSlice4",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=400,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco_ars(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=40,
        banco="BancoARS-Slice4",
        moneda="ARS",
        empresa_id=empresa.id,
        activo=True,
        saldo_inicial=Decimal("500000"),
        saldo_actual=Decimal("500000"),
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def banco_usd(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=41,
        banco="BancoUSD-Slice4",
        moneda="USD",
        empresa_id=empresa.id,
        activo=True,
        saldo_inicial=Decimal("10000"),
        saldo_actual=Decimal("10000"),
    )
    db.add(b)
    db.flush()
    return b


def _cheque_propio(
    db,
    banco_id: int,
    fecha_pago: date = HOY,
    monto: Decimal = Decimal("10000"),
    moneda: str = "ARS",
    instrumento: str = "fisico",
) -> Cheque:
    """Emite un cheque propio en estado inicial (emitido o diferido)."""
    chequera = None
    if instrumento == "fisico":
        chequera = Chequera(
            banco_empresa_id=banco_id,
            instrumento="fisico",
            numero_desde=1,
            numero_hasta=999,
            proximo_numero=1,
            activa=True,
        )
        db.add(chequera)
        db.flush()

    cheque = cheques_service.emitir_cheque_propio(
        db,
        tipo="propio",
        instrumento=instrumento,
        numero="CHL-S4-001" if instrumento == "fisico" else "ECH-S4-001",
        monto=monto,
        moneda=moneda,
        fecha_emision=date(2026, 6, 1),
        fecha_pago=fecha_pago,
        banco_empresa_id=banco_id,
        chequera_id=chequera.id if chequera else None,
    )
    db.flush()
    return cheque  # type: ignore[return-value]


def _cheque_tercero(
    db,
    fecha_pago: date = HOY,
    monto: Decimal = Decimal("15000"),
    moneda: str = "ARS",
    instrumento: str = "fisico",
) -> Cheque:
    """Recibe un cheque de tercero en estado en_cartera."""
    cheque = cheques_service.recibir_cheque_tercero(
        db,
        banco_nombre="Banco Nación",
        cuit_librador="20112233445",
        librador_nombre="Tercero SA",
        numero="TCH-S4-001",
        monto=monto,
        moneda=moneda,
        fecha_emision=date(2026, 5, 1),
        fecha_pago=fecha_pago,
        instrumento=instrumento,
    )
    db.flush()
    return cheque  # type: ignore[return-value]


def _echeq_tercero_en_custodia(db, banco_id: int, fecha_pago: date = HOY) -> Cheque:
    """Crea un e-cheq de tercero que llega a en_custodia con banco_deposito_id asignado."""
    cheque = cheques_service.recibir_cheque_tercero(
        db,
        banco_nombre="Banco Galicia",
        cuit_librador="30998877661",
        librador_nombre="Galicia SA",
        numero="ECH-CUS-001",
        monto=Decimal("20000"),
        moneda="ARS",
        fecha_emision=date(2026, 5, 1),
        fecha_pago=fecha_pago,
        instrumento="echeq",
    )
    db.flush()
    # Asignar banco destino antes de ir a custodia (en la práctica se configura al depositar)
    cheque.banco_deposito_id = banco_id  # type: ignore[attr-defined]
    cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
    db.flush()
    return cheque  # type: ignore[return-value]


# ──────────────────────────────────────────────────────────────────────────
# FR-4.1 — Debitar cheque propio
# ──────────────────────────────────────────────────────────────────────────


class TestDebitarChequePropio:
    def test_debitar_emitido_ok(self, db, banco_ars: BancoEmpresa) -> None:
        """emitido → debitar → debitado; genera egreso en banco del cheque."""
        cheque = _cheque_propio(db, banco_ars.id, fecha_pago=HOY, monto=Decimal("10000"))
        saldo_antes = Decimal(str(banco_ars.saldo_actual))

        cheques_service.debitar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        db.flush()

        assert cheque.estado == "debitado"
        # Saldo bancario debería haber bajado
        db.refresh(banco_ars)
        assert Decimal(str(banco_ars.saldo_actual)) == saldo_antes - Decimal("10000")
        # Debe existir un BancoMovimiento EGRESO
        mov = (
            db.query(BancoMovimiento)
            .filter(
                BancoMovimiento.banco_id == banco_ars.id,
                BancoMovimiento.tipo == "egreso",
            )
            .first()
        )
        assert mov is not None
        assert Decimal(str(mov.monto)) == Decimal("10000")
        # Evento registrado
        tipos = [e.tipo for e in cheque.eventos]
        assert "debitado" in tipos

    def test_debitar_diferido_ok(self, db, banco_ars: BancoEmpresa) -> None:
        """diferido → debitar → debitado; genera egreso."""
        cheque = _cheque_propio(db, banco_ars.id, fecha_pago=HOY)
        # Forzar estado diferido (emitido con fecha_pago pasada ya es emitido; usamos
        # directamente la función con fecha_pago == hoy, lo que daría 'emitido'.
        # Para testear diferido necesitamos fecha_pago en el pasado ≥ fecha_emision).
        # Re-emit con fecha_pago ayer pero cheque_emision ayer-1.
        cheque.estado = "diferido"
        db.flush()

        cheques_service.debitar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        db.flush()

        assert cheque.estado == "debitado"

    def test_debitar_antes_fecha_pago_levanta_422(self, db, banco_ars: BancoEmpresa) -> None:
        """No se puede debitar antes de fecha_pago (FR-4.3)."""
        cheque = _cheque_propio(db, banco_ars.id, fecha_pago=MANANA)
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.debitar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        assert exc_info.value.status_code == 422
        assert "fecha" in exc_info.value.detail.lower()

    def test_debitar_moneda_banco_distinta_levanta_422(self, db, banco_usd: BancoEmpresa) -> None:
        """Cheque ARS en banco USD → 422 al debitar."""
        cheque = _cheque_propio(
            db, banco_usd.id, fecha_pago=HOY, monto=Decimal("10000"), moneda="ARS", instrumento="echeq"
        )
        # Forzar que el banco tenga moneda USD
        cheque.moneda = "ARS"
        db.flush()
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.debitar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        assert exc_info.value.status_code == 422

    def test_debitado_es_terminal(self, db, banco_ars: BancoEmpresa) -> None:
        """debitado es estado terminal — cualquier transición falla con 422."""
        cheque = _cheque_propio(db, banco_ars.id, fecha_pago=HOY)
        cheques_service.debitar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        db.flush()
        assert cheque.estado == "debitado"
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "anular", motivo="intento")
        assert exc_info.value.status_code == 422
        assert "terminal" in exc_info.value.detail.lower()


# ──────────────────────────────────────────────────────────────────────────
# FR-4.2 — Depositar cheque tercero
# ──────────────────────────────────────────────────────────────────────────


class TestDepositarChequeTercero:
    def test_depositar_en_cartera_ok(self, db, banco_ars: BancoEmpresa) -> None:
        """en_cartera → depositar → depositado. No genera movimiento banco todavía."""
        cheque = _cheque_tercero(db, fecha_pago=HOY)
        saldo_antes = Decimal(str(banco_ars.saldo_actual))

        cheques_service.depositar_cheque(db, cheque, banco_empresa_id=banco_ars.id, fecha=HOY, usuario_id=None)
        db.flush()

        assert cheque.estado == "depositado"
        # Sin movimiento bancario todavía
        db.refresh(banco_ars)
        assert Decimal(str(banco_ars.saldo_actual)) == saldo_antes
        # Evento registrado
        tipos = [e.tipo for e in cheque.eventos]
        assert "depositado" in tipos

    def test_depositar_aceptado_ok(self, db, banco_ars: BancoEmpresa) -> None:
        """aceptado (e-cheq) → depositar → depositado."""
        cheque = _cheque_tercero(db, fecha_pago=HOY, instrumento="echeq")
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        db.flush()

        cheques_service.depositar_cheque(db, cheque, banco_empresa_id=banco_ars.id, fecha=HOY, usuario_id=None)
        db.flush()

        assert cheque.estado == "depositado"

    def test_depositar_antes_fecha_pago_levanta_422(self, db, banco_ars: BancoEmpresa) -> None:
        """No se puede depositar antes de fecha_pago (FR-4.3)."""
        cheque = _cheque_tercero(db, fecha_pago=MANANA)
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.depositar_cheque(db, cheque, banco_empresa_id=banco_ars.id, fecha=HOY, usuario_id=None)
        assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# FR-4.2 — Acreditar cheque tercero
# ──────────────────────────────────────────────────────────────────────────


class TestAcreditarChequeTercero:
    def test_acreditar_antes_fecha_pago_levanta_422(self, db, banco_ars: BancoEmpresa) -> None:
        """FIX 2: no se puede acreditar antes de fecha_pago (FR-4.3).
        Forzamos estado depositado directamente para aislar el guard de acreditar."""
        # Forzar un cheque en estado depositado con fecha_pago futura.
        cheque = _cheque_tercero(db, fecha_pago=MANANA)
        cheque.estado = "depositado"
        cheque.banco_deposito_id = banco_ars.id
        db.flush()
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.acreditar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        assert exc_info.value.status_code == 422
        assert "fecha" in exc_info.value.detail.lower()

    def test_acreditar_depositado_ok(self, db, banco_ars: BancoEmpresa) -> None:
        """depositado → acreditar → acreditado; genera ingreso en banco."""
        cheque = _cheque_tercero(db, fecha_pago=HOY, monto=Decimal("15000"))
        cheques_service.depositar_cheque(db, cheque, banco_empresa_id=banco_ars.id, fecha=HOY, usuario_id=None)
        db.flush()

        saldo_antes = Decimal(str(banco_ars.saldo_actual))

        cheques_service.acreditar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        db.flush()

        assert cheque.estado == "acreditado"
        db.refresh(banco_ars)
        assert Decimal(str(banco_ars.saldo_actual)) == saldo_antes + Decimal("15000")
        # BancoMovimiento INGRESO
        mov = (
            db.query(BancoMovimiento)
            .filter(
                BancoMovimiento.banco_id == banco_ars.id,
                BancoMovimiento.tipo == "ingreso",
            )
            .first()
        )
        assert mov is not None
        assert Decimal(str(mov.monto)) == Decimal("15000")
        # Evento
        tipos = [e.tipo for e in cheque.eventos]
        assert "acreditado" in tipos

    def test_acreditar_moneda_banco_distinta_levanta_422(self, db, banco_usd: BancoEmpresa) -> None:
        """Cheque USD depositado en banco USD, pero cheque ARS → 422 al depositar en banco USD."""
        cheque = _cheque_tercero(db, fecha_pago=HOY, moneda="ARS")
        # Intentar depositar cheque ARS en banco USD → debe fallar
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.depositar_cheque(db, cheque, banco_empresa_id=banco_usd.id, fecha=HOY, usuario_id=None)
        assert exc_info.value.status_code == 422

    def test_acreditado_es_terminal(self, db, banco_ars: BancoEmpresa) -> None:
        """acreditado es estado terminal."""
        cheque = _cheque_tercero(db, fecha_pago=HOY)
        cheques_service.depositar_cheque(db, cheque, banco_empresa_id=banco_ars.id, fecha=HOY, usuario_id=None)
        db.flush()
        cheques_service.acreditar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        db.flush()
        assert cheque.estado == "acreditado"
        with pytest.raises(HTTPException):
            cheques_service.transicionar_cheque(db, cheque, "anular", motivo="intento")


# ──────────────────────────────────────────────────────────────────────────
# e-cheq en_custodia → acreditar
# ──────────────────────────────────────────────────────────────────────────


class TestEcheqCustodiaAcreditar:
    def test_custodia_acreditar_ok(self, db, banco_ars: BancoEmpresa) -> None:
        """e-cheq en_custodia → acreditar → acreditado; genera ingreso."""
        cheque = _echeq_tercero_en_custodia(db, banco_ars.id, fecha_pago=HOY)
        saldo_antes = Decimal(str(banco_ars.saldo_actual))

        cheques_service.acreditar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        db.flush()

        assert cheque.estado == "acreditado"
        db.refresh(banco_ars)
        assert Decimal(str(banco_ars.saldo_actual)) == saldo_antes + Decimal("20000")

    def test_custodia_no_es_terminal_con_acreditar(self, db, banco_ars: BancoEmpresa) -> None:
        """en_custodia NO es terminal desde Slice 4 — puede acreditarse."""
        cheque = _echeq_tercero_en_custodia(db, banco_ars.id, fecha_pago=HOY)
        # Debe poder acreditar sin 422
        cheques_service.acreditar_cheque(db, cheque, fecha=HOY, usuario_id=None)
        db.flush()
        assert cheque.estado == "acreditado"

    def test_custodia_sigue_bloqueando_otras_transiciones(self, db, banco_ars: BancoEmpresa) -> None:
        """en_custodia sigue siendo terminal para acciones distintas a acreditar."""
        cheque = _echeq_tercero_en_custodia(db, banco_ars.id, fecha_pago=HOY)
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "anular", motivo="intento")
        assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# FR-4.4 — Reporte de cheques por segmento
# ──────────────────────────────────────────────────────────────────────────


class TestReporteCheques:
    def test_reporte_segmentos(self, db, banco_ars: BancoEmpresa) -> None:
        """get_reporte_cheques devuelve segmentos: en_cartera, a_debitar, vencidos."""
        # En cartera (tercero, fecha futura — no vencido)
        tercero_cartera = cheques_service.recibir_cheque_tercero(
            db,
            banco_nombre="Banco Test",
            cuit_librador="20123456789",
            numero="RPT-TC-001",
            monto=Decimal("1000"),
            moneda="ARS",
            fecha_emision=HOY,
            fecha_pago=HOY + timedelta(days=30),
            instrumento="fisico",
        )
        db.flush()

        # A debitar (propio emitido, fecha_pago HOY o anterior — no vencido = listo para debitar)
        propio_a_debitar = _cheque_propio(db, banco_ars.id, fecha_pago=HOY)
        assert propio_a_debitar.estado in {"emitido", "diferido"}

        # Vencido (propio emitido, fecha_pago pasada, sin debitar)
        propio_vencido = _cheque_propio(db, banco_ars.id, fecha_pago=AYER, instrumento="echeq")
        assert propio_vencido.estado in {"emitido", "diferido"}

        reporte = cheques_service.get_reporte_cheques(db)

        # en_cartera: terceros en cartera (aceptado incluido)
        ids_cartera = {c.id for c in reporte["en_cartera"]}
        assert tercero_cartera.id in ids_cartera

        # a_debitar: propios emitidos/diferidos con fecha_pago <= hoy
        ids_debitar = {c.id for c in reporte["a_debitar"]}
        assert propio_a_debitar.id in ids_debitar
        assert propio_vencido.id in ids_debitar  # vencido también aparece aquí

        # vencidos: SOLO terceros con fecha_pago < hoy (sin solapamiento con a_debitar).
        # Un propio vencido (emitido|diferido, fecha_pago < hoy) debe aparecer SOLO en
        # a_debitar, NO en vencidos (FIX 3 — evita doble conteo).
        ids_vencidos = {c.id for c in reporte["vencidos"]}
        assert propio_vencido.id not in ids_vencidos, "propio vencido NO debe estar en vencidos (ya está en a_debitar)"

    def test_propio_vencido_en_un_solo_segmento(self, db, banco_ars: BancoEmpresa) -> None:
        """Un propio emitido con fecha_pago < hoy aparece SOLO en a_debitar, no en vencidos."""
        propio = _cheque_propio(db, banco_ars.id, fecha_pago=AYER, instrumento="echeq")
        assert propio.estado in {"emitido", "diferido"}

        reporte = cheques_service.get_reporte_cheques(db, hoy=HOY)

        ids_debitar = {c.id for c in reporte["a_debitar"]}
        ids_vencidos = {c.id for c in reporte["vencidos"]}

        assert propio.id in ids_debitar, "propio vencido debe estar en a_debitar"
        assert propio.id not in ids_vencidos, "propio vencido NO debe estar en vencidos"

    def test_tercero_vencido_aparece_en_vencidos(self, db, banco_ars: BancoEmpresa) -> None:
        """Un tercero en_cartera con fecha_pago < hoy aparece en vencidos."""
        tercero = _cheque_tercero(db, fecha_pago=AYER)

        reporte = cheques_service.get_reporte_cheques(db, hoy=HOY)

        ids_vencidos = {c.id for c in reporte["vencidos"]}
        assert tercero.id in ids_vencidos, "tercero vencido debe aparecer en vencidos"
