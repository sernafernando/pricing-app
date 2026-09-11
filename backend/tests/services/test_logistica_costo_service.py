"""The Python cost resolver and the SQL one must never drift apart.

`logistica_costo_service.costo_efectivo` (Python, over loaded rows) and
`etiquetas_shared._build_costo_case` (SQL, inside a query) answer the same
question for the same label. They cannot be one implementation -- one runs
in the database, the other over objects already in memory -- so this file
is what keeps them honest: every case is evaluated BOTH ways against the
same row, and the two answers must be equal.

Without it, the ML sales breakdown and the Etiquetas screen would be free
to show different costs for the same `shipping_id`, which is the
two-numbers-for-one-sale failure the breakdown module calls the worst
outcome available.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Numeric, cast, literal

from app.api.endpoints.etiquetas_shared import _build_costo_case
from app.models.etiqueta_envio import EtiquetaEnvio
from app.services.logistica_costo_service import costo_efectivo, normalizar_cordon


class TestCordonNormalisation:
    """`cp_cordones` writes the accent, `logistica_costo_cordon` does not.
    Everything that joins them has to agree on one spelling."""

    @pytest.mark.parametrize(
        "stored,expected",
        [
            ("Cordón 1", "Cordon 1"),
            ("Cordón 2", "Cordon 2"),
            ("Cordón 3", "Cordon 3"),
            ("CABA", "CABA"),
            (None, None),
        ],
    )
    def test_it_maps_to_the_tariff_table_spelling(self, stored, expected) -> None:
        assert normalizar_cordon(stored) == expected

    def test_an_already_plain_value_is_left_alone(self) -> None:
        """Callers should not have to know which spelling they hold."""
        assert normalizar_cordon("Cordon 1") == "Cordon 1"


class TestOverrideWins:
    def test_a_typed_override_beats_every_tariff(self) -> None:
        """A human typed it; no tariff, turbo price or surcharge outranks
        that."""
        assert costo_efectivo(
            costo_override=Decimal("123.45"),
            es_turbo=True,
            es_lluvia=True,
            costo=Decimal("500"),
            costo_turbo=Decimal("900"),
            lluvia_tipo="fijo",
            lluvia_valor=1800.0,
        ) == Decimal("123.45")


class TestNothingResolvesToNone:
    def test_no_tariff_at_all_is_none_not_zero(self) -> None:
        """`Decimal("0")` would render as a shipment that cost us nothing,
        and a reader cannot tell that lie from a genuine free shipment."""
        assert costo_efectivo() is None

    def test_turbo_with_neither_price_is_none_not_zero(self) -> None:
        assert costo_efectivo(es_turbo=True) is None


# (es_turbo, es_lluvia, costo, costo_turbo, lluvia_tipo, lluvia_valor)
_CASES = [
    (False, False, Decimal("500"), Decimal("900"), "fijo", 0.0),
    (False, True, Decimal("500"), Decimal("900"), "fijo", 1800.0),
    (True, False, Decimal("500"), Decimal("900"), "fijo", 1800.0),
    (True, True, Decimal("500"), Decimal("900"), "fijo", 1800.0),
    (True, True, Decimal("500"), Decimal("900"), "porcentaje", 50.0),
    (True, False, Decimal("500"), None, "fijo", 1800.0),
    (True, True, Decimal("500"), None, "porcentaje", 50.0),
    (True, True, Decimal("500"), Decimal("900"), "fijo", 0.0),
    # NOT round on purpose. Every case above happens to land on an exact
    # cent, which let the two implementations agree while Python kept
    # digits SQL had already cast away. 255.553 x 1.5 = 383.3295 in Python
    # and 383.33 in SQL -- one shipment, two prices.
    (True, True, Decimal("255.553"), Decimal("255.553"), "porcentaje", 50.0),
    (True, True, Decimal("101.017"), Decimal("333.339"), "porcentaje", 33.0),
    # The branches the first non-round cases did NOT reach. Both of these
    # failed while `porcentaje` passed, because only that branch rounded.
    (False, False, Decimal("255.553"), Decimal("900"), "fijo", 0.0),
    (True, False, Decimal("500"), Decimal("255.553"), "fijo", 1800.0),
    (True, True, Decimal("500"), Decimal("255.553"), "fijo", 100.0),
]


class TestTheTwoImplementationsAgree:
    """The whole point of this file. Each case is computed in Python and in
    SQL over the same row; a difference fails here rather than showing up
    as two costs for one shipment in production."""

    @pytest.mark.parametrize("es_turbo,es_lluvia,costo,costo_turbo,lluvia_tipo,lluvia_valor", _CASES)
    def test_python_matches_sql(self, db, es_turbo, es_lluvia, costo, costo_turbo, lluvia_tipo, lluvia_valor) -> None:
        label = EtiquetaEnvio(
            shipping_id="7001",
            fecha_envio=date(2026, 8, 1),
            es_turbo=es_turbo,
            es_lluvia=es_lluvia,
        )
        db.add(label)
        db.commit()

        en_python = costo_efectivo(
            es_turbo=es_turbo,
            es_lluvia=es_lluvia,
            costo=costo,
            costo_turbo=costo_turbo,
            lluvia_tipo=lluvia_tipo,
            lluvia_valor=lluvia_valor,
        )

        expresion = _build_costo_case(
            literal(costo_turbo, Numeric(12, 2)) if costo_turbo is not None else cast(None, Numeric(12, 2)),
            literal(costo, Numeric(12, 2)),
            lluvia_tipo,
            lluvia_valor,
        )
        en_sql = db.query(expresion).filter(EtiquetaEnvio.shipping_id == "7001").scalar()

        assert en_python is not None
        assert Decimal(str(en_sql)) == en_python
