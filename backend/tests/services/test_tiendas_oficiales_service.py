"""`app.services.tiendas_oficiales`: resolving store ids by `clave`."""

from __future__ import annotations

import pytest

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.services.tiendas_oficiales import (
    StoreClaveNotConfigured,
    TPLINK_CLAVE,
    require_store_ids_for_clave,
    store_ids_for_clave,
)


def _stores(db) -> None:
    db.add_all(
        [
            MlTiendaOficial(store_id=2645, nombre="TP-Link", clave="tplink", activa=False),
            MlTiendaOficial(store_id=471846, nombre="TP-Link", clave="tplink"),
            MlTiendaOficial(store_id=57997, nombre="Gauss"),
            MlTiendaOficial(store_id=5, nombre="Otra", clave="otra"),
        ]
    )
    db.flush()


def test_returns_every_id_of_the_clave_including_inactive_sorted(db) -> None:
    _stores(db)
    # An inactive id still counts: sales under the old id keep belonging to the store.
    assert store_ids_for_clave(db, TPLINK_CLAVE) == [2645, 471846]


def test_unknown_clave_is_empty(db) -> None:
    _stores(db)
    assert store_ids_for_clave(db, "nada") == []


def test_require_returns_the_ids(db) -> None:
    _stores(db)
    assert require_store_ids_for_clave(db, "tplink") == [2645, 471846]


def test_require_fails_closed_with_a_clear_message_when_nothing_is_configured(db) -> None:
    with pytest.raises(StoreClaveNotConfigured) as exc:
        require_store_ids_for_clave(db, "tplink")
    assert "No hay tiendas configuradas con la clave tplink" in str(exc.value)
