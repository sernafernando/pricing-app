"""`GET /ventas-fuera-ml/operaciones` (the synced GBP rows) no longer shows sell in / sell out (VPF T4).

Since VPF T4 the engines credit the operations loaded from the GBP PDF reports, under canal `fuera` keyed by the PDF
line id (orchestrator, L20), so this screen leaves its sell in / sell out fields null instead of matching a synced
`it_transaction` against an unrelated PDF line. Postgres world from `tests.services.test_sell_in_out_ventas_postgres`.
Invented data only (the repo is public).
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.api.endpoints import ventas_fuera_ml
from app.core.database import get_db
from tests.services import test_sell_in_out_ventas_postgres as w
from tests.services.sell_in import _world as w_in

pytestmark = pytest.mark.postgres

NUEVOS = (
    "sell_in_ars",
    "sell_out_ars",
    "sell_out_estimado",
    "sell_in_estimado",
    "costo_con_sell_in",
    "ganancia_con_sell_in_out",
    "markup_con_sell_in_out",
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("ventas_fuera_sio") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(ventas_fuera_ml.router, prefix="/api")
    factory = sessionmaker(bind=engine)

    def db() -> Iterator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    with TestClient(app) as c:
        yield c


def _operaciones(client: TestClient) -> dict:
    response = client.get(
        "/api/ventas-fuera-ml/operaciones", params={"from_date": "2026-11-01", "to_date": "2026-11-30"}
    )
    assert response.status_code == 200, response.text
    return {op["id_operacion"]: op for op in response.json()}


def test_a_synced_row_never_shows_the_sell_in_out_of_the_pdf_line_with_its_id(
    engine: Engine, client: TestClient
) -> None:
    pdf = w.venta(engine)  # a PDF line, canal `fuera`
    w.sell_in(engine, w.compra_item(engine), pdf, "200.00")
    w.sell_out(engine, w.campana(engine), pdf, "100.00")
    gbp = w_in.venta(engine, "gbp", 2964, 2, w.DIA)
    w_in.update_venta(engine, "gbp", gbp, monto_total=1500, costo_total=1000, ganancia=500, markup_porcentaje=50)
    w_in.update_venta(engine, "gbp", gbp, it_transaction=pdf)  # a synced row with the PDF line's id

    op = _operaciones(client)[pdf]

    assert (op["costo_pesos_sin_iva"], op["ganancia"], op["markup"]) == (1000, 500, 0.5)
    assert {k: op[k] for k in NUEVOS} == dict.fromkeys(NUEVOS)
