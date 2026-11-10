"""Inventory / Código ML keys for Gestión Full.

Real Full SKUs use MercadoLibre ``inventory_id``. Rows that never entered Full
have no Código ML; we still need a stable override / package key, so we store
``NOINV:{user_product_id}``. Excel leaves Código ML blank for those synthetics.
"""

from __future__ import annotations

from typing import Optional

NOINV_PREFIX = "NOINV:"


def is_synthetic_inventory_id(inventory_id: Optional[str]) -> bool:
    return bool(inventory_id) and str(inventory_id).startswith(NOINV_PREFIX)


def synthetic_inventory_id(user_product_id: str) -> str:
    return f"{NOINV_PREFIX}{user_product_id}"


def package_inventory_id(
    inventory_id: Optional[str],
    *,
    user_product_id: str,
) -> str:
    """Key stored on override / ready / package lines."""
    if inventory_id:
        return str(inventory_id)
    return synthetic_inventory_id(user_product_id)


def excel_codigo_ml(inventory_id: Optional[str]) -> str:
    """Value for official ML Excel column C (empty when still without Código ML)."""
    if not inventory_id or is_synthetic_inventory_id(inventory_id):
        return ""
    return str(inventory_id)


def user_product_id_from_synthetic(inventory_id: str) -> Optional[str]:
    if not is_synthetic_inventory_id(inventory_id):
        return None
    mlau = inventory_id[len(NOINV_PREFIX) :]
    return mlau or None
