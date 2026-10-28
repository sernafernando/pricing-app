"""PARA GANAR periodicidad — normalize and validate subscription payloads."""

from __future__ import annotations

from typing import Any, Optional

from app.models.para_ganar_periodicidad import (
    SCOPE_ALL,
    SCOPE_MLAS,
    SCOPE_MODES,
    SCOPE_RULES,
)

KNOWN_TIPOS = frozenset({"clasica", "3", "6", "9", "12"})


def normalize_ean(raw: str) -> str:
    return (raw or "").strip()


def normalize_mla(raw: str) -> str:
    return (raw or "").strip().upper()


def normalize_tipos(raw: Optional[list[Any]]) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        token = str(item).strip().lower()
        if not token or token in seen:
            continue
        if token not in KNOWN_TIPOS:
            raise ValueError(f"tipo_publicacion inválido: {token}")
        seen.add(token)
        out.append(token)
    return out


def normalize_int_ids(raw: Optional[list[Any]], *, field: str) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero") from exc
        if value <= 0:
            raise ValueError(f"{field} debe ser > 0")
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def normalize_mla_list(raw: Optional[list[Any]]) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        mla = normalize_mla(str(item))
        if not mla or mla in seen:
            continue
        seen.add(mla)
        out.append(mla)
    return out


def validate_scope_payload(
    *,
    scope_mode: str,
    mlas: Optional[list[Any]],
    tipos_publicacion: Optional[list[Any]],
    pricelist_ids: Optional[list[Any]],
    tienda_oficial_ids: Optional[list[Any]],
) -> dict[str, Any]:
    """Return cleaned fields for persistence. Raises ValueError on bad input."""
    mode = (scope_mode or "").strip().lower()
    if mode not in SCOPE_MODES:
        raise ValueError(f"scope_mode inválido: {scope_mode}")

    mla_list = normalize_mla_list(mlas)
    tipos = normalize_tipos(tipos_publicacion)
    pricelists = normalize_int_ids(pricelist_ids, field="pricelist_ids")
    tiendas = normalize_int_ids(tienda_oficial_ids, field="tienda_oficial_ids")

    if mode == SCOPE_ALL:
        return {
            "scope_mode": SCOPE_ALL,
            "mlas": [],
            "tipos_publicacion": [],
            "pricelist_ids": [],
            "tienda_oficial_ids": [],
        }
    if mode == SCOPE_MLAS:
        if not mla_list:
            raise ValueError("scope_mode=mlas requiere al menos un MLA")
        return {
            "scope_mode": SCOPE_MLAS,
            "mlas": mla_list,
            "tipos_publicacion": [],
            "pricelist_ids": [],
            "tienda_oficial_ids": [],
        }
    # rules
    if not tipos and not pricelists and not tiendas:
        raise ValueError("scope_mode=rules requiere tipos_publicacion, pricelist_ids o tienda_oficial_ids")
    return {
        "scope_mode": SCOPE_RULES,
        "mlas": [],
        "tipos_publicacion": tipos,
        "pricelist_ids": pricelists,
        "tienda_oficial_ids": tiendas,
    }
