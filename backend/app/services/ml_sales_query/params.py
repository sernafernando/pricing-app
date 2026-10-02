"""Request-param parsing shared by the Ventas ML (`routers/ml_ventas_ops.py`)
and Métricas ML (`routers/ml_metricas.py`) routers: the CSV filter params
(brands, ids, official stores) with ONE contract -- trimmed, de-duplicated in
first-seen order, and an empty entry, a malformed token or an out-of-range
id is HTTP 422, never silently treated as "no filter"."""

from __future__ import annotations

from typing import Optional, Tuple

from fastapi import HTTPException, status

from app.services.ml_sales_query.filters import NO_STORE


def parse_csv_strings(raw: Optional[str], field: str) -> Tuple[str, ...]:
    """PFILT R35/T16a: CSV of brand names, deduplicated (order preserved).
    An empty entry (e.g. `"epson,,lexmark"` or a lone `","`) is HTTP 422,
    never silently dropped."""
    if not raw:
        return ()
    values: "list[str]" = []
    seen: set = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} contiene un valor vacío: {raw!r}",
            )
        key = value.upper()
        if key not in seen:
            seen.add(key)
            values.append(value)
    return tuple(values)


INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1


def parse_csv_ids(raw: Optional[str], field: str) -> Tuple[int, ...]:
    """PFILT R35/T16a: CSV of integer ids, deduplicated. A non-numeric id
    or an empty CSV entry is HTTP 422 (never treated as 'no filter')."""
    if not raw:
        return ()
    values: "list[int]" = []
    seen: set = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} contiene un valor vacío: {raw!r}",
            )
        try:
            parsed = int(value)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} inválido (esperado un entero): {value!r}",
            ) from e
        # An INT column raises a DataError on an out-of-range value, which
        # would surface as a 500 instead of the 422 the contract promises.
        if not (INT32_MIN <= parsed <= INT32_MAX):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} contiene un id fuera de rango: {value!r}",
            )
        if parsed not in seen:
            seen.add(parsed)
            values.append(parsed)
    return tuple(values)


STORES_PARAM_DESCRIPTION = "CSV de mlp_official_store_id y/o 'sin_tienda' (ODD metricas-ml-tablero T1)"


def parse_csv_stores(raw: Optional[str]) -> Tuple[str, ...]:
    """ODD `metricas-ml-tablero` T1: CSV of official-store ids plus the
    `sin_tienda` sentinel, normalised to text (`"057997"` -> `"57997"`) and
    deduplicated. An empty entry, a non-numeric token or an out-of-range id is
    422, same contract as the other facets (`parse_csv_ids`)."""
    if not raw:
        return ()
    values: "list[str]" = []
    for part in raw.split(","):
        token = part.strip()
        value = NO_STORE if token == NO_STORE else str(parse_csv_ids(token or ",", "stores")[0])
        if value not in values:
            values.append(value)
    return tuple(values)
