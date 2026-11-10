"""Unit tests for Gestión Full plan reset (bulk wipe)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.auditoria import TipoAccion
from app.models.gestion_full_override import GestionFullOverride
from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.services.gestion_full.plan_reset import reset_planificacion


def test_reset_planificacion_deletes_both_tables_and_audits() -> None:
    db = MagicMock()
    override_q = MagicMock()
    ready_q = MagicMock()
    override_q.delete.return_value = 3
    ready_q.delete.return_value = 5

    def query_side_effect(model: type) -> MagicMock:
        if model is GestionFullOverride:
            return override_q
        if model is GestionFullPmReady:
            return ready_q
        raise AssertionError(f"unexpected model {model}")

    db.query.side_effect = query_side_effect
    usuario = SimpleNamespace(id=42)

    with patch("app.services.gestion_full.plan_reset.registrar") as reg:
        out = reset_planificacion(db, usuario=usuario)

    assert out == {"overrides_deleted": 3, "pm_ready_deleted": 5}
    override_q.delete.assert_called_once_with(synchronize_session=False)
    ready_q.delete.assert_called_once_with(synchronize_session=False)
    db.commit.assert_called_once()
    reg.assert_called_once()
    kwargs = reg.call_args.kwargs
    assert kwargs["tipo"] == TipoAccion.GESTION_FULL_PLAN_RESET
    assert kwargs["usuario_id"] == 42
    assert kwargs["masivo"] is True
    assert kwargs["productos_afectados"] == 8
    assert kwargs["despues"] == {"overrides_deleted": 3, "pm_ready_deleted": 5}
