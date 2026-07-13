"""
T-6 / T-7: Unit tests — SQL string guards for agregar_metricas_tplink_incremental.py.

Slice 2 (SDD change tplink-metricas-dual-key-dedup): the incremental job's
`calcular_metricas_locales` no longer owns its own SQL string — it delegates
to the shared `_tplink_metricas_core.build_aggregation_sql()` (design D1),
so these SQL-shape guards now target the core module's query builder
instead of the wrapper function. The assertions themselves are unchanged.

Verifies (SQLite-safe string assertions):
- The shared aggregating SQL contains NO literal 'coslis_id = 1'.
- The SQL contains ':coslis_id' bind parameter.
- The SQL contains ':store_id' bind parameter.
- process_and_insert does NOT call registrar_consumo_grupo_offset,
  registrar_consumo_offset_individual, or crear_notificacion_markup_bajo.

These are cheap regression guards against literal-leakage and double-counting side effects.
"""

from __future__ import annotations

import inspect

import pytest


def _get_module():
    """Import the incremental job module."""
    import app.scripts.agregar_metricas_tplink_incremental as mod
    return mod


def _get_core_module():
    """Import the shared aggregation core module (owns the SQL now)."""
    import app.scripts._tplink_metricas_core as core
    return core


class TestIncrementalSqlNoCoslis1Literal:
    """SQL must use :coslis_id bind, never coslis_id = 1 literal."""

    def test_no_literal_coslis_id_1_in_sql(self) -> None:
        """The shared aggregating SQL must not contain 'coslis_id = 1'."""
        core = _get_core_module()
        sql_str = str(core.build_aggregation_sql())
        assert "coslis_id = 1" not in sql_str, (
            "Found literal 'coslis_id = 1' in the shared aggregating SQL — "
            "must use :coslis_id bind parameter instead."
        )

    def test_coslis_id_bind_present_in_sql(self) -> None:
        """The SQL must reference ':coslis_id' as a bind parameter."""
        core = _get_core_module()
        sql_str = str(core.build_aggregation_sql())
        assert ":coslis_id" in sql_str, (
            "':coslis_id' bind not found in the shared aggregating SQL."
        )

    def test_store_id_bind_present_in_sql(self) -> None:
        """The SQL must filter by ':store_id' bind parameter."""
        core = _get_core_module()
        sql_str = str(core.build_aggregation_sql())
        assert ":store_id" in sql_str, (
            "':store_id' bind not found in the shared aggregating SQL. "
            "Must add 'AND tmlip.mlp_official_store_id = :store_id' to WHERE clause."
        )

    def test_incremental_delegates_to_shared_core_builder(self) -> None:
        """The wrapper's `calcular_metricas_locales` must call the core's
        `build_aggregation_sql()` rather than embedding its own SQL string."""
        mod = _get_module()
        source = inspect.getsource(mod.calcular_metricas_locales)
        assert "build_aggregation_sql()" in source
        assert "DISTINCT ON" not in source


class TestIncrementalNoGlobalSideEffects:
    """process_and_insert must NOT call ML-global side-effect functions."""

    def test_no_registrar_consumo_grupo_offset_call(self) -> None:
        """process_and_insert must not call registrar_consumo_grupo_offset."""
        mod = _get_module()
        source = inspect.getsource(mod.process_and_insert)
        assert "registrar_consumo_grupo_offset" not in source, (
            "process_and_insert calls registrar_consumo_grupo_offset — "
            "this double-counts offset consumo (ML incremental already handles store-2645)."
        )

    def test_no_registrar_consumo_offset_individual_call(self) -> None:
        """process_and_insert must not call registrar_consumo_offset_individual."""
        mod = _get_module()
        source = inspect.getsource(mod.process_and_insert)
        assert "registrar_consumo_offset_individual" not in source, (
            "process_and_insert calls registrar_consumo_offset_individual — "
            "this double-counts offset consumo."
        )

    def test_no_crear_notificacion_markup_bajo_call(self) -> None:
        """process_and_insert must not call crear_notificacion_markup_bajo."""
        mod = _get_module()
        source = inspect.getsource(mod.process_and_insert)
        assert "crear_notificacion_markup_bajo" not in source, (
            "process_and_insert calls crear_notificacion_markup_bajo — "
            "this duplicates markup notifications (ML incremental already sends them)."
        )
