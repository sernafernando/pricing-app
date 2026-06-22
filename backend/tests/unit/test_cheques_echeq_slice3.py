"""
Tests unitarios — Slice 3: e-cheq (cheque electrónico).

TDD Strict — FR-3.1, FR-3.2:
  FR-3.1: instrumento='echeq' en propios y terceros; chequera OPCIONAL para e-cheq propio.
  FR-3.2: estados extra aceptado / rechazado_emision / en_custodia;
          acciones gateadas por instrumento=='echeq' (físico → 422);
          transiciones inválidas → 422.

Flujo e-cheq de tercero definido:
  en_cartera --[aceptar]--> aceptado
  en_cartera --[rechazar_emision]--> rechazado_emision
  aceptado   --[entregar]--> entregado
  aceptado   --[rechazar_emision]--> rechazado_emision
  aceptado   --[anular]--> anulado
  aceptado / en_cartera --[poner_en_custodia]--> en_custodia

Flujo e-cheq propio:
  emitido / diferido --[poner_en_custodia]--> en_custodia

Regresión:
  - físico (propio/tercero) NO puede ejecutar aceptar / rechazar_emision / poner_en_custodia.
  - Transiciones Slice 1/2 de físico siguen funcionando.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.banco_empresa import BancoEmpresa
from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import cheques_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=90, nombre="EmpresaSlice3", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=90,
        nombre="ProveedorSlice3",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=900,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=90,
        banco="BancoSlice3",
        moneda="ARS",
        empresa_id=empresa.id,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


def _echeq_tercero(db, numero: str = "ECH-T-001", monto: Decimal | None = None) -> object:
    """Crea un e-cheq de tercero en cartera."""
    return cheques_service.recibir_cheque_tercero(
        db,
        banco_nombre="Banco Nación",
        cuit_librador="20112233445",
        librador_nombre="Tercero SA",
        numero=numero,
        monto=monto or Decimal("100000"),
        moneda="ARS",
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 7, 22),
        instrumento="echeq",
    )


def _echeq_propio(db, banco_id: int, numero: str = "ECH-P-001", diferido: bool = False) -> object:
    """Crea un e-cheq propio sin chequera (número dado por el banco)."""
    fecha_emision = date(2026, 6, 22)
    fecha_pago = date(2026, 8, 22) if diferido else date(2026, 6, 22)
    return cheques_service.emitir_cheque_propio(
        db,
        tipo="propio",
        instrumento="echeq",
        numero=numero,
        monto=Decimal("50000"),
        moneda="ARS",
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        banco_empresa_id=banco_id,
        chequera_id=None,  # e-cheq propio SIN chequera
    )


def _fisico_propio(db, banco_id: int) -> object:
    """Crea un cheque físico propio con chequera."""
    from app.models.cheque import Chequera

    chequera = Chequera(
        banco_empresa_id=banco_id,
        instrumento="fisico",
        numero_desde=1,
        numero_hasta=100,
        proximo_numero=1,
        activa=True,
    )
    db.add(chequera)
    db.flush()
    return cheques_service.emitir_cheque_propio(
        db,
        tipo="propio",
        instrumento="fisico",
        numero="FIS-P-001",
        monto=Decimal("50000"),
        moneda="ARS",
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 6, 22),
        banco_empresa_id=banco_id,
        chequera_id=chequera.id,
    )


def _fisico_tercero(db) -> object:
    """Crea un cheque físico de tercero en cartera."""
    return cheques_service.recibir_cheque_tercero(
        db,
        banco_nombre="Banco Santander",
        cuit_librador="20998877665",
        numero="FIS-T-001",
        monto=Decimal("100000"),
        moneda="ARS",
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 7, 22),
        instrumento="fisico",
    )


# ──────────────────────────────────────────────────────────────────────────
# FR-3.1 — e-cheq propio sin chequera
# ──────────────────────────────────────────────────────────────────────────


class TestEcheqPropioSinChequera:
    def test_echeq_propio_sin_chequera_ok(self, db, banco) -> None:
        """Un e-cheq propio sin chequera_id se emite correctamente."""
        cheque = _echeq_propio(db, banco.id)
        db.flush()
        assert cheque.id is not None
        assert cheque.instrumento == "echeq"
        assert cheque.chequera_id is None
        assert cheque.estado in {"emitido", "diferido"}

    def test_echeq_propio_diferido_sin_chequera(self, db, banco) -> None:
        """Un e-cheq diferido sin chequera_id también es válido."""
        cheque = _echeq_propio(db, banco.id, numero="ECH-P-DIFER", diferido=True)
        db.flush()
        assert cheque.instrumento == "echeq"
        assert cheque.chequera_id is None
        assert cheque.estado == "diferido"

    def test_echeq_propio_numero_requerido_schema(self, db, banco) -> None:
        """El schema rechaza numero vacío para e-cheq propio (min_length=1)."""
        from pydantic import ValidationError
        from app.schemas.cheque import EmitirChequePropio

        with pytest.raises(ValidationError):
            EmitirChequePropio(
                banco_empresa_id=banco.id,
                instrumento="echeq",
                numero="",  # vacío → falla Pydantic min_length=1
                monto=Decimal("1000"),
                moneda="ARS",
                fecha_emision=date(2026, 6, 22),
                fecha_pago=date(2026, 6, 22),
            )

    def test_fisico_propio_sin_chequera_levanta_422(self, db, banco) -> None:
        """Un cheque físico propio sin chequera_id sigue siendo inválido."""
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.emitir_cheque_propio(
                db,
                tipo="propio",
                instrumento="fisico",
                numero="FIS-NO-CH",
                monto=Decimal("1000"),
                moneda="ARS",
                fecha_emision=date(2026, 6, 22),
                fecha_pago=date(2026, 6, 22),
                banco_empresa_id=banco.id,
                chequera_id=None,  # físico SIN chequera → 422
            )
        assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# FR-3.2 — Transiciones e-cheq tercero
# ──────────────────────────────────────────────────────────────────────────


class TestTransicionesEcheqTercero:
    def test_aceptar_en_cartera(self, db) -> None:
        """en_cartera --[aceptar]--> aceptado."""
        cheque = _echeq_tercero(db, numero="ECH-T-ACE-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        assert cheque.estado == "aceptado"

    def test_rechazar_emision_desde_en_cartera(self, db) -> None:
        """en_cartera --[rechazar_emision]--> rechazado_emision."""
        cheque = _echeq_tercero(db, numero="ECH-T-REJ-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "rechazar_emision", motivo="Rechazo bancario")
        assert cheque.estado == "rechazado_emision"

    def test_aceptado_entregar(self, db) -> None:
        """aceptado --[entregar]--> entregado."""
        cheque = _echeq_tercero(db, numero="ECH-T-ENT-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        cheques_service.transicionar_cheque(db, cheque, "entregar")
        assert cheque.estado == "entregado"

    def test_aceptado_rechazar_emision(self, db) -> None:
        """aceptado --[rechazar_emision]--> rechazado_emision."""
        cheque = _echeq_tercero(db, numero="ECH-T-REJ-002")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        assert cheque.estado == "aceptado"
        cheques_service.transicionar_cheque(db, cheque, "rechazar_emision", motivo="Fondos insuficientes post-accept")
        assert cheque.estado == "rechazado_emision"

    def test_aceptado_anular(self, db) -> None:
        """aceptado --[anular]--> anulado."""
        cheque = _echeq_tercero(db, numero="ECH-T-ANU-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        cheques_service.transicionar_cheque(db, cheque, "anular", motivo="Error en datos")
        assert cheque.estado == "anulado"

    def test_aceptado_poner_en_custodia(self, db) -> None:
        """aceptado --[poner_en_custodia]--> en_custodia."""
        cheque = _echeq_tercero(db, numero="ECH-T-CUS-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert cheque.estado == "en_custodia"

    def test_en_cartera_poner_en_custodia(self, db) -> None:
        """en_cartera --[poner_en_custodia]--> en_custodia (directo, sin aceptar)."""
        cheque = _echeq_tercero(db, numero="ECH-T-CUS-002")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert cheque.estado == "en_custodia"

    def test_rechazado_emision_es_terminal(self, db) -> None:
        """rechazado_emision es estado terminal — no permite más transiciones."""
        cheque = _echeq_tercero(db, numero="ECH-T-TERM-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "rechazar_emision")
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "aceptar")
        assert exc_info.value.status_code == 422

    def test_evento_registrado_en_aceptar(self, db) -> None:
        """La acción 'aceptar' registra evento en cheque_evento."""
        from app.models.cheque import ChequeEvento

        cheque = _echeq_tercero(db, numero="ECH-T-EVT-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        db.flush()
        eventos = db.query(ChequeEvento).filter(ChequeEvento.cheque_id == cheque.id).all()
        tipos = [e.tipo for e in eventos]
        assert "aceptado" in tipos, f"Esperaba evento 'aceptado', got {tipos}"


# ──────────────────────────────────────────────────────────────────────────
# FR-3.2 — Transiciones e-cheq propio (custodia)
# ──────────────────────────────────────────────────────────────────────────


class TestTransicionesEcheqPropio:
    def test_emitido_poner_en_custodia(self, db, banco) -> None:
        """emitido --[poner_en_custodia]--> en_custodia."""
        cheque = _echeq_propio(db, banco.id, numero="ECH-P-CUS-001")
        db.flush()
        assert cheque.estado == "emitido"
        cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert cheque.estado == "en_custodia"

    def test_diferido_poner_en_custodia(self, db, banco) -> None:
        """diferido --[poner_en_custodia]--> en_custodia."""
        cheque = _echeq_propio(db, banco.id, numero="ECH-P-CUS-002", diferido=True)
        db.flush()
        assert cheque.estado == "diferido"
        cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert cheque.estado == "en_custodia"


# ──────────────────────────────────────────────────────────────────────────
# FR-3.2 — Físico NO puede ejecutar acciones e-cheq
# ──────────────────────────────────────────────────────────────────────────


class TestFisicoNoEcheq:
    def test_fisico_propio_no_puede_aceptar(self, db, banco) -> None:
        """Cheque físico propio → aceptar → 422."""
        cheque = _fisico_propio(db, banco.id)
        db.flush()
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "aceptar")
        assert exc_info.value.status_code == 422

    def test_fisico_tercero_no_puede_aceptar(self, db) -> None:
        """Cheque físico tercero → aceptar → 422."""
        cheque = _fisico_tercero(db)
        db.flush()
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "aceptar")
        assert exc_info.value.status_code == 422

    def test_fisico_propio_no_puede_rechazar_emision(self, db, banco) -> None:
        """Cheque físico propio → rechazar_emision → 422."""
        cheque = _fisico_propio(db, banco.id)
        db.flush()
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "rechazar_emision")
        assert exc_info.value.status_code == 422

    def test_fisico_propio_no_puede_poner_en_custodia(self, db, banco) -> None:
        """Cheque físico propio → poner_en_custodia → 422."""
        cheque = _fisico_propio(db, banco.id)
        db.flush()
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert exc_info.value.status_code == 422

    def test_fisico_tercero_no_puede_poner_en_custodia(self, db) -> None:
        """Cheque físico tercero → poner_en_custodia → 422."""
        cheque = _fisico_tercero(db)
        db.flush()
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# Regresión Slice 1/2 — transiciones de físico no rotas
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# FIX 1 — en_custodia es terminal en Slice 3
# ──────────────────────────────────────────────────────────────────────────


class TestEnCustodiaTerminal:
    def test_en_custodia_bloquea_transiciones_invalidas(self, db, banco) -> None:
        """en_custodia bloquea transiciones no previstas (ej. anular) — 422 siempre.

        NOTE (Slice 4): en_custodia ya NO está en ESTADOS_TERMINALES porque Slice 4
        le agregó la salida 'acreditar'. Sin embargo, cualquier transición inválida
        desde en_custodia sigue devolviendo 422 (transición no registrada en el dict).
        Este test fue ajustado en Slice 4 para verificar el comportamiento correcto:
        el 422 sigue disparándose pero el mensaje es 'transición inválida' (no 'terminal').
        """
        cheque = _echeq_propio(db, banco.id, numero="ECH-P-CUTERM-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert cheque.estado == "en_custodia"
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "anular", motivo="Intento post-custodia")
        assert exc_info.value.status_code == 422
        # Desde Slice 4: en_custodia no es terminal, el error es 'transición inválida'
        assert "transición inválida" in exc_info.value.detail.lower() or "terminal" in exc_info.value.detail.lower()

    def test_en_custodia_tercero_bloquea_transiciones_invalidas(self, db) -> None:
        """en_custodia desde tercero e-cheq bloquea transiciones inválidas (ej. entregar)."""
        cheque = _echeq_tercero(db, numero="ECH-T-CUTERM-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        cheques_service.transicionar_cheque(db, cheque, "poner_en_custodia")
        assert cheque.estado == "en_custodia"
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "entregar")
        assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# FIX 2 — aceptar es OPCIONAL para e-cheq tercero; en_cartera→entregar OK
# ──────────────────────────────────────────────────────────────────────────


class TestEcheqTerceroEndosoOpcional:
    def test_echeq_tercero_en_cartera_se_puede_endosar_sin_aceptar(self, db) -> None:
        """e-cheq tercero en_cartera puede ir directo a entregado (endoso) sin aceptar."""
        cheque = _echeq_tercero(db, numero="ECH-T-ENDOSO-DIRECT-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "entregar")
        assert cheque.estado == "entregado"

    def test_echeq_tercero_aceptado_se_puede_endosar(self, db) -> None:
        """e-cheq tercero aceptado puede ir a entregado (endoso vía aceptar primero)."""
        cheque = _echeq_tercero(db, numero="ECH-T-ENDOSO-ACE-001")
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "aceptar")
        assert cheque.estado == "aceptado"
        cheques_service.transicionar_cheque(db, cheque, "entregar")
        assert cheque.estado == "entregado"


# ──────────────────────────────────────────────────────────────────────────
# FIX 3 — motivo requerido en rechazar_emision (schema Pydantic)
# ──────────────────────────────────────────────────────────────────────────


class TestMotivorequeridoRechazarEmision:
    def test_rechazar_emision_sin_motivo_levanta_validation_error(self) -> None:
        """TransicionEcheqRequest con rechazar_emision sin motivo → ValidationError."""
        from pydantic import ValidationError

        from app.schemas.cheque import TransicionEcheqRequest

        with pytest.raises(ValidationError) as exc_info:
            TransicionEcheqRequest(accion="rechazar_emision", motivo=None)
        assert "motivo" in str(exc_info.value).lower()

    def test_rechazar_emision_motivo_vacio_levanta_validation_error(self) -> None:
        """TransicionEcheqRequest con rechazar_emision + motivo='' → ValidationError."""
        from pydantic import ValidationError

        from app.schemas.cheque import TransicionEcheqRequest

        with pytest.raises(ValidationError):
            TransicionEcheqRequest(accion="rechazar_emision", motivo="")

    def test_rechazar_emision_con_motivo_ok(self) -> None:
        """TransicionEcheqRequest con rechazar_emision + motivo válido → OK."""
        from app.schemas.cheque import TransicionEcheqRequest

        req = TransicionEcheqRequest(accion="rechazar_emision", motivo="Rechazo bancario")
        assert req.accion == "rechazar_emision"
        assert req.motivo == "Rechazo bancario"

    def test_aceptar_sin_motivo_ok(self) -> None:
        """TransicionEcheqRequest con aceptar sin motivo → válido."""
        from app.schemas.cheque import TransicionEcheqRequest

        req = TransicionEcheqRequest(accion="aceptar")
        assert req.accion == "aceptar"
        assert req.motivo is None

    def test_poner_en_custodia_sin_motivo_ok(self) -> None:
        """TransicionEcheqRequest con poner_en_custodia sin motivo → válido."""
        from app.schemas.cheque import TransicionEcheqRequest

        req = TransicionEcheqRequest(accion="poner_en_custodia")
        assert req.accion == "poner_en_custodia"


class TestRegresionSlice12:
    def test_fisico_propio_anular_sigue_funcionando(self, db, banco) -> None:
        """Anular cheque físico propio sigue siendo válido."""
        cheque = _fisico_propio(db, banco.id)
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "anular", motivo="Regresión Slice 3")
        assert cheque.estado == "anulado"

    def test_fisico_tercero_rechazar_sigue_funcionando(self, db) -> None:
        """Rechazar cheque físico tercero sigue siendo válido."""
        cheque = _fisico_tercero(db)
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "rechazar")
        assert cheque.estado == "rechazado"

    def test_fisico_tercero_entregar_sigue_funcionando(self, db) -> None:
        """Entregar cheque físico tercero sigue siendo válido."""
        cheque = _fisico_tercero(db)
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "entregar")
        assert cheque.estado == "entregado"
