"""
S5 — reserve applicable propio cheques at OP creation time (create-without-pay).

Gap closed: `OrdenPagoCreate` declared `cheques` but `crear_orden_pago` never
forwarded it to any reservation logic — a pre-existing propio cheque selected
in the modal was silently dropped when the user created a PENDIENTE OP
without paying immediately. Design ADR-2 said the router should orchestrate
`crear()` followed by N x `reservar_cheque_propio_en_op` in the same
transaction; this slice implements that orchestration.

Only ONE of the three `cheques` entry kinds is reservable on this path:
  1. Pre-existing propio (`cheque_id` set, `tipo == 'propio'`)  -> RESERVED.
  2. New propio to be emitted (`cheque_id` is None)             -> 422.
  3. Tercero endorsement (`cheque_id` set, `tipo == 'tercero'`) -> 422
     (rejected by the shared `_validar_propio_aplicable` guard reused from
     `reservar_cheque_propio_en_op` — no new validation logic duplicated).

`crear_y_pagar` is NEVER touched by this slice — it must keep handing
`cheques` straight to `ejecutar_pago` untouched, or S3b's merge step would
find an already-reserved link and 422 on a legitimate flow (double link).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from app.models.banco_empresa import BancoEmpresa
from app.models.cheque import OrdenPagoCheque
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import cheques_service, ordenes_pago_service

BASE = "/api/administracion/compras"


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaChequeReservaAlCrearS5", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="ProveedorChequeReservaAlCrearS5",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=95555,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def otro_proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="OtroProveedorChequeReservaAlCrearS5",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=95556,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        banco="BancoChequeReservaAlCrearS5",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("500000"),
        saldo_actual=Decimal("500000"),
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


def _cheque_propio(db, *, numero: str, banco_empresa_id: int, proveedor_id: int | None = None) -> "Any":  # noqa: ANN401
    return cheques_service.emitir_cheque_propio(
        db,
        tipo="propio",
        instrumento="echeq",
        numero=numero,
        monto=Decimal("20000"),
        moneda="ARS",
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 6, 22),
        banco_empresa_id=banco_empresa_id,
        proveedor_id=proveedor_id,
    )


def _cheque_tercero(db, *, proveedor_id: int) -> "Any":  # noqa: ANN401,ARG001
    return cheques_service.recibir_cheque_tercero(
        db,
        banco_nombre="Banco Librador Tercero S5",
        cuit_librador="20111111112",
        librador_nombre="Librador Tercero S5",
        numero="TER-S5-0001",
        monto=Decimal("20000"),
        moneda="ARS",
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 7, 22),
    )


def _base_payload(empresa, proveedor) -> dict:
    return {
        "empresa_id": empresa.id,
        "proveedor_id": proveedor.id,
        "moneda": "ARS",
        "monto_total": "20000",
        "modo_imputacion": "especifica",
        "items": [{"tipo": "pago_a_cuenta", "id": None, "monto": "20000"}],
    }


def _base_payload_cubierta_por_cheque(empresa, proveedor) -> dict:
    """`a_cuenta` mode, no items — used when a reserved cheque fully covers
    monto_total, so the balance check (items + pago_a_cuenta + cheques ==
    monto_total) is satisfied by the cheque alone."""
    return {
        "empresa_id": empresa.id,
        "proveedor_id": proveedor.id,
        "moneda": "ARS",
        "monto_total": "20000",
        "modo_imputacion": "a_cuenta",
        "items": [],
    }


class TestReservaAlCrearPreexistente:
    def test_op_pendiente_con_propio_preexistente_crea_un_link_sin_cc_ni_imputacion(
        self, client, auth_headers, db, empresa, proveedor, banco, active_user, con_todos_los_permisos
    ) -> None:
        cheque = _cheque_propio(db, numero="P-S5-CREATE-1", banco_empresa_id=banco.id, proveedor_id=proveedor.id)
        db.commit()

        payload = _base_payload(empresa, proveedor)
        payload["cheques"] = [
            {"cheque_id": cheque.id, "monto": "20000", "moneda": "ARS"},
        ]
        r = client.post(f"{BASE}/ordenes-pago", headers=auth_headers, json=payload)
        assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
        op_id = r.json()["id"]

        links = db.query(OrdenPagoCheque).filter_by(cheque_id=cheque.id).all()
        assert len(links) == 1
        assert links[0].orden_pago_id == op_id

        db.refresh(cheque)
        assert cheque.orden_pago_id == op_id
        assert cheque.estado in ("emitido", "diferido")

        assert db.query(CCProveedorMovimiento).count() == 0
        assert db.query(Imputacion).count() == 0

    def test_reserva_luego_pago_compone_con_s3b_una_sola_imputacion_y_un_solo_link(
        self, client, auth_headers, db, empresa, proveedor, banco, active_user, con_todos_los_permisos
    ) -> None:
        """The single most important test in this slice: proves S5's
        create-time reservation and S3b's merge-step-at-pay-time compose
        correctly — no double link, exactly one imputation."""
        cheque = _cheque_propio(db, numero="P-S5-CREATE-2", banco_empresa_id=banco.id, proveedor_id=proveedor.id)
        db.commit()

        payload = _base_payload_cubierta_por_cheque(empresa, proveedor)
        payload["cheques"] = [
            {"cheque_id": cheque.id, "monto": "20000", "moneda": "ARS"},
        ]
        r = client.post(f"{BASE}/ordenes-pago", headers=auth_headers, json=payload)
        assert r.status_code == 201, r.text
        op_id = r.json()["id"]

        # monto_efectivo_op == 0 (the cheque covers the full total), so a
        # fuente is required by OrdenPagoEjecutarPago's pydantic validator
        # but contributes zero movement — banco_id here is inert plumbing,
        # not part of what this test proves.
        pago_payload = {"fecha_pago_real": "2026-06-23", "banco_id": banco.id}
        r2 = client.post(f"{BASE}/ordenes-pago/{op_id}/pagar", headers=auth_headers, json=pago_payload)
        assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text}"
        assert r2.json()["estado"] == "pagado"

        links = db.query(OrdenPagoCheque).filter_by(cheque_id=cheque.id).all()
        assert len(links) == 1, "Reservation + payment must compose into exactly one link row."
        # No pedido_id on this cheque (a_cuenta) -> _imputar_cheque_en_op's
        # Caso B path applies: a direct CC haber movement, not an Imputacion
        # row (Imputacion is only created for the pedido-destination Caso A
        # path). Exactly one CC movement is the composition proof here.
        assert db.query(CCProveedorMovimiento).filter_by(origen_tipo="cheque", origen_id=cheque.id).count() == 1, (
            "The cheque CC movement created at pay time must exist exactly once."
        )
        assert db.query(CCProveedorMovimiento).filter_by(proveedor_id=proveedor.id).count() == 1

    def test_reserva_fallida_hace_rollback_completo_de_la_op(
        self, client, auth_headers, db, empresa, proveedor, otro_proveedor, banco, active_user, con_todos_los_permisos
    ) -> None:
        """A cheque already reserved on ANOTHER op must roll back the whole
        creation — no orphaned OrdenPago row left behind."""
        cheque = _cheque_propio(db, numero="P-S5-CREATE-3", banco_empresa_id=banco.id, proveedor_id=proveedor.id)
        db.commit()

        # Pre-reserve it on a different pendiente OP via the existing S3b endpoint.
        payload_previa = _base_payload(empresa, proveedor)
        r_previa = client.post(f"{BASE}/ordenes-pago", headers=auth_headers, json=payload_previa)
        assert r_previa.status_code == 201, r_previa.text
        op_previa_id = r_previa.json()["id"]
        r_reserva = client.post(
            f"{BASE}/ordenes-pago/{op_previa_id}/cheques",
            headers=auth_headers,
            json={"cheque_id": cheque.id, "monto": "20000", "moneda": "ARS"},
        )
        assert r_reserva.status_code == 201, r_reserva.text

        numero_antes = db.query(OrdenPago).count()

        payload = _base_payload(empresa, proveedor)
        payload["cheques"] = [
            {"cheque_id": cheque.id, "monto": "20000", "moneda": "ARS"},
        ]
        r = client.post(f"{BASE}/ordenes-pago", headers=auth_headers, json=payload)
        assert r.status_code == 409, f"Expected 409 (already reserved elsewhere), got {r.status_code}: {r.text}"

        assert db.query(OrdenPago).count() == numero_antes, "Failed reservation must roll back the whole OP creation."


class TestKindsNoReservables:
    def test_propio_nuevo_a_emitir_422_nombra_lo_no_soportado(
        self, client, auth_headers, db, empresa, proveedor, banco, active_user, con_todos_los_permisos
    ) -> None:
        payload = _base_payload(empresa, proveedor)
        payload["cheques"] = [
            {
                "banco_empresa_id": banco.id,
                "instrumento": "echeq",
                "numero": "NUEVO-S5-0001",
                "monto": "20000",
                "moneda": "ARS",
                "fecha_emision": "2026-06-22",
                "fecha_pago": "2026-06-22",
            }
        ]
        r = client.post(f"{BASE}/ordenes-pago", headers=auth_headers, json=payload)
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
        body = r.json()
        detail = body.get("detail") or body.get("error", {}).get("message", "")
        assert "pagar" in detail.lower() or "pagá" in detail.lower()

        assert db.query(OrdenPago).count() == 0, "Rejected emission must not leave an orphaned OP."

    def test_tercero_a_endosar_422_nombra_lo_no_soportado(
        self, client, auth_headers, db, empresa, proveedor, banco, active_user, con_todos_los_permisos
    ) -> None:
        cheque = _cheque_tercero(db, proveedor_id=proveedor.id)
        db.commit()

        payload = _base_payload(empresa, proveedor)
        payload["cheques"] = [
            {"cheque_id": cheque.id, "monto": "20000", "moneda": "ARS"},
        ]
        r = client.post(f"{BASE}/ordenes-pago", headers=auth_headers, json=payload)
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

        assert db.query(OrdenPago).count() == 0, "Rejected endorsement must not leave an orphaned OP."

    def test_sin_cheques_comportamiento_sin_cambios(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_todos_los_permisos
    ) -> None:
        payload = _base_payload(empresa, proveedor)
        r = client.post(f"{BASE}/ordenes-pago", headers=auth_headers, json=payload)
        assert r.status_code == 201, r.text


class TestCrearYPagarRegresionNoReserva:
    """`crear_y_pagar` must stay UNCHANGED by this slice: it hands `cheques`
    straight to `ejecutar_pago` and must NEVER call
    `reservar_cheque_propio_en_op`, or S3b's merge step would find the link
    already reserved and 422 on the duplicate guard. Proves exactly one
    `OrdenPagoCheque` row per cheque for all three kinds: propio-new
    (emitted in the same tx), propio-preexisting (applied), and tercero
    (endorsed). Service-level, same pattern as
    tests/unit/test_crear_y_pagar_con_cheque.py."""

    def test_las_tres_variantes_de_cheque_crean_un_solo_link_cada_una(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        propio_preexistente = _cheque_propio(
            db, numero="P-S5-CYP-PRE", banco_empresa_id=banco.id, proveedor_id=proveedor.id
        )
        tercero = cheques_service.recibir_cheque_tercero(
            db,
            banco_nombre="Banco Librador CYP",
            cuit_librador="20222222223",
            librador_nombre="Librador CYP",
            numero="TER-S5-CYP-0001",
            monto=Decimal("20000"),
            moneda="ARS",
            fecha_emision=date(2026, 6, 22),
            fecha_pago=date(2026, 7, 22),
        )
        db.flush()

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("60000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 23),
            creado_por_id=active_user.id,
            cheques=[
                {
                    "banco_empresa_id": banco.id,
                    "instrumento": "echeq",
                    "numero": "P-S5-CYP-NUEVO",
                    "monto": Decimal("20000"),
                    "moneda": "ARS",
                    "fecha_emision": date(2026, 6, 22),
                    "fecha_pago": date(2026, 6, 22),
                },
                {
                    "cheque_id": propio_preexistente.id,
                    "monto": Decimal("20000"),
                    "moneda": "ARS",
                },
                {
                    "cheque_id": tercero.id,
                    "monto": Decimal("20000"),
                    "moneda": "ARS",
                },
            ],
        )

        assert op.estado == "pagado"

        links = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.orden_pago_id == op.id).all()
        assert len(links) == 3, "Expected exactly one link per cheque — no double-linking."

        # Each cheque_id among the three appears exactly once.
        cheque_ids_linkeados = [link.cheque_id for link in links]
        assert len(cheque_ids_linkeados) == len(set(cheque_ids_linkeados)), "A cheque was linked more than once."
        assert propio_preexistente.id in cheque_ids_linkeados
        assert tercero.id in cheque_ids_linkeados

        db.refresh(tercero)
        assert tercero.estado == "entregado"
        db.refresh(propio_preexistente)
        assert propio_preexistente.orden_pago_id == op.id
