"""
Contrato del CLI de sincronización de proveedores (app.scripts.sync_suppliers).

Dos comportamientos que quedaron sin fijar cuando el sync pasó a la cadena
canónica de ProveedoresService:

- `main()` sale con exit code 1 ante `SyncEnCursoError`: el cron NO puede
  reportar como éxito una corrida que nunca persistió nada.
- El label del encabezado usa `is not None`, no truthiness: `--supp-id 0`
  consulta suppID=0 y el encabezado no puede mentir "toda la tabla".
"""

from unittest.mock import MagicMock, patch

import pytest

from app.scripts import sync_suppliers as cli
from app.services.proveedores_service import SyncEnCursoError

RESULTADO_OK = {
    "total_erp": 1,
    "insertados": 1,
    "actualizados": 0,
    "rma_insertados": 0,
    "vinculados_rma": 0,
}


def _service_mock(sync_desde_erp):
    """ProveedoresService(db) cuyo sync_desde_erp es la corutina dada."""
    instancia = MagicMock()
    instancia.sync_desde_erp = sync_desde_erp
    return MagicMock(return_value=instancia)


class TestMainExitCodes:
    def test_sync_en_curso_sale_con_exit_1(self, capsys):
        async def sync_bloqueado(supp_id=None):
            raise SyncEnCursoError("Ya hay una sincronización de proveedores en curso")

        with (
            patch.object(cli, "SessionLocal", MagicMock()),
            patch.object(cli, "ProveedoresService", _service_mock(sync_bloqueado)),
            patch.object(cli.sys, "argv", ["sync_suppliers"]),
        ):
            with pytest.raises(SystemExit) as excinfo:
                cli.main()

        assert excinfo.value.code == 1
        assert "Sincronización no ejecutada" in capsys.readouterr().out


class TestLabelSuppId:
    def test_supp_id_cero_no_dice_toda_la_tabla(self, capsys):
        async def sync_ok(supp_id=None):
            return RESULTADO_OK

        with patch.object(cli, "ProveedoresService", _service_mock(sync_ok)):
            cli.sync_full(MagicMock(), supp_id=0)

        salida = capsys.readouterr().out
        assert "supp_id=0" in salida
        assert "toda la tabla" not in salida

    def test_sin_supp_id_sigue_diciendo_toda_la_tabla(self, capsys):
        async def sync_ok(supp_id=None):
            return RESULTADO_OK

        with patch.object(cli, "ProveedoresService", _service_mock(sync_ok)):
            cli.sync_full(MagicMock(), supp_id=None)

        assert "toda la tabla" in capsys.readouterr().out
