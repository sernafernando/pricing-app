"""
Mapeo empresa local → sucursal OC (Automations PASTORIZA / GRUPO GAUSS).

Nuevo mapa, no reutiliza `compras_empresa_erp_map` (comp_id/bra_id ERP).
Unmapped empresa_id → None; the Phase 3 worker persists error+acta and
does not call Gemini.

Locked values (design.md / explore):
  - Empresa 1 → PASTORIZA
  - Empresa 2 → GRUPO GAUSS
"""

from __future__ import annotations

from typing import Final, Optional

EMPRESA_OC_MAP: Final[dict[int, str]] = {
    1: "PASTORIZA",
    2: "GRUPO GAUSS",
}


def sucursal_oc_para_empresa(empresa_id: int) -> Optional[str]:
    """
    Translate a local `empresas.id` to the OC sucursal label.

    Returns:
        ``PASTORIZA`` or ``GRUPO GAUSS`` when mapped; ``None`` otherwise.
    """
    return EMPRESA_OC_MAP.get(empresa_id)
