"""
S1 — HTTP-level regression: `cheques` payload wiring (R1).

Before this slice, `cheques` was silently dropped between the frontend
payload and `ordenes_pago_service` because:
  - the Pydantic request schemas never declared a `cheques` field, and
  - the router call sites never forwarded `cheques=` to the service.

These tests exercise the ROUTER/HTTP layer (not the service directly) to
prove the payload actually reaches the service. They mock the service
entrypoints to assert on the kwargs they receive, so they stay independent
of the full cheque-emission business logic (already covered by
test_crear_y_pagar_con_cheque.py).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.banco_empresa import BancoEmpresa
from app.models.empresa import Empresa
from app.models.orden_pago import OrdenPago
from app.models.proveedor import OrigenProveedor, Proveedor

BASE = "/api/administracion/compras"


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Data fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaChequePayloadWiring", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="ProveedorChequePayloadWiring",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=77777,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        banco="Banco Payload Wiring",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("500000"),
        saldo_actual=Decimal("500000"),
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def op_pendiente(db, empresa, proveedor, active_user) -> OrdenPago:
    """OP pendiente lista para pagar — solo se usa para PATCH /pagar."""
    import json  # noqa: PLC0415

    from sqlalchemy import text  # noqa: PLC0415

    from app.services.numeracion_service import generar_siguiente_numero  # noqa: PLC0415

    numero, _ = generar_siguiente_numero(db, tipo="orden_pago", empresa_id=empresa.id)
    op = OrdenPago(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("20000"),
        modo_imputacion="especifica",
        estado="pendiente",
        creado_por_id=active_user.id,
    )
    db.add(op)
    db.flush()
    db.execute(
        text(
            "INSERT INTO compras_eventos (tipo, entidad_tipo, entidad_id, payload, usuario_id)"
            " VALUES ('items_registrados', 'orden_pago', :op_id, :payload, :uid)"
        ),
        {
            "op_id": op.id,
            "payload": json.dumps({"items": [{"tipo": "pago_a_cuenta", "id": None, "monto": "20000"}]}),
            "uid": active_user.id,
        },
    )
    db.flush()
    return op


@pytest.fixture
def cheque_payload(banco) -> dict:
    """Payload de un cheque propio nuevo (emisión) — mismo shape que la
    fixture equivalente en test_crear_y_pagar_con_cheque.py."""
    return {
        "banco_empresa_id": banco.id,
        "chequera_id": None,
        "instrumento": "echeq",
        "numero": "ECH-WIRING-001",
        "monto": "20000",
        "moneda": "ARS",
        "fecha_emision": "2026-01-15",
        "fecha_pago": "2026-01-15",
    }


# ──────────────────────────────────────────────────────────────────────────
# Tests — POST /ordenes-pago/crear-y-pagar
# ──────────────────────────────────────────────────────────────────────────


class TestChequesForwardedCrearYPagar:
    def test_cheques_forwarded_to_service(
        self, client, auth_headers, db, empresa, proveedor, banco, cheque_payload, active_user, con_todos_los_permisos
    ) -> None:
        """R1: a non-empty `cheques` array in the crear-y-pagar body reaches
        `ordenes_pago_service.crear_y_pagar` as the `cheques=` kwarg."""
        with patch("app.routers.administracion_compras.ordenes_pago_service.crear_y_pagar") as mock_crear_y_pagar:
            mock_op = OrdenPago(
                id=1,
                numero="OP-WIRING-0001",
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto_total=Decimal("20000"),
                modo_imputacion="a_cuenta",
                estado="pagado",
                creado_por_id=active_user.id,
            )
            db.add(mock_op)
            db.flush()
            mock_crear_y_pagar.return_value = mock_op

            payload = {
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "20000",
                "modo_imputacion": "a_cuenta",
                "items": [{"tipo": "pago_a_cuenta", "id": None, "monto": "20000"}],
                "banco_id": banco.id,
                "fecha_pago_real": "2026-01-15",
                "cheques": [cheque_payload],
            }
            r = client.post(
                f"{BASE}/ordenes-pago/crear-y-pagar",
                headers=auth_headers,
                json=payload,
            )

            assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
            assert mock_crear_y_pagar.called, "Service was not invoked."
            _, kwargs = mock_crear_y_pagar.call_args
            assert "cheques" in kwargs, "`cheques` kwarg was never forwarded to the service — payload dropped."
            forwarded = kwargs["cheques"]
            assert len(forwarded) == 1
            assert forwarded[0]["numero"] == cheque_payload["numero"]
            assert forwarded[0]["banco_empresa_id"] == cheque_payload["banco_empresa_id"]
            assert Decimal(str(forwarded[0]["monto"])) == Decimal(cheque_payload["monto"])
            assert str(forwarded[0]["fecha_emision"]) == cheque_payload["fecha_emision"]

    def test_cheques_omitted_regression(
        self, client, auth_headers, db, empresa, proveedor, banco, active_user, con_todos_los_permisos
    ) -> None:
        """A request that omits `cheques` entirely must behave exactly as
        before: the service receives an empty list, not None or an error."""
        with patch("app.routers.administracion_compras.ordenes_pago_service.crear_y_pagar") as mock_crear_y_pagar:
            mock_op = OrdenPago(
                id=2,
                numero="OP-WIRING-0002",
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto_total=Decimal("15000"),
                modo_imputacion="a_cuenta",
                estado="pagado",
                creado_por_id=active_user.id,
            )
            db.add(mock_op)
            db.flush()
            mock_crear_y_pagar.return_value = mock_op

            payload = {
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "15000",
                "modo_imputacion": "a_cuenta",
                "items": [{"tipo": "pago_a_cuenta", "id": None, "monto": "15000"}],
                "banco_id": banco.id,
                "fecha_pago_real": "2026-01-15",
            }
            r = client.post(
                f"{BASE}/ordenes-pago/crear-y-pagar",
                headers=auth_headers,
                json=payload,
            )

            assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
            _, kwargs = mock_crear_y_pagar.call_args
            assert kwargs.get("cheques") == [], f"Expected empty list default, got {kwargs.get('cheques')!r}"


# ──────────────────────────────────────────────────────────────────────────
# Tests — POST /ordenes-pago/{op_id}/pagar
# ──────────────────────────────────────────────────────────────────────────


class TestChequesForwardedPagar:
    def test_cheques_forwarded_to_service(
        self, client, auth_headers, db, op_pendiente, banco, cheque_payload, con_todos_los_permisos
    ) -> None:
        """R1: a non-empty `cheques` array in the pagar body reaches
        `ordenes_pago_service.ejecutar_pago` as the `cheques=` kwarg."""
        with patch("app.routers.administracion_compras.ordenes_pago_service.ejecutar_pago") as mock_ejecutar_pago:
            mock_ejecutar_pago.return_value = op_pendiente

            payload = {
                "banco_id": banco.id,
                "fecha_pago_real": "2026-01-15",
                "cheques": [cheque_payload],
            }
            r = client.post(
                f"{BASE}/ordenes-pago/{op_pendiente.id}/pagar",
                headers=auth_headers,
                json=payload,
            )

            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
            assert mock_ejecutar_pago.called, "Service was not invoked."
            _, kwargs = mock_ejecutar_pago.call_args
            assert "cheques" in kwargs, "`cheques` kwarg was never forwarded to the service — payload dropped."
            forwarded = kwargs["cheques"]
            assert len(forwarded) == 1
            assert forwarded[0]["numero"] == cheque_payload["numero"]
            assert forwarded[0]["banco_empresa_id"] == cheque_payload["banco_empresa_id"]
            assert Decimal(str(forwarded[0]["monto"])) == Decimal(cheque_payload["monto"])
            assert str(forwarded[0]["fecha_emision"]) == cheque_payload["fecha_emision"]

    def test_cheques_omitted_regression(
        self, client, auth_headers, db, op_pendiente, banco, con_todos_los_permisos
    ) -> None:
        """A request that omits `cheques` entirely must behave exactly as
        before: the service receives an empty list, not None or an error."""
        with patch("app.routers.administracion_compras.ordenes_pago_service.ejecutar_pago") as mock_ejecutar_pago:
            mock_ejecutar_pago.return_value = op_pendiente

            payload = {
                "banco_id": banco.id,
                "fecha_pago_real": "2026-01-15",
            }
            r = client.post(
                f"{BASE}/ordenes-pago/{op_pendiente.id}/pagar",
                headers=auth_headers,
                json=payload,
            )

            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
            _, kwargs = mock_ejecutar_pago.call_args
            assert kwargs.get("cheques") == [], f"Expected empty list default, got {kwargs.get('cheques')!r}"


class TestPagoSinFuenteEsAlcanzablePorHTTP:
    """A fully cheque-covered OP needs no caja and no banco.

    `ejecutar_pago` has always supported that path, but the request schema
    demanded exactly one funding source, so the request died on a Pydantic 422
    before the service ever ran. The existing coverage called the service
    directly with `banco_id=None`, which is precisely why nobody noticed —
    the same blind spot that let the dropped `cheques` payload survive.
    """

    def test_pagar_sin_caja_ni_banco_llega_al_servicio(
        self, client, auth_headers, db, op_pendiente, con_todos_los_permisos
    ) -> None:
        with patch("app.routers.administracion_compras.ordenes_pago_service.ejecutar_pago") as mock_ejecutar_pago:
            mock_ejecutar_pago.return_value = op_pendiente

            r = client.post(
                f"{BASE}/ordenes-pago/{op_pendiente.id}/pagar",
                headers=auth_headers,
                json={"fecha_pago_real": "2026-01-15"},
            )

            assert r.status_code == 200, (
                f"A cheque-covered OP must be payable with no funding source; got {r.status_code}: {r.text}"
            )
            assert mock_ejecutar_pago.called, "the service never ran — the schema rejected the request"

    def test_caja_y_banco_juntos_siguen_siendo_422(
        self, client, auth_headers, db, op_pendiente, banco, con_todos_los_permisos
    ) -> None:
        """Relaxing the validator must not lose the mutual-exclusion rule."""
        r = client.post(
            f"{BASE}/ordenes-pago/{op_pendiente.id}/pagar",
            headers=auth_headers,
            json={"caja_id": 1, "banco_id": banco.id, "fecha_pago_real": "2026-01-15"},
        )
        assert r.status_code == 422, f"caja + banco together must still be rejected; got {r.status_code}"
