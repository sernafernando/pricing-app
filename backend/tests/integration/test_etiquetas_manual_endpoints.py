"""Integration tests — "Mensaje para depósito" en envíos flex/manuales.

Covers:
  - POST /api/etiquetas-envio/desde-pedido (deposito_mensaje persistido)
  - POST /api/etiquetas-envio/manual-envio (deposito_mensaje persistido)
  - PUT  /api/etiquetas-envio/manual-envio/{shipping_id} (deposito_mensaje actualizado)
  - GET  /api/etiquetas-envio (grilla expone deposito_mensaje)
  - GUARDIÁN: el mensaje NUNCA se filtra al ZPL/enrichment de la etiqueta.

TDD: tests escritos ANTES de la implementación (Strict TDD mode activo).
Pattern basado en test_recepcion_deposito_endpoints.py.

Change: envios-mensaje-deposito
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.operador import Operador

BASE = "/api"


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_permiso_envios():
    """Patch PermisosService so envios_flex.subir_etiquetas + pedidos.crear_envio_flex + envios_flex.ver pass."""

    def _fake(self, user, codigo):
        return codigo in {
            "envios_flex.subir_etiquetas",
            "pedidos.crear_envio_flex",
            "envios_flex.ver",
            "envios_flex.cambiar_estado_manual",
        }

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={
                "envios_flex.subir_etiquetas",
                "pedidos.crear_envio_flex",
                "envios_flex.ver",
                "envios_flex.cambiar_estado_manual",
            },
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Domain fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def operador(db) -> Operador:
    op = Operador(pin="1234", nombre="Operador Test", activo=True)
    db.add(op)
    db.flush()
    return op


def _base_manual_payload(operador_id: int, deposito_mensaje: str | None = None) -> dict:
    payload = {
        "fecha_envio": str(date.today()),
        "receiver_name": "Juan Perez",
        "street_name": "Av Siempreviva",
        "street_number": "742",
        "zip_code": "1900",
        "city_name": "La Plata",
        "status": "ready_to_ship",
        "operador_id": operador_id,
    }
    if deposito_mensaje is not None:
        payload["deposito_mensaje"] = deposito_mensaje
    return payload


def _base_desde_pedido_payload(deposito_mensaje: str | None = None) -> dict:
    payload = {
        "fecha_envio": str(date.today()),
        "receiver_name": "Maria Lopez",
        "street_name": "Calle Falsa",
        "street_number": "123",
        "zip_code": "1000",
        "city_name": "CABA",
    }
    if deposito_mensaje is not None:
        payload["deposito_mensaje"] = deposito_mensaje
    return payload


# ──────────────────────────────────────────────────────────────────────────
# R2.1 — POST /etiquetas-envio/desde-pedido
# ──────────────────────────────────────────────────────────────────────────


class TestDesdePedidoEndpoint:
    def test_post_desde_pedido_persiste_deposito_mensaje(self, client, auth_headers, db, con_permiso_envios):
        payload = _base_desde_pedido_payload(deposito_mensaje="envolver en burbuja")
        r = client.post(f"{BASE}/etiquetas-envio/desde-pedido", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        shipping_id = r.json()["shipping_id"]

        etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
        assert etiqueta is not None
        assert etiqueta.manual_deposito_mensaje == "envolver en burbuja"

    def test_post_sin_deposito_mensaje_queda_null(self, client, auth_headers, db, con_permiso_envios):
        payload = _base_desde_pedido_payload()  # sin deposito_mensaje
        r = client.post(f"{BASE}/etiquetas-envio/desde-pedido", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        shipping_id = r.json()["shipping_id"]

        etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
        assert etiqueta.manual_deposito_mensaje is None

    def test_post_desde_pedido_string_vacio_normaliza_a_null(self, client, auth_headers, db, con_permiso_envios):
        payload = _base_desde_pedido_payload(deposito_mensaje="   ")
        r = client.post(f"{BASE}/etiquetas-envio/desde-pedido", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        shipping_id = r.json()["shipping_id"]

        etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
        assert etiqueta.manual_deposito_mensaje is None


# ──────────────────────────────────────────────────────────────────────────
# R2.2 — POST /etiquetas-envio/manual-envio
# ──────────────────────────────────────────────────────────────────────────


class TestManualEnvioEndpoint:
    def test_post_manual_envio_persiste_deposito_mensaje(self, client, auth_headers, db, operador, con_permiso_envios):
        payload = _base_manual_payload(operador.id, deposito_mensaje="cliente pidió sin factura visible")
        r = client.post(f"{BASE}/etiquetas-envio/manual-envio", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        shipping_id = r.json()["shipping_id"]

        etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
        assert etiqueta.manual_deposito_mensaje == "cliente pidió sin factura visible"

        # Auditoría incluye el nuevo campo
        from app.models.operador_actividad import OperadorActividad

        actividad = (
            db.query(OperadorActividad)
            .filter(OperadorActividad.accion == "crear_envio_manual")
            .order_by(OperadorActividad.id.desc())
            .first()
        )
        assert actividad is not None
        assert actividad.detalle.get("deposito_mensaje") == "cliente pidió sin factura visible"


# ──────────────────────────────────────────────────────────────────────────
# R2.4 / R2.5 — PUT /etiquetas-envio/manual-envio/{shipping_id}
# ──────────────────────────────────────────────────────────────────────────


class TestEditarEnvioManualEndpoint:
    def _crear_envio_manual(self, client, auth_headers, operador_id, deposito_mensaje=None):
        payload = _base_manual_payload(operador_id, deposito_mensaje=deposito_mensaje)
        r = client.post(f"{BASE}/etiquetas-envio/manual-envio", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        return r.json()["shipping_id"]

    def test_put_manual_envio_actualiza_deposito_mensaje(
        self, client, auth_headers, db, operador, con_permiso_envios
    ):
        operador_id = operador.id
        shipping_id = self._crear_envio_manual(client, auth_headers, operador_id, deposito_mensaje=None)

        payload = _base_manual_payload(operador_id, deposito_mensaje="revisar N° de serie")
        r = client.put(
            f"{BASE}/etiquetas-envio/manual-envio/{shipping_id}",
            json=payload,
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
        assert etiqueta.manual_deposito_mensaje == "revisar N° de serie"

    def test_put_manual_envio_borra_deposito_mensaje(self, client, auth_headers, db, operador, con_permiso_envios):
        operador_id = operador.id
        shipping_id = self._crear_envio_manual(client, auth_headers, operador_id, deposito_mensaje="nota previa")

        payload = _base_manual_payload(operador_id, deposito_mensaje="")
        r = client.put(
            f"{BASE}/etiquetas-envio/manual-envio/{shipping_id}",
            json=payload,
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
        assert etiqueta.manual_deposito_mensaje is None

    def test_put_manual_envio_reemplaza_valor_existente(self, client, auth_headers, db, operador, con_permiso_envios):
        """Transición valor→valor: el caso más común en uso real."""
        operador_id = operador.id
        shipping_id = self._crear_envio_manual(client, auth_headers, operador_id, deposito_mensaje="nota original")

        payload = _base_manual_payload(operador_id, deposito_mensaje="nota corregida")
        r = client.put(
            f"{BASE}/etiquetas-envio/manual-envio/{shipping_id}",
            json=payload,
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        db.expire_all()
        etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
        assert etiqueta.manual_deposito_mensaje == "nota corregida"


# ──────────────────────────────────────────────────────────────────────────
# R3.1 — GET /etiquetas-envio (grilla)
# ──────────────────────────────────────────────────────────────────────────


class TestGrillaEndpoint:
    def test_get_grilla_incluye_deposito_mensaje(self, client, auth_headers, db, operador, con_permiso_envios):
        payload = _base_manual_payload(operador.id, deposito_mensaje="nota de grilla")
        r = client.post(f"{BASE}/etiquetas-envio/manual-envio", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        shipping_id = r.json()["shipping_id"]

        r = client.get(f"{BASE}/etiquetas-envio", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()
        if isinstance(items, dict) and "items" in items:
            items = items["items"]

        row = next(i for i in items if i["shipping_id"] == shipping_id)
        assert row["deposito_mensaje"] == "nota de grilla"


# ──────────────────────────────────────────────────────────────────────────
# R4 — GUARDIÁN: exclusión de la etiqueta ZPL / enrichment (D2, invariante crítico)
# ──────────────────────────────────────────────────────────────────────────


class TestGuardianExclusionZpl:
    def test_GUARDIAN_enrichment_zpl_excluye_deposito_mensaje(
        self, client, auth_headers, db, operador, con_permiso_envios
    ):
        """El ZPL generado para un envío CON deposito_mensaje debe ser
        byte-a-byte idéntico al de un envío SIN deposito_mensaje (mismos
        demás datos), y NUNCA debe contener el texto del mensaje."""

        secret_text = "ESTO_NUNCA_DEBE_IMPRIMIRSE_EN_LA_ETIQUETA"
        operador_id = operador.id

        payload_con = _base_manual_payload(operador_id, deposito_mensaje=secret_text)
        r_con = client.post(f"{BASE}/etiquetas-envio/manual-envio", json=payload_con, headers=auth_headers)
        assert r_con.status_code == 200, r_con.text
        shipping_con = r_con.json()["shipping_id"]

        payload_sin = _base_manual_payload(operador_id, deposito_mensaje=None)
        r_sin = client.post(f"{BASE}/etiquetas-envio/manual-envio", json=payload_sin, headers=auth_headers)
        assert r_sin.status_code == 200, r_sin.text
        shipping_sin = r_sin.json()["shipping_id"]

        zpl_con = client.get(
            f"{BASE}/etiquetas-envio/{shipping_con}/etiqueta-manual",
            headers=auth_headers,
        )
        zpl_sin = client.get(
            f"{BASE}/etiquetas-envio/{shipping_sin}/etiqueta-manual",
            headers=auth_headers,
        )
        assert zpl_con.status_code == 200, zpl_con.text
        assert zpl_sin.status_code == 200, zpl_sin.text

        assert secret_text not in zpl_con.text

        # El único diff esperado es el shipping_id embebido en el QR_DATA
        # (identificador único de cada envío, no relacionado a deposito_mensaje).
        # Normalizamos ese shipping_id antes de comparar byte a byte el resto
        # del ZPL — si deposito_mensaje se filtrara a algún otro placeholder,
        # esta comparación lo detectaría.
        normalized_con = zpl_con.text.replace(shipping_con, "SHIPPING_ID")
        normalized_sin = zpl_sin.text.replace(shipping_sin, "SHIPPING_ID")
        assert normalized_con == normalized_sin

    def test_GUARDIAN_desde_pedido_zpl_excluye_deposito_mensaje(
        self, client, auth_headers, db, con_permiso_envios
    ):
        """Mismo invariante que el guardián de manual-envio, pero para el flujo
        desde-pedido: ese endpoint construye el payload por separado, así que
        necesita su propio guardián para que ambos caminos no diverjan."""

        secret_text = "SECRETO_DESDE_PEDIDO_NO_IMPRIMIR"

        payload_con = _base_desde_pedido_payload(deposito_mensaje=secret_text)
        r_con = client.post(f"{BASE}/etiquetas-envio/desde-pedido", json=payload_con, headers=auth_headers)
        assert r_con.status_code == 200, r_con.text
        shipping_con = r_con.json()["shipping_id"]

        payload_sin = _base_desde_pedido_payload(deposito_mensaje=None)
        r_sin = client.post(f"{BASE}/etiquetas-envio/desde-pedido", json=payload_sin, headers=auth_headers)
        assert r_sin.status_code == 200, r_sin.text
        shipping_sin = r_sin.json()["shipping_id"]

        zpl_con = client.get(f"{BASE}/etiquetas-envio/{shipping_con}/etiqueta-manual", headers=auth_headers)
        zpl_sin = client.get(f"{BASE}/etiquetas-envio/{shipping_sin}/etiqueta-manual", headers=auth_headers)
        assert zpl_con.status_code == 200, zpl_con.text
        assert zpl_sin.status_code == 200, zpl_sin.text

        assert secret_text not in zpl_con.text

        normalized_con = zpl_con.text.replace(shipping_con, "SHIPPING_ID")
        normalized_sin = zpl_sin.text.replace(shipping_sin, "SHIPPING_ID")
        assert normalized_con == normalized_sin
