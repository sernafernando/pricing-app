"""
Integration tests — routers/ml_bot.py `/admin-pending` endpoints (ML Bot
Phase B derive-to-admin lane, sdd/ml-bot-admin-pending, PR2).

Mirrors `tests/integration/test_ml_bot_messages_actions_router.py`'s
permission-fixture shape (`con_todos_los_permisos`/`sin_permisos`/
`_permiso_solo`) but on `ml_bot.admin_pending.ver`/`.gestionar` and the
`MlBotAdminPendingRequest.status` CAS lifecycle (`new` -> `in_progress` ->
`done`|`cancelled`, `in_progress` -> `new` on release).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.ml_bot_admin_pending_request import MlBotAdminPendingRequest

BASE = "/api/ml-bot"


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def sin_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


def _permiso_solo(permiso_ok: str):
    return patch(
        "app.services.permisos_service.PermisosService.tiene_permiso",
        side_effect=lambda self_or_user, *args, **kwargs: args[0] == permiso_ok if args else False,
    )


def _seed_pending(db, *, status="new", **overrides) -> MlBotAdminPendingRequest:
    defaults = dict(
        pack_id="PACK-1",
        buyer_id=1,
        request_type="invoice_cuit_change",
        source="bot_derived",
        raw_text="mi cuit es 20-14768351-1",
        extracted_cuit="20147683511",
        extracted_name="Juan Perez",
        cuit_valid=True,
        doc_mismatch=False,
        status=status,
    )
    defaults.update(overrides)
    row = MlBotAdminPendingRequest(**defaults)
    db.add(row)
    db.flush()
    return row


# ==========================================================================
# GET /admin-pending, GET /admin-pending/{id} — .ver
# ==========================================================================


class TestListAndGetRequireVerPermission:
    def test_list_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        _seed_pending(db)
        db.commit()
        r = client.get(f"{BASE}/admin-pending", headers=auth_headers)
        assert r.status_code == 403

    def test_get_detail_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        row = _seed_pending(db)
        db.commit()
        r = client.get(f"{BASE}/admin-pending/{row.id}", headers=auth_headers)
        assert r.status_code == 403

    def test_gestionar_alone_no_alcanza_para_ver_403(self, client, auth_headers, db) -> None:
        row = _seed_pending(db)
        db.commit()
        with _permiso_solo("ml_bot.admin_pending.gestionar"):
            r = client.get(f"{BASE}/admin-pending/{row.id}", headers=auth_headers)
        assert r.status_code == 403

    def test_list_con_permiso_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_pending(db)
        db.commit()
        r = client.get(f"{BASE}/admin-pending", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["requests"]) == 1

    def test_list_filters_by_status(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_pending(db, status="new", pack_id="PACK-A")
        _seed_pending(db, status="done", pack_id="PACK-B", resolved_cuit="20147683511")
        db.commit()
        r = client.get(f"{BASE}/admin-pending", params={"status": "done"}, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["requests"][0]["pack_id"] == "PACK-B"

    def test_get_inexistente_404(self, client, auth_headers, con_todos_los_permisos) -> None:
        r = client.get(f"{BASE}/admin-pending/999999", headers=auth_headers)
        assert r.status_code == 404


# ==========================================================================
# GET /admin-pending/{id} — suggested_ack_template
# ==========================================================================


class TestGetDetailReturnsSuggestedAckTemplate:
    def test_clean_cuit_no_mismatch_returns_ack_clean(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, cuit_valid=True, doc_mismatch=False)
        db.commit()
        r = client.get(f"{BASE}/admin-pending/{row.id}", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "se realizará el cambio" in body["suggested_ack_template"]

    def test_invalid_cuit_returns_ack_confirm(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, cuit_valid=False, doc_mismatch=False)
        db.commit()
        r = client.get(f"{BASE}/admin-pending/{row.id}", headers=auth_headers)
        assert r.status_code == 200
        assert "confirmes tu CUIT" in r.json()["suggested_ack_template"]

    def test_doc_mismatch_returns_ack_confirm(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, cuit_valid=True, doc_mismatch=True)
        db.commit()
        r = client.get(f"{BASE}/admin-pending/{row.id}", headers=auth_headers)
        assert r.status_code == 200
        assert "confirmes tu CUIT" in r.json()["suggested_ack_template"]

    def test_detail_includes_superseded_values(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        superseded = [
            {"cuit": "20111111112", "name": "Old Name", "at": "2026-01-01T00:00:00+00:00", "source": "bot_derived"}
        ]
        row = _seed_pending(db, superseded_values=superseded)
        db.commit()
        r = client.get(f"{BASE}/admin-pending/{row.id}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["superseded_values"] == superseded


# ==========================================================================
# POST /admin-pending — manual create — .gestionar
# ==========================================================================


class TestManualCreate:
    def test_sin_permiso_403(self, client, auth_headers, sin_permisos) -> None:
        r = client.post(f"{BASE}/admin-pending", json={"pack_id": "PACK-9"}, headers=auth_headers)
        assert r.status_code == 403

    def test_manual_create_source_manual(self, client, auth_headers, active_user, con_todos_los_permisos) -> None:
        r = client.post(
            f"{BASE}/admin-pending",
            json={
                "pack_id": "PACK-9",
                "buyer_id": 55,
                "raw_text": "mi cuit es 20-14768351-1",
                "extracted_cuit": "20147683511",
                "extracted_name": "Juan Perez",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["source"] == "manual"
        assert body["created_by"] == active_user.id
        assert body["status"] == "new"
        assert body["pack_id"] == "PACK-9"


# ==========================================================================
# POST /admin-pending/{id}/claim, /release — CAS — .gestionar
# ==========================================================================


class TestClaimRelease:
    def test_claim_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        row = _seed_pending(db, status="new")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/claim", headers=auth_headers)
        assert r.status_code == 403

    def test_claim_desde_new_200(self, client, auth_headers, db, active_user, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="new")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/claim", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "in_progress"
        assert body["claimed_by"] == active_user.id
        assert body["claimed_at"] is not None

    def test_claim_conflict_desde_in_progress_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="in_progress")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/claim", headers=auth_headers)
        assert r.status_code == 409

    def test_release_desde_in_progress_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="in_progress", claimed_by=1)
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/release", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "new"
        assert body["claimed_by"] is None

    def test_release_conflict_desde_new_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="new")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/release", headers=auth_headers)
        assert r.status_code == 409


# ==========================================================================
# POST /admin-pending/{id}/done — .gestionar, requires resolved_cuit
# ==========================================================================


class TestDoneRequiresResolvedCuit:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        row = _seed_pending(db, status="in_progress")
        db.commit()
        r = client.post(
            f"{BASE}/admin-pending/{row.id}/done", json={"resolved_cuit": "20147683511"}, headers=auth_headers
        )
        assert r.status_code == 403

    def test_empty_body_rejected(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="in_progress")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/done", json={}, headers=auth_headers)
        assert r.status_code == 422

    def test_empty_string_resolved_cuit_rejected(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="in_progress")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/done", json={"resolved_cuit": ""}, headers=auth_headers)
        assert r.status_code == 422

    def test_success_stamps_resolved_fields(
        self, client, auth_headers, db, active_user, con_todos_los_permisos
    ) -> None:
        row = _seed_pending(db, status="in_progress")
        db.commit()
        r = client.post(
            f"{BASE}/admin-pending/{row.id}/done", json={"resolved_cuit": "20-14768351-1"}, headers=auth_headers
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done"
        assert body["resolved_cuit"] == "20-14768351-1"
        assert body["resolved_cuit_valid"] is True
        assert body["resolved_by"] == active_user.id
        assert body["resolved_at"] is not None

    def test_invalid_resolved_cuit_flagged_not_autocorrected(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        row = _seed_pending(db, status="in_progress")
        db.commit()
        r = client.post(
            f"{BASE}/admin-pending/{row.id}/done", json={"resolved_cuit": "99-99999999-9"}, headers=auth_headers
        )
        assert r.status_code == 200
        body = r.json()
        assert body["resolved_cuit"] == "99-99999999-9"
        assert body["resolved_cuit_valid"] is False

    def test_conflict_desde_done_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="done", resolved_cuit="20147683511")
        db.commit()
        r = client.post(
            f"{BASE}/admin-pending/{row.id}/done", json={"resolved_cuit": "20147683511"}, headers=auth_headers
        )
        assert r.status_code == 409


# ==========================================================================
# POST /admin-pending/{id}/cancel — .gestionar
# ==========================================================================


class TestCancel:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        row = _seed_pending(db, status="new")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/cancel", json={"reason": "duplicado"}, headers=auth_headers)
        assert r.status_code == 403

    def test_cancel_desde_new_200(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="new")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/cancel", json={"reason": "duplicado"}, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "cancelled"
        assert body["cancel_reason"] == "duplicado"

    def test_reason_vacio_422(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="new")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/cancel", json={"reason": ""}, headers=auth_headers)
        assert r.status_code == 422

    def test_conflict_desde_done_409(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, status="done", resolved_cuit="20147683511")
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/cancel", json={"reason": "x"}, headers=auth_headers)
        assert r.status_code == 409


# ==========================================================================
# POST /admin-pending/{id}/enrich-afip — .gestionar
# ==========================================================================


class TestEnrichAfip:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        row = _seed_pending(db)
        db.commit()
        r = client.post(f"{BASE}/admin-pending/{row.id}/enrich-afip", headers=auth_headers)
        assert r.status_code == 403

    def test_enrich_updates_afip_fields(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, extracted_cuit="20147683511")
        db.commit()

        async def fake_enrich(cuit):
            return "enriched", {
                "afip_razon_social": "Juan Perez",
                "afip_condicion_iva": "Responsable Inscripto",
                "afip_domicilio": "Calle Falsa 123",
            }

        with patch("app.services.ml_messages.admin_pending_service._enrich_afip", side_effect=fake_enrich):
            r = client.post(f"{BASE}/admin-pending/{row.id}/enrich-afip", headers=auth_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["afip_status"] == "enriched"
        assert body["afip_razon_social"] == "Juan Perez"

    def test_enrich_never_raises_on_afip_failure(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        row = _seed_pending(db, extracted_cuit="20147683511")
        db.commit()

        async def fake_unavailable(cuit):
            return "unavailable", {}

        with patch("app.services.ml_messages.admin_pending_service._enrich_afip", side_effect=fake_unavailable):
            r = client.post(f"{BASE}/admin-pending/{row.id}/enrich-afip", headers=auth_headers)

        assert r.status_code == 200
        assert r.json()["afip_status"] == "unavailable"

    def test_enrich_on_terminal_row_is_noop_without_afip_call(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        # A done/cancelled row must not trigger an AFIP call; it returns the
        # row unchanged (idempotent no-op, not a 409).
        row = _seed_pending(db, status="done", afip_status="ok")
        db.commit()

        def boom(cuit):
            raise AssertionError("AFIP must not be called on a terminal row")

        with patch("app.services.ml_messages.admin_pending_service._enrich_afip", side_effect=boom):
            r = client.post(f"{BASE}/admin-pending/{row.id}/enrich-afip", headers=auth_headers)

        assert r.status_code == 200
        assert r.json()["afip_status"] == "ok"
