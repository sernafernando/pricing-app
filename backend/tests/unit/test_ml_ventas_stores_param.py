"""ODD `metricas-ml-tablero` T1 review: `_parse_csv_stores` normalises and
de-duplicates the `stores` param before it reaches `SalesFilter`, so two
spellings of the same store can never become two EXISTS branches (or two
cache keys) -- and a malformed token is a 422, never a silent no-op."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers.ml_ventas_ops import _parse_csv_stores


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("057997", ("57997",)),
        ("00002645,2645", ("2645",)),
        ("57997,57997,57997", ("57997",)),
        ("  sin_tienda  ", ("sin_tienda",)),
        ("sin_tienda,sin_tienda", ("sin_tienda",)),
        (" 057997 , sin_tienda,57997 ,  sin_tienda ", ("57997", "sin_tienda")),
        ("2645,057997,sin_tienda,2645", ("2645", "57997", "sin_tienda")),
        ("", ()),
        (None, ()),
    ],
)
def test_normalises_and_deduplicates_keeping_first_seen_order(raw, expected) -> None:
    assert _parse_csv_stores(raw) == expected


@pytest.mark.parametrize("raw", ["57997,,2645", "abc", "SIN_TIENDA", "57997;2645", " , ", "99999999999999"])
def test_a_malformed_token_is_422(raw) -> None:
    with pytest.raises(HTTPException) as err:
        _parse_csv_stores(raw)
    assert err.value.status_code == 422
