"""What `alembic revision --autogenerate` compares (`alembic/env.py`, `include_object`).

The Costo SI T4 snapshots (`costo_si_t4_respaldo_<table>`, migration `20261128_costo_si_t4_recalculo`) are tables
without a model on purpose: the recalc's safety net, dropped by hand once the owner signs off. Without this filter an
autogenerate would propose dropping them. Every other object is compared as before.
"""

from __future__ import annotations

from typing import Any, Optional

PREFIJO_RESPALDO_T4 = "costo_si_t4_respaldo_"


def incluir(objeto: Any, nombre: Optional[str], tipo: str, reflejado: bool, comparado_con: Any) -> bool:
    """Alembic's `include_object` hook: False only for a T4 snapshot table found in the database."""
    del objeto, comparado_con
    return not (tipo == "table" and reflejado and (nombre or "").startswith(PREFIJO_RESPALDO_T4))
