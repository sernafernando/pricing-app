"""Drift guard between `vocabularios.VOCABULARIOS` and `TriagePropuesta`'s
`Literal[...]` annotations for `severidad`/`urgencia` (tickets-triage-feedback
PR1).

A `typing.Literal` cannot be constructed from a runtime value, so
`TriagePropuesta` and `vocabularios.VOCABULARIOS` are two independent copies
of the same closed vocabulary — the design's own flagged "genuinely hard to
keep correct" duplication. This test is the thing that keeps it honest: if
either copy drifts, this goes red instead of silently letting a corrected
value through (or reject one) `TriagePropuesta` disagrees with.

Written FIRST (RED phase) per strict TDD: `app.tickets.services.vocabularios`
does not exist yet, so this must fail on import error, not a false pass.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_vocabularios_drift.py -v
"""

from __future__ import annotations

import typing

from app.tickets.services.triage_service import TriagePropuesta
from app.tickets.services.vocabularios import CAMPOS_CORREGIBLES, VOCABULARIOS


def _literal_values(campo: str) -> set[str]:
    """Extracts the closed set of values from `TriagePropuesta.<campo>`'s
    `Optional[Literal[...]]` annotation via `typing.get_args`, unwrapping the
    `Optional` (i.e. `Union[Literal[...], None]`) wrapper first.

    `triage_service.py` uses `from __future__ import annotations`, so raw
    `__annotations__` values are unevaluated strings — `typing.get_type_hints`
    resolves them back into real `Literal[...]` objects first."""
    hints = typing.get_type_hints(TriagePropuesta)
    annotation = hints[campo]
    args = typing.get_args(annotation)  # (Literal[...], NoneType)
    literal_type = next(a for a in args if typing.get_origin(a) is typing.Literal)
    return set(typing.get_args(literal_type))


class TestVocabulariosMatchTriagePropuestaLiterals:
    def test_severidad_literal_matches_vocabulario(self) -> None:
        assert _literal_values("severidad") == VOCABULARIOS["severidad"]

    def test_urgencia_literal_matches_vocabulario(self) -> None:
        assert _literal_values("urgencia") == VOCABULARIOS["urgencia"]


class TestCamposCorregibles:
    def test_only_severidad_and_urgencia_are_correctable(self) -> None:
        """Spec: 'Confirm Accepts An Optional Corrected Value, Severidad/
        Urgencia Only' — titulo/resumen/sector/tipo_ticket/metadata_ia are
        deliberately excluded."""
        assert CAMPOS_CORREGIBLES == frozenset({"severidad", "urgencia"})
