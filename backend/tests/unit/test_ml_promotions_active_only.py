"""
Only ACTIVE publications are queried against ML for promotions
(owner decision, perf/productos-promos-first-load).

The ML publications store (`ml_items`) already knows each publication's status. Closed, paused,
under-review and inactive publications, gone ones and ones ML says never existed must not reach the
ml-webhook proxy for a promotions pull: `POST /promociones/item/{mla}/refresh` and the live
confirmation read short-circuit with a reason the panel shows in Spanish, and
`GET /promociones/item/{mla}` tells the panel up front (`motivo_sin_actualizacion`) so it does not
even ask. A publication the store has not seen yet keeps today's behaviour, and so does any failure
to read the store (fail-open: the store being unreachable must not disable the refresh button).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.ml_publications import MlItem
from app.models.usuario import Usuario
from app.services.ml_webhook_client import RefreshOutcome

MLA = "MLA123456789"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

MOTIVO_PAUSADA = "Publicación pausada: las promos se actualizan cuando se reactive"
MOTIVO_REVISION = "Publicación en revisión: las promos se actualizan cuando vuelva a estar activa"
MOTIVO_INACTIVA = "Publicación inactiva: las promos se actualizan cuando se reactive"
MOTIVO_CERRADA = "Publicación cerrada: no se consultan promociones en ML"
MOTIVO_BAJA = "Publicación dada de baja en ML: no se consultan promociones"
MOTIVO_NUNCA = "La publicación no existe en ML: no se consultan promociones"

NOT_ACTIVE = [
    ({"status": "paused"}, MOTIVO_PAUSADA),
    ({"status": "under_review"}, MOTIVO_REVISION),
    ({"status": "inactive"}, MOTIVO_INACTIVA),
    ({"status": "closed"}, MOTIVO_CERRADA),
    ({"status": "active", "gone_at": NOW}, MOTIVO_BAJA),
    ({"status": "closed", "gone_at": NOW}, MOTIVO_BAJA),
    ({"status": None, "never_existed": True}, MOTIVO_NUNCA),
]


@pytest.fixture
def client(db):
    user = Usuario()
    user.id = 1
    user.username = "tester"
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    permisos = MagicMock()
    permisos.tiene_permiso.return_value = True
    with patch("app.routers.ml_promotions.PermisosService", return_value=permisos):
        yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _store(db, **fields) -> None:
    db.add(MlItem(item_id=MLA, **fields))
    db.commit()


def _refresh(client):
    proxy = AsyncMock(return_value=RefreshOutcome(ok=True))
    with patch("app.routers.ml_promotions.ml_webhook_client.refresh_item_promotions", new=proxy):
        response = client.post(f"/api/promociones/item/{MLA}/refresh")
    return response, proxy


class TestRefreshSkipsWhatIsNotActive:
    @pytest.mark.parametrize(("fields", "motivo"), NOT_ACTIVE)
    def test_not_active_never_reaches_the_proxy(self, client, db, fields, motivo) -> None:
        _store(db, **fields)

        response, proxy = _refresh(client)

        proxy.assert_not_called()
        assert response.status_code == 200
        assert response.json() == {"ok": False, "motivo": motivo}

    def test_active_refreshes(self, client, db) -> None:
        _store(db, status="active", fetched_at=NOW)

        response, proxy = _refresh(client)

        proxy.assert_called_once_with(MLA)
        assert response.json() == {"ok": True, "motivo": None}

    def test_not_in_the_store_keeps_the_current_behaviour(self, client) -> None:
        response, proxy = _refresh(client)

        proxy.assert_called_once_with(MLA)
        assert response.json()["ok"] is True

    def test_store_row_without_a_status_yet_keeps_the_current_behaviour(self, client, db) -> None:
        _store(db)  # discovered, not fetched: status unknown, not marked gone

        _, proxy = _refresh(client)

        proxy.assert_called_once_with(MLA)

    def test_store_read_failure_is_fail_open(self, client, db) -> None:
        with patch.object(db, "query", side_effect=RuntimeError("store down")):
            _, proxy = _refresh(client)

        proxy.assert_called_once_with(MLA)


class TestConfirmationReadSkipsWhatIsNotActive:
    @pytest.mark.parametrize(("fields", "motivo"), NOT_ACTIVE)
    def test_not_active_never_reaches_the_proxy(self, client, db, fields, motivo) -> None:
        _store(db, **fields)
        live = AsyncMock(return_value=[])

        with patch("app.routers.ml_promotions.ml_webhook_client.get_item_promotions", new=live):
            response = client.get(f"/api/promociones/item/{MLA}/confirmacion-ml")

        live.assert_not_called()
        assert response.status_code == 200
        assert response.json() == {"sin_promos_confirmado": False, "promos_en_ml": None}

    def test_active_still_asks_ml(self, client, db) -> None:
        _store(db, status="active", fetched_at=NOW)
        live = AsyncMock(return_value=[])

        with patch("app.routers.ml_promotions.ml_webhook_client.get_item_promotions", new=live):
            response = client.get(f"/api/promociones/item/{MLA}/confirmacion-ml")

        live.assert_called_once()
        assert response.json()["sin_promos_confirmado"] is True


class TestReadTellsThePanelUpFront:
    def _get(self, client):
        with patch("app.routers.ml_promotions.fetch_item_promotions", return_value=[]):
            return client.get(f"/api/promociones/item/{MLA}")

    @pytest.mark.parametrize(("fields", "motivo"), NOT_ACTIVE)
    def test_not_active_carries_the_reason_and_still_serves_the_mirror(self, client, db, fields, motivo) -> None:
        _store(db, **fields)

        body = self._get(client).json()

        assert body["motivo_sin_actualizacion"] == motivo
        assert body["promotions"] == []

    def test_active_has_no_reason(self, client, db) -> None:
        _store(db, status="active", fetched_at=NOW)

        assert self._get(client).json()["motivo_sin_actualizacion"] is None

    def test_not_in_the_store_has_no_reason(self, client) -> None:
        assert self._get(client).json()["motivo_sin_actualizacion"] is None
