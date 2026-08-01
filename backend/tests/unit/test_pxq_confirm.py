"""Tests for `pxq_confirm`: matching the post-write re-read to mirror rows.

This logic decides whether the snapshot advances, and a stale snapshot is what
lets the next sync overwrite somebody else's change. Five separate defects
were found here while it lived inside the orchestration module — several of
them introduced while fixing the previous one — which is why it now has its
own module and its own tests.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.models.ml_pxq_tier import (
    ESTADO_DESCONOCIDO,
    ESTADO_LISTO,
    ESTADO_SINCRONIZADO,
)
from app.services.pxq_confirm import remap_and_confirm


class TestPartialConfirmationIsNotSuccess:
    """The previous fix covered the case where the confirmation re-read failed
    ENTIRELY. It left open the case where the re-read arrived but one row did
    not match: that row goes to `desconocido` and the caller still received
    `synced: True` with a 200. Same defect, one branch over."""

    def test_a_row_that_cannot_be_confirmed_makes_the_whole_outcome_unconfirmed(self) -> None:

        rows = [
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=10,
                precio_unitario=Decimal("500.00"),
                ml_price_id="ML1",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            ),
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=20,
                precio_unitario=Decimal("400.00"),
                ml_price_id="ML2",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            ),
        ]
        # The re-read only accounts for the first row.
        confirmed = [{"id": "ML1", "quantity": 10, "amount": 500.00}]

        all_confirmed = remap_and_confirm(rows, confirmed)

        assert all_confirmed is False
        assert rows[1].estado == ESTADO_DESCONOCIDO
        assert rows[1].cantidad_sincronizada is None

    def test_every_row_confirmed_reports_confirmed(self) -> None:
        from app.models.ml_pxq_tier import ESTADO_SINCRONIZADO

        rows = [
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=10,
                precio_unitario=Decimal("500.00"),
                ml_price_id="ML1",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            )
        ]
        confirmed = [{"id": "ML1", "quantity": 10, "amount": 500.00}]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].cantidad_sincronizada == 10

    def test_money_is_matched_as_decimal_not_binary_float(self) -> None:
        """The one comparison deciding whether the snapshot advances was
        float == float, in a module whose whole point is that a stale snapshot
        reintroduces the overwrite bug."""

        from app.models.ml_pxq_tier import ESTADO_SINCRONIZADO

        rows = [
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=3,
                precio_unitario=Decimal("1234.56"),
                ml_price_id="ML1",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            )
        ]
        confirmed = [{"id": "ML1", "quantity": 3, "amount": "1234.56"}]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].precio_sincronizado == Decimal("1234.56")


class TestOnlyTiersWithAShippingCostAreEverWritten:
    """The founding rule of this feature: a tier without a resolved
    whole-shipment cost is never priced and never written.

    The filter asked `estado != incompleto` and its docstring claimed that
    equals "carries costo_envio_total". It does not — nothing recomputes
    `estado` when a cost is cleared, so a row sitting at `listo` or
    `desconocido` with a NULL cost went straight into the write."""

    def _row(self, estado, quantity, cost, price_id=None):
        return SimpleNamespace(
            estado=estado,
            cantidad_minima=quantity,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=cost,
            ml_price_id=price_id,
            cantidad_sincronizada=None,
            precio_sincronizado=None,
        )

    def test_a_row_without_a_shipping_cost_is_excluded_whatever_its_estado(self) -> None:
        from app.services.ml_pxq_write_service import _desired_tiers_from_mirror

        rows = [
            self._row(ESTADO_LISTO, 10, None),
            self._row(ESTADO_DESCONOCIDO, 20, None, "ML2"),
            self._row(ESTADO_LISTO, 30, Decimal("3200.00")),
        ]

        desired = _desired_tiers_from_mirror(rows)

        assert [d.quantity for d in desired] == [30]


class TestConfirmationMatchesByIdWhenItIsKnown:
    """Matching purely on (quantity, amount) lets a row claim a tier it did
    not create. An untracked tier — one alive in ML that we preserve as a keep
    and never owned — with the same quantity and price as one of our rows can
    be claimed by it, and then the next sync will happily modify or delete
    somebody else's tier. Which row wins is decided by list order.

    When the row already carries an ml_price_id, that id IS the answer; only
    creates need to be matched by value."""

    def _row(self, quantity, amount, price_id=None, synced=False):
        return SimpleNamespace(
            estado="listo",
            cantidad_minima=quantity,
            precio_unitario=amount,
            costo_envio_total=Decimal("3200.00"),
            ml_price_id=price_id,
            cantidad_sincronizada=quantity if synced else None,
            precio_sincronizado=amount if synced else None,
        )

    def test_a_row_with_an_id_does_not_claim_an_untracked_tier_with_the_same_values(self) -> None:

        # A keep: values still equal the snapshot, so this row's id survived
        # the write and is the only correct match.
        rows = [self._row(10, Decimal("500.00"), "OURS", synced=True)]
        # The untracked tier is listed FIRST and has identical values.
        confirmed = [
            {"id": "THEIRS", "quantity": 10, "amount": "500.00"},
            {"id": "OURS", "quantity": 10, "amount": "500.00"},
        ]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].ml_price_id == "OURS"

    def test_a_created_row_without_an_id_still_matches_by_value(self) -> None:

        rows = [self._row(20, Decimal("400.00"))]
        confirmed = [{"id": "NEW", "quantity": 20, "amount": "400.00"}]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].ml_price_id == "NEW"


def test_a_created_row_cannot_adopt_an_untracked_tier_with_identical_values() -> None:
    """The case the keep-vs-id test does not reach. A create has no id, so it
    must match by value — and an untracked tier we preserved but never owned
    can carry the same quantity and price. Whoever is first in the re-read
    wins, and adopting a stranger's tier means the next sync modifies or
    deletes it.

    `untracked_ids` exists to claim those up front. It was accepted as a
    parameter, documented as the protection, and never passed by the one
    caller — the guard was there and unplugged."""

    row = SimpleNamespace(
        estado="listo",
        cantidad_minima=10,
        precio_unitario=Decimal("500.00"),
        costo_envio_total=Decimal("3200.00"),
        ml_price_id=None,
        cantidad_sincronizada=None,
        precio_sincronizado=None,
    )
    confirmed = [
        {"id": "THEIRS", "quantity": 10, "amount": "500.00"},
        {"id": "OURS", "quantity": 10, "amount": "500.00"},
    ]

    assert remap_and_confirm([row], confirmed, untracked_ids=["THEIRS"]) is True
    assert row.ml_price_id == "OURS"


def test_a_keep_whose_id_vanished_from_the_reread_is_not_confirmed() -> None:
    """Introduced by the two-pass matcher: pass 1 looked the id up and, on a
    miss, did nothing at all — no desconocido, no all_confirmed=False — while
    pass 2 skipped the row as "already resolved". It fell through the gap, and
    the caller got synced: True.

    Concretely: ML applies the write but rotates the id. The row stays
    `sincronizado` pointing at an id that no longer exists, the next sync
    refuses with `mirror ml_price_id absent from live read`, and the success
    the user was shown was never true."""

    row = SimpleNamespace(
        estado="sincronizado",
        cantidad_minima=10,
        precio_unitario=Decimal("500.00"),
        costo_envio_total=Decimal("3200.00"),
        ml_price_id="ML1",
        cantidad_sincronizada=10,
        precio_sincronizado=Decimal("500.00"),
    )
    # ML rotated the id: our keep is gone from the confirmation.
    confirmed = [{"id": "ML9", "quantity": 10, "amount": "500.00"}]

    assert remap_and_confirm([row], confirmed) is False
    assert row.estado == ESTADO_DESCONOCIDO
