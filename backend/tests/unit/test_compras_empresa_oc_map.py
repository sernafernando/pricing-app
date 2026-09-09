"""Unit tests for `app.core.compras_empresa_oc_map`."""

from __future__ import annotations

from app.core.compras_empresa_oc_map import EMPRESA_OC_MAP, sucursal_oc_para_empresa


class TestSucursalOcParaEmpresa:
    def test_empresa_1_pastoriza(self) -> None:
        assert sucursal_oc_para_empresa(1) == "PASTORIZA"

    def test_empresa_2_grupo_gauss(self) -> None:
        assert sucursal_oc_para_empresa(2) == "GRUPO GAUSS"

    def test_unmapped_returns_none(self) -> None:
        assert sucursal_oc_para_empresa(99) is None

    def test_map_has_only_locked_empresas(self) -> None:
        assert EMPRESA_OC_MAP == {1: "PASTORIZA", 2: "GRUPO GAUSS"}
