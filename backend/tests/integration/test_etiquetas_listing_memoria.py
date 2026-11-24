"""GET /api/etiquetas-envio without `page` streams its rows instead of building the whole reply in memory.

The plain list (every label of a date range, what "Envíos Flex" asks for) used to load every row, build one
pydantic model per row and let FastAPI copy it three more times; a large range peaked at about 8x the size of its
own reply (handoffs/drain-diagnostico.md). The reply's contract stays the same: the same JSON items, in the same
order, as the paginated shape. Invented data.
"""

from __future__ import annotations

import tracemalloc
from datetime import date, timedelta

import pytest

from app.models.etiqueta_envio import EtiquetaEnvio
from tests.integration.test_etiquetas_manual_endpoints import con_permiso_envios  # noqa: F401  fixture

BASE = "/api"
DESDE = date(2026, 10, 1)
CANTIDAD = 3000


def _etiquetas(db, cantidad: int) -> None:
    db.add_all(
        EtiquetaEnvio(
            shipping_id=f"9{n:09d}",
            fecha_envio=DESDE + timedelta(days=n % 40),
            es_manual=True,
            manual_receiver_name=f"Destinatario de prueba número {n}",
            manual_street_name="Avenida de los Inventados",
            manual_street_number=str(n),
            manual_zip_code="1900",
            manual_city_name="La Plata",
            manual_comment="Timbre roto, dejar en portería " * 4,
        )
        for n in range(cantidad)
    )
    db.flush()


@pytest.fixture
def muchas(db):
    _etiquetas(db, CANTIDAD)


def _rango(**extra) -> dict:
    return {"fecha_desde": DESDE.isoformat(), "fecha_hasta": (DESDE + timedelta(days=60)).isoformat(), **extra}


@pytest.mark.usefixtures("muchas", "con_permiso_envios")
def test_a_large_range_peaks_at_a_small_multiple_of_its_reply(client, auth_headers):
    client.get(f"{BASE}/etiquetas-envio", params=_rango(fecha_hasta=DESDE.isoformat()), headers=auth_headers)

    tracemalloc.start()
    try:
        r = client.get(f"{BASE}/etiquetas-envio", params=_rango(), headers=auth_headers)
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert r.status_code == 200, r.text
    assert len(r.json()) == CANTIDAD
    # The reply itself is held about three times (the server's buffer and the test client's copies of the body);
    # building it as rows + models + encoder copies took about 8x.
    assert pico < 4 * len(r.content), f"peak {pico / 2**20:.1f} MB for a {len(r.content) / 2**20:.1f} MB reply"


@pytest.mark.usefixtures("muchas", "con_permiso_envios")
def test_the_plain_list_is_the_paginated_items_in_the_same_order(client, auth_headers):
    lista = client.get(f"{BASE}/etiquetas-envio", params=_rango(), headers=auth_headers)
    paginas = [
        client.get(f"{BASE}/etiquetas-envio", params=_rango(page=p, page_size=500), headers=auth_headers).json()
        for p in range(1, CANTIDAD // 500 + 1)
    ]

    assert lista.status_code == 200
    assert lista.headers["content-type"] == "application/json"
    assert [p["total"] for p in paginas] == [CANTIDAD] * len(paginas)
    assert lista.json() == [item for p in paginas for item in p["items"]]


@pytest.mark.usefixtures("con_permiso_envios")
def test_an_empty_range_is_an_empty_list(client, auth_headers):
    r = client.get(f"{BASE}/etiquetas-envio", params=_rango(), headers=auth_headers)

    assert (r.status_code, r.json()) == (200, [])
