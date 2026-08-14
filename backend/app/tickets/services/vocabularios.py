"""Closed vocabularies for AI-triage correctable fields
(tickets-triage-feedback PR1).

Deliberately a LEAF module — imports nothing from `app.tickets.services.*` —
so `confirmacion_service` can import this without creating a circular import
with `triage_service` (which itself imports `confirmacion_service` for the
auto-apply write path).

`VOCABULARIOS` is a second, independent copy of the values already encoded
in `TriagePropuesta.severidad`/`.urgencia`'s `Literal[...]` annotations in
`triage_service.py` — a `typing.Literal` cannot be constructed from a
runtime value, so that duplication is unavoidable. Kept honest by
`tests/tickets/test_vocabularios_drift.py`'s drift-guard test, which asserts
both copies agree via `typing.get_args`.
"""

from __future__ import annotations

VOCABULARIOS: dict[str, frozenset[str]] = {
    "severidad": frozenset({"trivial", "menor", "mayor", "critica"}),
    "urgencia": frozenset({"baja", "normal", "alta", "inmediata"}),
}

# Fields `confirmacion_service.confirmar()` accepts an optional corrected
# value for (spec: "Confirm Accepts An Optional Corrected Value, Severidad/
# Urgencia Only"). A strict subset of `confirmacion_service.CAMPOS_CONFIRMABLES`
# — titulo/resumen/sector/tipo_ticket/metadata_ia are transformations or
# domain operations, not closed-vocabulary judgements, so "correcting" them
# has no defined meaning here.
CAMPOS_CORREGIBLES = frozenset({"severidad", "urgencia"})
