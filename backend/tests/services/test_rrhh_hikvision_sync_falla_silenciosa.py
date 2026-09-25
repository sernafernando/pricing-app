"""Regresión: una falla total de lectura del dispositivo Hikvision no debe
reportarse como sync exitoso sin novedades.

Incidente real: el sync de las 10:00 del 2026-09-25 no pudo leer ningún
evento (3x HTTP 401) y sin embargo logueó "Sync completado: nuevas=0,
duplicadas=0, sin_empleado=0, errores=0" — indistinguible de un día sin
fichadas nuevas. El dispositivo vive en un repetidor WiFi saturado
(~2000ms de ping), así que estas fallas de lectura van a ser rutinarias.

Contrato esperado:
- Falla en la PRIMERA página (cero eventos leídos) → sync_fichadas debe
  levantar ConnectionError. Nada se persiste.
- Falla en una página POSTERIOR (al menos una página exitosa antes) →
  se conservan las fichadas ya leídas (son reales, el dedup por event_id
  hace que un re-sync sea seguro) pero el resultado queda marcado como
  lectura incompleta.
- Lectura completa → comportamiento sin cambios.
"""

from __future__ import annotations

import pytest

from app.models.rrhh_fichada import RRHHFichada
from app.services.rrhh_hikvision_client import HikvisionClient


def _make_client(db) -> HikvisionClient:
    client = HikvisionClient(db)
    # Evitar depender de variables de entorno HIKVISION_*: seteamos
    # directamente los atributos que _is_configured() revisa.
    client.host = "192.168.1.50"
    client.port = 80
    client.username = "admin"
    client.password = "secret"
    return client


def _evento(serial_no: str, employee_no: str = "42", time_str: str = "2026-09-25T10:00:00") -> dict:
    return {
        "serialNo": serial_no,
        "employeeNoString": employee_no,
        "time": time_str,
        "deviceName": "DS-K1T804AMF",
    }


def test_falla_en_primera_pagina_levanta_connection_error_y_no_persiste(db, monkeypatch):
    """Cero eventos leídos (falla ya en la página 0) → error explícito, sin filas."""
    client = _make_client(db)

    def _make_request_falla(method, path, json_body=None):
        raise ConnectionError("Hikvision respondió con error HTTP 401: unauthorized")

    monkeypatch.setattr(client, "_make_request", _make_request_falla)

    with pytest.raises(ConnectionError):
        client.sync_fichadas()

    assert db.query(RRHHFichada).count() == 0


def test_falla_en_pagina_posterior_conserva_eventos_y_marca_lectura_incompleta(db, monkeypatch):
    """Página 1 OK, página 2 falla → se guarda lo leído y se marca incompleto."""
    client = _make_client(db)

    responses = [
        {
            "AcsEvent": {
                "searchID": "evt-1",
                "totalMatches": 60,
                "responseStatusStrg": "MORE",
                "InfoList": [
                    _evento("serial-1", employee_no="42", time_str="2026-09-25T10:00:00"),
                    # Empleado distinto para no chocar con el dedup por proximidad
                    # (mismo empleado + <120s se considera la misma autenticación física).
                    _evento("serial-2", employee_no="43", time_str="2026-09-25T10:00:00"),
                ],
            }
        },
    ]
    call_count = {"n": 0}

    def _make_request_parcial(method, path, json_body=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return responses[0]
        raise ConnectionError("Hikvision respondió con error HTTP 401: unauthorized")

    monkeypatch.setattr(client, "_make_request", _make_request_parcial)

    resultado = client.sync_fichadas()

    assert db.query(RRHHFichada).count() == 2
    assert resultado["nuevas"] == 2
    assert resultado["lectura_completa"] is False
    assert resultado["error_lectura"] is not None


def test_lectura_completa_no_cambia_comportamiento(db, monkeypatch):
    """Regresión del happy path: todas las páginas OK → lectura_completa=True, error=None."""
    client = _make_client(db)

    def _make_request_ok(method, path, json_body=None):
        return {
            "AcsEvent": {
                "searchID": "evt-1",
                "totalMatches": 1,
                "responseStatusStrg": "OK",
                "InfoList": [_evento("serial-ok")],
            }
        }

    monkeypatch.setattr(client, "_make_request", _make_request_ok)

    resultado = client.sync_fichadas()

    assert db.query(RRHHFichada).count() == 1
    assert resultado["nuevas"] == 1
    assert resultado["lectura_completa"] is True
    assert resultado["error_lectura"] is None


def test_falla_total_no_produce_dict_de_exito_con_cero_errores(db, monkeypatch):
    """Guarda de regresión explícita: una falla total NUNCA debe devolver un
    resultado tipo {"nuevas": 0, ..., "errores": 0} indistinguible de éxito."""
    client = _make_client(db)

    def _make_request_falla(method, path, json_body=None):
        raise ConnectionError("Hikvision respondió con error HTTP 401: unauthorized")

    monkeypatch.setattr(client, "_make_request", _make_request_falla)

    resultado = None
    excepcion = None
    try:
        resultado = client.sync_fichadas()
    except ConnectionError as e:
        excepcion = e

    assert excepcion is not None, (
        "Una falla total de lectura debe levantar ConnectionError, nunca devolver silenciosamente un dict de resultado."
    )
    assert resultado is None
