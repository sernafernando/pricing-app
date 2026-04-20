"""
Mapeo empresa local ↔ (comp_id, bra_id) del ERP.

Este módulo concentra la traducción entre:
  - Empresa local (`empresas.id`) ← nuestro sistema
  - Company + Branch del ERP (`tb_commercial_transactions.comp_id/bra_id`)

Valores CONFIRMADOS por el usuario (2026-04-17):
  - Empresa 1 (sucursal principal) → (comp_id=1, bra_id=1)
  - Empresa 2 (Grupo Gauss)        → (comp_id=1, bra_id=45)

Los `bra_id` 35-42 son sucursales internas de transferencia (solo mueven
remitos entre depósitos, NO son empresas comerciales). Se ignoran con
log WARNING en `bra_a_empresa_o_ignorar`.

Cierre 3 del usuario (reemplaza D14 "hardcoded 1:1 v1" del design).
Referencia: COMPRAS-1.3 en tasks.md, state.yaml key_decisions.empresa_erp_mapping.
"""

from __future__ import annotations

from typing import Final, Optional

from app.core.logging import get_logger

logger = get_logger("core.compras_empresa_erp_map")


# ──────────────────────────────────────────────────────────────────────────
# Mapeos (dicts congelados por convención — no mutar en runtime)
# ──────────────────────────────────────────────────────────────────────────

EMPRESA_A_COMP_BRA_MAP: Final[dict[int, tuple[int, int]]] = {
    1: (1, 1),  # Empresa 1 → sucursal principal
    2: (1, 45),  # Empresa 2 → Grupo Gauss
}

COMP_BRA_A_EMPRESA: Final[dict[tuple[int, int], int]] = {
    (1, 1): 1,
    (1, 45): 2,
}


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def resolver_comp_bra(empresa_id: int) -> tuple[int, int]:
    """
    Traduce una empresa local a su (comp_id, bra_id) del ERP.

    Args:
        empresa_id: ID de la tabla `empresas` local.

    Returns:
        Tupla (comp_id, bra_id) según el mapeo configurado.

    Raises:
        KeyError: si `empresa_id` no está mapeado. El mensaje incluye la
            lista de empresas mapeadas para facilitar debugging.
    """
    try:
        return EMPRESA_A_COMP_BRA_MAP[empresa_id]
    except KeyError as exc:
        empresas_mapeadas = sorted(EMPRESA_A_COMP_BRA_MAP.keys())
        raise KeyError(
            f"empresa_id={empresa_id} no tiene mapeo en EMPRESA_A_COMP_BRA_MAP. "
            f"Empresas mapeadas: {empresas_mapeadas}. "
            f"Agregá el mapeo en app/core/compras_empresa_erp_map.py si corresponde."
        ) from exc


def bra_a_empresa_o_ignorar(comp_id: int, bra_id: int) -> Optional[int]:
    """
    Traduce (comp_id, bra_id) del ERP a una empresa local, si aplica.

    Diseñado para el hook de matching en `sync_commercial_transactions_guid.py`:
    muchas ct tienen `bra_id` 35-42 (sucursales internas de transferencia) que
    NO son empresas comerciales nuestras — se ignoran silenciosamente.

    Args:
        comp_id: Company ID del ERP.
        bra_id: Branch ID del ERP.

    Returns:
        `empresa_id` si `(comp_id, bra_id)` está mapeado.
        `None` si NO está mapeado (log WARNING para telemetría).
    """
    empresa_id = COMP_BRA_A_EMPRESA.get((comp_id, bra_id))
    if empresa_id is None:
        logger.warning(
            "ct con comp_id=%d bra_id=%d no mapea a empresa local — ignorada",
            comp_id,
            bra_id,
        )
    return empresa_id
