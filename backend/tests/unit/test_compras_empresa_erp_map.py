"""
Unit tests para `app.core.compras_empresa_erp_map`.

Cubre los 6 casos declarados en el acceptance criteria de COMPRAS-1.3:
  - resolver_comp_bra(1) → (1, 1)
  - resolver_comp_bra(2) → (1, 45)
  - resolver_comp_bra(99) → raise KeyError
  - bra_a_empresa_o_ignorar(1, 1) → 1
  - bra_a_empresa_o_ignorar(1, 45) → 2
  - bra_a_empresa_o_ignorar(1, 35) → None + log WARNING
  - bra_a_empresa_o_ignorar(1, 999) → None + log WARNING
"""

from __future__ import annotations

import logging

import pytest

from app.core.compras_empresa_erp_map import (
    COMP_BRA_A_EMPRESA,
    EMPRESA_A_COMP_BRA_MAP,
    bra_a_empresa_o_ignorar,
    resolver_comp_bra,
)


class TestResolverCompBra:
    """Tests para resolver_comp_bra(empresa_id)."""

    def test_empresa_1_retorna_comp_1_bra_1(self) -> None:
        assert resolver_comp_bra(1) == (1, 1)

    def test_empresa_2_retorna_comp_1_bra_45(self) -> None:
        assert resolver_comp_bra(2) == (1, 45)

    def test_empresa_no_mapeada_raises_keyerror(self) -> None:
        with pytest.raises(KeyError) as exc_info:
            resolver_comp_bra(99)

        # Mensaje informativo: debe incluir la lista de empresas mapeadas
        mensaje: str = str(exc_info.value)
        assert "99" in mensaje
        assert "no tiene mapeo" in mensaje
        # La lista de empresas mapeadas actuales
        assert "1" in mensaje
        assert "2" in mensaje


class TestBraAEmpresaOIgnorar:
    """Tests para bra_a_empresa_o_ignorar(comp_id, bra_id)."""

    def test_comp_1_bra_1_retorna_empresa_1(self) -> None:
        assert bra_a_empresa_o_ignorar(1, 1) == 1

    def test_comp_1_bra_45_retorna_empresa_2(self) -> None:
        assert bra_a_empresa_o_ignorar(1, 45) == 2

    def test_bra_35_sucursal_transferencia_retorna_none_con_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        # El logger vive bajo el namespace "app" que tiene propagate=False
        # (ver app/core/logging.py). Enganchamos el handler de caplog
        # directamente al logger objetivo para capturar los records.
        target_logger = logging.getLogger("app.core.compras_empresa_erp_map")
        target_logger.addHandler(caplog.handler)
        target_logger.setLevel(logging.WARNING)

        try:
            resultado = bra_a_empresa_o_ignorar(1, 35)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert resultado is None
        assert any("comp_id=1" in r.getMessage() and "bra_id=35" in r.getMessage() for r in caplog.records), (
            f"No se emitió log WARNING con comp_id=1 bra_id=35. Records: {caplog.records}"
        )

    def test_bra_999_no_mapeado_retorna_none_con_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        target_logger = logging.getLogger("app.core.compras_empresa_erp_map")
        target_logger.addHandler(caplog.handler)
        target_logger.setLevel(logging.WARNING)

        try:
            resultado = bra_a_empresa_o_ignorar(1, 999)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert resultado is None
        assert any("bra_id=999" in r.getMessage() for r in caplog.records), (
            f"No se emitió log WARNING con bra_id=999. Records: {caplog.records}"
        )


class TestMapaConsistencia:
    """Sanity checks sobre los dicts declarativos — si alguien agrega una
    empresa, debe agregar el mapeo inverso también."""

    def test_mapa_directo_e_inverso_son_consistentes(self) -> None:
        """Todo (comp_id, bra_id) debe derivarse de alguna empresa_id."""
        for empresa_id, (comp_id, bra_id) in EMPRESA_A_COMP_BRA_MAP.items():
            assert COMP_BRA_A_EMPRESA[(comp_id, bra_id)] == empresa_id, (
                f"Inconsistencia: empresa_id={empresa_id} mapea a "
                f"({comp_id}, {bra_id}) en directo pero el inverso "
                f"retorna {COMP_BRA_A_EMPRESA.get((comp_id, bra_id))}"
            )

    def test_tamaños_de_mapas_coinciden(self) -> None:
        """El mapa directo y el inverso deben tener el mismo size."""
        assert len(EMPRESA_A_COMP_BRA_MAP) == len(COMP_BRA_A_EMPRESA)
