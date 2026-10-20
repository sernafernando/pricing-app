"""Answer the combo readiness check on a mocked consultas session.

Excluding combos (the ranking default) first asks whether `combo_componentes`
has been synced (`app.services.combos.componentes.combos_disponibles`). The
consultas tests feed their mocked session canned results in call order, so
that extra query must be answered here and never consume one of them."""

from __future__ import annotations

from unittest.mock import MagicMock


def es_chequeo_de_combos(sql: str) -> bool:
    return "combo_componentes" in sql and "pe.item_id" not in sql


def con_chequeo_de_combos(mock_db: MagicMock, sincronizados: bool = True) -> MagicMock:
    """Wrap `mock_db.execute` so the readiness check answers `sincronizados`
    and every other call reaches the original canned results, in order.
    `mock_db.execute.call_args_list` still records every statement."""
    canned = mock_db.execute
    chequeo = MagicMock()
    chequeo.scalar.return_value = sincronizados

    def _execute(stmt, *args, **kwargs):
        return chequeo if es_chequeo_de_combos(str(stmt)) else canned(stmt, *args, **kwargs)

    mock_db.execute = MagicMock(side_effect=_execute)
    return mock_db
