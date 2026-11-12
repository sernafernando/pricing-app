"""
GET /precios/calcular-markup logs who calls it by item_code (temporary diagnostic).

One INFO line per item_code call with the caller's username, User-Agent, item_code and found/404.
No token or other header ever reaches the log. Calls by item_id log nothing.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from app.models.producto import ProductoERP

LOGGER = "app.api.endpoints.pricing"
UA = "Mozilla/5.0 (compatible; Google-Apps-Script; beanserver; +https://script.google.com)"


@pytest.fixture()
def producto(db) -> ProductoERP:
    p = ProductoERP(
        item_id=8101,
        codigo="7790001234567",
        descripcion="Producto log test",
        costo=50000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def comision(db):
    from datetime import date

    from app.models.comision_versionada import ComisionBase, ComisionVersion

    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    db.flush()
    return version


def _caller_lines(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and "calcular-markup caller" in r.getMessage()]


def _get(client, auth_headers, params):
    headers = {**auth_headers, "User-Agent": UA, "X-Secret": "do-not-log"}
    with patch("app.api.endpoints.pricing.resolver_costo_envio", return_value=1500.0):
        return client.get("/api/precios/calcular-markup", params=params, headers=headers)


def _assert_no_secrets(line: str, auth_headers: dict) -> None:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    assert token not in line
    assert "Bearer" not in line
    assert "do-not-log" not in line


def test_item_code_found_logs_one_info_line(client, auth_headers, producto, comision, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = _get(client, auth_headers, {"precio": 80000, "item_code": producto.codigo})

    assert response.status_code == 200, response.text
    lines = _caller_lines(caplog)
    assert len(lines) == 1
    record = lines[0]
    assert record.levelno == logging.INFO
    line = record.getMessage()
    assert "user=testuser" in line
    assert f"user_agent={UA!r}" in line
    assert f"item_code={producto.codigo!r}" in line
    assert "result=found" in line
    _assert_no_secrets(line, auth_headers)


def test_item_code_not_found_logs_404(client, auth_headers, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = _get(client, auth_headers, {"precio": 80000, "item_code": "ABC-NOT-EAN"})

    assert response.status_code == 404
    lines = _caller_lines(caplog)
    assert len(lines) == 1
    line = lines[0].getMessage()
    assert "user=testuser" in line
    assert f"user_agent={UA!r}" in line
    assert "item_code='ABC-NOT-EAN'" in line
    assert "result=404" in line
    _assert_no_secrets(line, auth_headers)


def test_item_id_call_logs_nothing(client, auth_headers, producto, comision, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = _get(client, auth_headers, {"precio": 80000, "item_id": producto.item_id})

    assert response.status_code == 200, response.text
    assert _caller_lines(caplog) == []
