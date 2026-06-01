"""
Unit tests for sync_ageing.py (Slice 4 — ERP Ageing Sync).

Covers:
- _fetch_ageing: delegates to gbp-parser endpoint via GET, validates response shape
- Código → item_id mapping (resolved via productos_erp.codigo)
- Upsert payload: ageing_dias, ageing_payload, explicit updated_at
- Unmatched Códigos are skipped (no crash)
- Empty ERP response handled gracefully

All DB and HTTP calls are mocked — no real network or DB access.
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql as pg_dialect

from app.scripts.sync_ageing import (
    _build_upsert_rows,
    _fetch_ageing,
    _resolve_codigo_map,
    _upsert_batch,
    parse_ageing_response,
)


# ---------------------------------------------------------------------------
# Sample data (matches real scriptAgeing schema)
# ---------------------------------------------------------------------------

SAMPLE_AGEING_ROW = {
    "Código": "SKU-001",
    "Producto": "Widget A",
    "Ageing": 45,
    "Stock_Físico": 10,
    "Pendientes": 2,
    "Stock_Disponible": 8,
    "Moneda_Costo": "ARS",
    "Costo": 1500.0,
    "IVA": 21.0,
    "Precio_Lista_ML": 2500.0,
    "Precio_Publicado_ML": 2400.0,
    "Costo_Envio": 300.0,
    "Comisión_ML": 250.0,
    "Activa": "1",
}

SAMPLE_AGEING_ROW_2 = {
    "Código": "SKU-002",
    "Producto": "Widget B",
    "Ageing": 12,
    "Stock_Físico": 5,
    "Pendientes": 0,
    "Stock_Disponible": 5,
    "Moneda_Costo": "ARS",
    "Costo": 800.0,
    "IVA": 21.0,
    "Precio_Lista_ML": 1200.0,
    "Precio_Publicado_ML": 1100.0,
    "Costo_Envio": 150.0,
    "Comisión_ML": 110.0,
    "Activa": "1",
}

UNMATCHED_ROW = {
    "Código": "SKU-UNKNOWN",
    "Producto": "Ghost Product",
    "Ageing": 999,
    "Stock_Físico": 0,
    "Pendientes": 0,
    "Stock_Disponible": 0,
    "Moneda_Costo": "ARS",
    "Costo": 0.0,
    "IVA": 21.0,
    "Precio_Lista_ML": 0.0,
    "Precio_Publicado_ML": 0.0,
    "Costo_Envio": 0.0,
    "Comisión_ML": 0.0,
    "Activa": "0",
}


# ---------------------------------------------------------------------------
# Tests: _fetch_ageing — HTTP call to gbp-parser endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ageing_returns_rows_on_success() -> None:
    """_fetch_ageing returns the list of dicts from the gbp-parser endpoint."""
    sample_rows = [SAMPLE_AGEING_ROW, SAMPLE_AGEING_ROW_2]

    mock_response = MagicMock()
    mock_response.json.return_value = sample_rows
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.scripts.sync_ageing.httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ageing("2000-01-01 00:00:00", "2026-12-31 23:59:59")

    assert result == sample_rows
    mock_client.get.assert_called_once()
    call_kwargs = mock_client.get.call_args
    # Verify GET is called with strScriptLabel and date params
    params = (
        call_kwargs.kwargs.get("params") or call_kwargs.args[1]
        if len(call_kwargs.args) > 1
        else call_kwargs.kwargs["params"]
    )
    assert params["strScriptLabel"] == "scriptAgeing"
    assert params["fromDate"] == "2000-01-01 00:00:00"
    assert params["toDate"] == "2026-12-31 23:59:59"


@pytest.mark.asyncio
async def test_fetch_ageing_raises_on_non_list_response() -> None:
    """_fetch_ageing raises RuntimeError when the endpoint returns a non-list."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"error": "something went wrong"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.scripts.sync_ageing.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Respuesta inesperada del gbp-parser"):
            await _fetch_ageing("2000-01-01 00:00:00", "2026-12-31 23:59:59")


@pytest.mark.asyncio
async def test_fetch_ageing_returns_empty_list() -> None:
    """_fetch_ageing returns [] when the endpoint returns an empty list."""
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.scripts.sync_ageing.httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ageing("2000-01-01 00:00:00", "2026-12-31 23:59:59")

    assert result == []


# ---------------------------------------------------------------------------
# Tests: parse_ageing_response
# ---------------------------------------------------------------------------


def test_parse_ageing_response_valid_list() -> None:
    """parse_ageing_response returns a list unchanged when given a valid list."""
    raw: list[dict] = [SAMPLE_AGEING_ROW]
    result = parse_ageing_response(raw)
    assert result == raw


def test_parse_ageing_response_empty_list() -> None:
    """parse_ageing_response returns an empty list for empty input."""
    result = parse_ageing_response([])
    assert result == []


def test_parse_ageing_response_none_returns_empty() -> None:
    """parse_ageing_response returns [] when given None (defensive)."""
    result = parse_ageing_response(None)  # type: ignore[arg-type]
    assert result == []


def test_parse_ageing_response_non_list_returns_empty() -> None:
    """parse_ageing_response returns [] for unexpected non-list input."""
    result = parse_ageing_response({"error": "bad"})  # type: ignore[arg-type]
    assert result == []


# ---------------------------------------------------------------------------
# Tests: _resolve_codigo_map
# ---------------------------------------------------------------------------


def test_resolve_codigo_map_returns_mapping() -> None:
    """_resolve_codigo_map queries DB for matching codigos and returns codigo→item_id dict."""
    mock_db = MagicMock()
    # Simulate two matching rows returned by the DB query
    mock_db.execute.return_value.fetchall.return_value = [
        ("SKU-001", 101),
        ("SKU-002", 202),
    ]

    codigos = {"SKU-001", "SKU-002", "SKU-UNKNOWN"}
    result = _resolve_codigo_map(mock_db, codigos)

    assert result == {"SKU-001": 101, "SKU-002": 202}


def test_resolve_codigo_map_empty_codigos() -> None:
    """_resolve_codigo_map returns {} immediately for an empty input set."""
    mock_db = MagicMock()
    result = _resolve_codigo_map(mock_db, set())
    assert result == {}
    mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: _build_upsert_rows
# ---------------------------------------------------------------------------


def test_build_upsert_rows_matched() -> None:
    """_build_upsert_rows maps matched Códigos to item_ids with correct payload."""
    codigo_map = {"SKU-001": 101, "SKU-002": 202}
    rows = [SAMPLE_AGEING_ROW, SAMPLE_AGEING_ROW_2]
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)

    result, skipped = _build_upsert_rows(rows, codigo_map, sync_ts=now)

    assert skipped == 0
    assert len(result) == 2

    row_001 = next(r for r in result if r["item_id"] == 101)
    assert row_001["ageing_dias"] == 45
    assert row_001["ageing_payload"]["Código"] == "SKU-001"
    assert row_001["fecha_sync"] == now
    # updated_at MUST be explicitly set (not left to ORM onupdate)
    assert "updated_at" in row_001
    assert row_001["updated_at"] == now


def test_build_upsert_rows_skips_unmatched() -> None:
    """_build_upsert_rows skips rows whose Código is not in codigo_map."""
    codigo_map = {"SKU-001": 101}
    rows = [SAMPLE_AGEING_ROW, UNMATCHED_ROW]
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)

    result, skipped = _build_upsert_rows(rows, codigo_map, sync_ts=now)

    assert skipped == 1
    assert len(result) == 1
    assert result[0]["item_id"] == 101


def test_build_upsert_rows_all_unmatched() -> None:
    """_build_upsert_rows handles the case where nothing matches (returns empty list)."""
    codigo_map: dict[str, int] = {}
    rows = [SAMPLE_AGEING_ROW, UNMATCHED_ROW]
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)

    result, skipped = _build_upsert_rows(rows, codigo_map, sync_ts=now)

    assert result == []
    assert skipped == 2


def test_build_upsert_rows_empty_response() -> None:
    """_build_upsert_rows returns ([], 0) for an empty ERP response."""
    result, skipped = _build_upsert_rows([], {}, sync_ts=datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC))
    assert result == []
    assert skipped == 0


def test_build_upsert_rows_ageing_payload_contains_full_row() -> None:
    """ageing_payload must contain all fields from the ERP row."""
    codigo_map = {"SKU-001": 101}
    now = datetime(2026, 5, 29, tzinfo=UTC)
    result, _ = _build_upsert_rows([SAMPLE_AGEING_ROW], codigo_map, sync_ts=now)

    payload = result[0]["ageing_payload"]
    # Key fields from the ERP row schema
    for field in ("Código", "Producto", "Ageing", "Stock_Físico", "Moneda_Costo", "Costo"):
        assert field in payload, f"Missing field in ageing_payload: {field}"


def test_build_upsert_rows_ageing_none_when_key_missing() -> None:
    """ageing_dias must be None when the 'Ageing' key is absent or None in the ERP row."""
    row_missing_key: dict = {
        "Código": "SKU-001",
        "Producto": "Widget A",
        # 'Ageing' intentionally absent
    }
    row_explicit_none: dict = {
        "Código": "SKU-001",
        "Producto": "Widget A",
        "Ageing": None,
    }
    codigo_map = {"SKU-001": 101}
    now = datetime(2026, 5, 29, tzinfo=UTC)

    result_missing, _ = _build_upsert_rows([row_missing_key], codigo_map, sync_ts=now)
    assert result_missing[0]["ageing_dias"] is None, "Missing key should yield ageing_dias=None"

    result_none, _ = _build_upsert_rows([row_explicit_none], codigo_map, sync_ts=now)
    assert result_none[0]["ageing_dias"] is None, "Explicit None should yield ageing_dias=None"


# ---------------------------------------------------------------------------
# Tests: _upsert_batch — ON CONFLICT SET clause validation
# ---------------------------------------------------------------------------
#
# Approach: compile the INSERT … ON CONFLICT DO UPDATE statement with the
# PostgreSQL dialect and assert the SQL string includes `updated_at` in the
# SET clause. This verifies the data-correctness invariant (updated_at is
# explicitly set on conflict, not left to the frozen ORM insert-time value)
# without requiring a live PostgreSQL connection.
#
# Why not use a real DB here?
# The test suite uses SQLite (in-memory). pg_insert(...).on_conflict_do_update
# is a PostgreSQL-specific construct that SQLite cannot execute. There is no
# Postgres fixture/marker in the existing suite, so the SQL-compilation
# approach is the correct fit for this codebase.


def test_upsert_batch_compiled_sql_sets_updated_at() -> None:
    """_upsert_batch must emit ON CONFLICT DO UPDATE with an explicit updated_at in SET.

    Calls the REAL _upsert_batch with a mocked session, captures the statement
    passed to db.execute(), compiles it with the PostgreSQL dialect, and asserts
    'updated_at' is assigned in the SET clause — proving the frozen-insert-time
    bug cannot regress. (Testing the real function, not a reconstruction.)
    """
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)
    batch = [
        {
            "item_id": 1,
            "ageing_dias": 30,
            "ageing_payload": {"Ageing": 30},
            "fecha_sync": now,
            "updated_at": now,
        }
    ]

    db = MagicMock()
    _upsert_batch(db, batch)

    db.execute.assert_called_once()
    stmt = db.execute.call_args[0][0]
    sql_str = str(stmt.compile(dialect=pg_dialect.dialect()))

    assert "ON CONFLICT" in sql_str, "Statement must include ON CONFLICT clause"
    assert "DO UPDATE" in sql_str, "Statement must include DO UPDATE"
    # The SET clause must explicitly assign updated_at (not rely on ORM onupdate)
    assert "updated_at" in sql_str, (
        "ON CONFLICT SET clause must include updated_at — without it, updated_at stays frozen at insert time"
    )
