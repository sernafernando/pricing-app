"""`GET /api/items-sin-mla/tiendas-oficiales` reads the admin-managed table
(it used to serve a hardcoded dict): active stores only, in `orden`."""

from __future__ import annotations

from app.models.ml_tienda_oficial import MlTiendaOficial


def test_serves_active_stores_from_the_table_in_order(db, client, auth_headers) -> None:
    db.add_all(
        [
            MlTiendaOficial(store_id=20, nombre="Segunda", orden=2),
            MlTiendaOficial(store_id=10, nombre="Primera", orden=1),
            MlTiendaOficial(store_id=30, nombre="Inactiva", orden=0, activa=False),
        ]
    )
    db.flush()

    resp = client.get("/api/items-sin-mla/tiendas-oficiales", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == [{"id": 10, "nombre": "Primera"}, {"id": 20, "nombre": "Segunda"}]
