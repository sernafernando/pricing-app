"""Changing a product's sell-in cost mode through the API (`POST /api/sell-in/productos/{item_id}/modos/vista-previa`
and `POST .../modos`): the mode's own permission, the backdating one, the preview's fingerprint, and the row that
lands in the history. The money itself is covered on Postgres (`test_modos_escritura_postgres`)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.producto import ProductoERP, TipoMoneda

BASE = "/api/sell-in/productos"
HOY = date.today()


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso) -> dict:
    grant_permiso(rol_admin, "productos.ver")
    grant_permiso(rol_admin, "sell_in.ver")
    return admin_auth_headers


@pytest.fixture()
def ponderador(rol_admin, lector, grant_permiso) -> dict:
    grant_permiso(rol_admin, "sell_in.costo_ponderado")
    return lector


@pytest.fixture()
def producto(db) -> int:
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", costo=100.0, moneda_costo=TipoMoneda.ARS))
    db.commit()
    return 4512


def _cuerpo(modo: str, desde: date) -> dict:
    return {"modo": modo, "desde": desde.isoformat()}
