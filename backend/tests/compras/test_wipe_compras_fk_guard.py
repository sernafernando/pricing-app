"""Guard: the wipe-compras table list must not rot as the schema grows.

`wipe_compras_service` deletes a HARDCODED list of tables. Any table that points
at one of them with an incoming FK that does not resolve itself (RESTRICT or the
NO ACTION default) blocks `DELETE FROM` the parent with a ForeignKeyViolation —
a 500 that only surfaces when somebody actually presses the button.

That has now bitten three times:
  - 2026-06-03: dinero_a_cuenta + etiquetas_envio (fix 03f6cff6)
  - 2026-07-17: pedido_compra_ingresos, added 2026-06-18, two weeks after the
    list was last touched. The #839 env-gate hid the 500 behind a 404 until the
    gate was removed.

This test walks the real SQLAlchemy metadata instead of the list, so a NEW table
referencing a wiped table fails here at commit time rather than in production.

If this test fails, you added a table that points at the compras module. Pick one:
  1. It is compras data → add it to `TABLAS_COMPRAS_SIEMPRE` BEFORE its parent.
  2. Its FK resolves itself (CASCADE / SET NULL) → nothing to do; this test
     already ignores it.
  3. It is shared with another module and must survive → add it to `HANDLED`
     below WITH the reason and how the wipe deals with it.
Do not silence this by deleting the assertion.
"""

from __future__ import annotations

from app.core.database import Base
from app.services.wipe_compras_service import TABLAS_CAJA_BANCO, TABLAS_COMPRAS_SIEMPRE

# Incoming FKs the wipe deals with WITHOUT deleting the referencing table.
# Every entry needs a reason — an unexplained entry is how the rot creeps back.
HANDLED = {
    "etiquetas_envio": (
        "Shared with RMA (rma_caso_items -> etiquetas_envio RESTRICT). wipe_compras runs a "
        "non-destructive UPDATE unlinking it from compras (tipo_envio->'cliente', FKs->NULL) "
        "before DELETE FROM pedidos_compra."
    ),
}

# FK ondelete values that resolve themselves — Postgres cleans up, nothing blocks.
SELF_RESOLVING = {"CASCADE", "SET NULL", "SET DEFAULT"}


def _wiped_tables() -> set[str]:
    return set(TABLAS_COMPRAS_SIEMPRE) | set(TABLAS_CAJA_BANCO)


def _blocking_references() -> list[tuple[str, str, str]]:
    """(referencing_table, wiped_parent, ondelete) for every FK that blocks a wipe."""
    wiped = _wiped_tables()
    blockers: list[tuple[str, str, str]] = []

    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent not in wiped:
                continue
            if table.name in wiped:
                continue  # deleted too — ordering is the list's job, not this test's
            ondelete = (fk.ondelete or "NO ACTION").upper()
            if ondelete in SELF_RESOLVING:
                continue
            blockers.append((table.name, parent, ondelete))

    return sorted(set(blockers))


def test_no_unhandled_fk_blocks_the_wipe() -> None:
    """Every table pointing at a wiped table is wiped too, self-resolving, or HANDLED."""
    unhandled = [(src, parent, od) for src, parent, od in _blocking_references() if src not in HANDLED]

    assert not unhandled, (
        "These tables hold an incoming FK that will make DELETE FROM the parent fail "
        "with ForeignKeyViolation:\n"
        + "\n".join(f"  - {src}.{od} -> {parent}" for src, parent, od in unhandled)
        + "\n\nAdd each to TABLAS_COMPRAS_SIEMPRE (before its parent) if it is compras data, "
        "or to HANDLED in this file with the reason it must survive."
    )


def test_handled_entries_are_still_real() -> None:
    """HANDLED must not accumulate stale entries for FKs that no longer exist."""
    referencing = {src for src, _, _ in _blocking_references()}
    stale = sorted(set(HANDLED) - referencing)

    assert not stale, (
        f"HANDLED lists tables that no longer block the wipe: {stale}. "
        "Remove them — a stale exemption hides the next real one."
    )


def test_children_are_deleted_before_their_parents() -> None:
    """Ordering within the list must stay FK-safe: a child cannot be deleted after its parent."""
    order = TABLAS_COMPRAS_SIEMPRE + TABLAS_CAJA_BANCO
    position = {tabla: i for i, tabla in enumerate(order)}
    violations: list[str] = []

    for table in Base.metadata.tables.values():
        if table.name not in position:
            continue
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent not in position or parent == table.name:
                continue
            if (fk.ondelete or "NO ACTION").upper() in SELF_RESOLVING:
                continue
            if position[table.name] > position[parent]:
                violations.append(
                    f"{table.name} (pos {position[table.name]}) must come BEFORE {parent} (pos {position[parent]})"
                )

    assert not violations, "FK-unsafe deletion order:\n" + "\n".join(f"  - {v}" for v in sorted(set(violations)))
