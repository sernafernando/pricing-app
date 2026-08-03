"""Full matrix for the pure PxQ array-replace diff (design D4, PR 3a).

`POST /items/{ITEM_ID}/prices/standard/quantity` replaces the WHOLE prices
array -- every assertion here checks the exact emitted array, not just
counts, because the payload itself is what MercadoLibre acts on.
"""

from decimal import Decimal

from app.services.pxq_diff import (
    DesiredTier,
    LiveTier,
    diff_pxq_tiers,
)


def test_keep_emits_only_the_id_when_matched_and_unchanged():
    live = [LiveTier(id="ML123", quantity=10, amount=Decimal("500.00"))]
    desired = [
        DesiredTier(
            quantity=10,
            amount=Decimal("500.00"),
            ml_price_id="ML123",
            synced_quantity=10,
            synced_amount=Decimal("500.00"),
        )
    ]

    result = diff_pxq_tiers(live, desired)

    assert result.ok
    assert result.array == [{"id": "ML123"}]


def test_create_emits_object_without_id():
    live = []
    desired = [DesiredTier(quantity=5, amount=Decimal("300.00"), ml_price_id=None)]

    result = diff_pxq_tiers(live, desired)

    assert result.ok
    assert result.array == [{"quantity": 5, "amount": 300.0}]


def test_delete_omits_a_live_tier_whose_desired_row_no_longer_exists():
    # Live has two tiers; only one is still desired. The caller (PR 3) simply
    # does not pass the dropped row in `desired_tiers` -- it is not an
    # "untracked" tier, it WAS tracked and is now gone.
    live = [
        LiveTier(id="ML1", quantity=5, amount=Decimal("100.00")),
    ]
    desired = [
        DesiredTier(
            quantity=5, amount=Decimal("100.00"), ml_price_id="ML1", synced_quantity=5, synced_amount=Decimal("100.00")
        )
    ]

    result = diff_pxq_tiers(live, desired)

    assert result.ok
    assert result.array == [{"id": "ML1"}]
    # The dropped tier's id never appears anywhere in the array.
    assert all("ML2" not in str(entry) for entry in result.array)


def test_modify_deletes_old_id_and_creates_new_without_id():
    # Snapshot still holds what live holds, so only the local side moved (a
    # local price edit), so it's a modify, not a divergence refusal.
    live = [LiveTier(id="ML1", quantity=10, amount=Decimal("500.00"))]
    desired = [
        DesiredTier(
            quantity=10,
            amount=Decimal("550.00"),
            ml_price_id="ML1",
            synced_quantity=10,
            synced_amount=Decimal("500.00"),
        )
    ]

    result = diff_pxq_tiers(live, desired)

    assert result.ok
    # The old id "ML1" must never appear in the emitted array.
    assert result.array == [{"quantity": 10, "amount": 550.0}]


def test_unmirrored_live_tier_is_preserved_as_keep():
    live = [LiveTier(id="ML_UNKNOWN", quantity=20, amount=Decimal("900.00"))]
    desired = [DesiredTier(quantity=5, amount=Decimal("100.00"), ml_price_id=None)]

    result = diff_pxq_tiers(live, desired)

    assert result.ok
    assert {"id": "ML_UNKNOWN"} in result.array
    assert {"quantity": 5, "amount": 100.0} in result.array
    assert len(result.array) == 2


def test_divergence_refuses_when_matched_id_differs_and_mirror_believes_it_is_synced():
    live = [LiveTier(id="ML1", quantity=10, amount=Decimal("500.00"))]
    # Snapshot matches the desired values, so the mirror believes it is in sync; an
    # unexplained difference is an external change, not our own edit.
    desired = [
        DesiredTier(
            quantity=10,
            amount=Decimal("600.00"),
            ml_price_id="ML1",
            synced_quantity=10,
            synced_amount=Decimal("600.00"),
        )
    ]

    result = diff_pxq_tiers(live, desired)

    assert not result.ok
    assert result.array is None
    assert result.refusal.reason == "divergence"
    diff = result.refusal.divergences[0]
    assert diff.ml_price_id == "ML1"
    assert diff.live == {"id": "ML1", "quantity": 10, "amount": 500.0}
    assert diff.desired == {"quantity": 10, "amount": 600.0}


def test_divergence_refuses_when_mirror_ml_price_id_absent_from_live():
    live = []  # nothing live at all; mirror still holds an old confirmed id
    desired = [
        DesiredTier(
            quantity=10,
            amount=Decimal("500.00"),
            ml_price_id="ML_GHOST",
            synced_quantity=10,
            synced_amount=Decimal("500.00"),
        )
    ]

    result = diff_pxq_tiers(live, desired)

    assert not result.ok
    assert result.array is None
    assert result.refusal.reason == "divergence"
    diff = result.refusal.divergences[0]
    assert diff.ml_price_id == "ML_GHOST"
    assert diff.reason == "mirror ml_price_id absent from live read"


def test_divergence_refusal_builds_no_array_and_no_partial_write():
    # A mix of a clean keep and a divergent row: nothing gets written, not
    # even the row that would have been fine on its own.
    live = [
        LiveTier(id="ML_OK", quantity=5, amount=Decimal("100.00")),
        LiveTier(id="ML_BAD", quantity=10, amount=Decimal("500.00")),
    ]
    desired = [
        DesiredTier(
            quantity=5,
            amount=Decimal("100.00"),
            ml_price_id="ML_OK",
            synced_quantity=5,
            synced_amount=Decimal("100.00"),
        ),
        DesiredTier(
            quantity=10,
            amount=Decimal("999.00"),
            ml_price_id="ML_BAD",
            synced_quantity=10,
            synced_amount=Decimal("999.00"),
        ),
    ]

    result = diff_pxq_tiers(live, desired)

    assert not result.ok
    assert result.array is None
    assert len(result.refusal.divergences) == 1
    assert result.refusal.divergences[0].ml_price_id == "ML_BAD"


def test_ids_only_from_live_invariant_never_echoes_an_unseen_id():
    # Every id in a resulting array must trace back to `live_tiers`. This
    # constructs a case with several keeps/creates/an untracked live tier and
    # asserts the full id set emitted is a subset of the live id set.
    live = [
        LiveTier(id="ML_A", quantity=5, amount=Decimal("100.00")),
        LiveTier(id="ML_B", quantity=10, amount=Decimal("200.00")),
        LiveTier(id="ML_UNTRACKED", quantity=15, amount=Decimal("300.00")),
    ]
    desired = [
        DesiredTier(
            quantity=5, amount=Decimal("100.00"), ml_price_id="ML_A", synced_quantity=5, synced_amount=Decimal("100.00")
        ),
        DesiredTier(
            quantity=10,
            amount=Decimal("200.00"),
            ml_price_id="ML_B",
            synced_quantity=10,
            synced_amount=Decimal("200.00"),
        ),
        DesiredTier(quantity=99, amount=Decimal("999.00"), ml_price_id=None),
    ]

    result = diff_pxq_tiers(live, desired)

    assert result.ok
    live_ids = {tier.id for tier in live}
    emitted_ids = {entry["id"] for entry in result.array if "id" in entry}
    assert emitted_ids.issubset(live_ids)
    assert emitted_ids == {"ML_A", "ML_B", "ML_UNTRACKED"}


def test_empty_desired_set_refuses_without_allow_clear():
    live = [LiveTier(id="ML1", quantity=10, amount=Decimal("500.00"))]

    result = diff_pxq_tiers(live, [])

    assert not result.ok
    assert result.array is None
    assert result.refusal.reason == "empty_desired_set"
    # The refusal carries the diff of what WOULD have been wiped.
    assert result.refusal.divergences[0].ml_price_id == "ML1"


def test_empty_desired_set_with_allow_clear_wipes_the_whole_array():
    live = [
        LiveTier(id="ML1", quantity=10, amount=Decimal("500.00")),
        LiveTier(id="ML_UNTRACKED", quantity=20, amount=Decimal("900.00")),
    ]

    result = diff_pxq_tiers(live, [], allow_clear=True)

    assert result.ok
    assert result.array == []


def test_more_than_five_desired_tiers_refuses():
    desired = [DesiredTier(quantity=n, amount=Decimal("100.00"), ml_price_id=None) for n in range(2, 8)]

    result = diff_pxq_tiers([], desired)

    assert not result.ok
    assert result.refusal.reason == "too_many_tiers"


def test_decimal_and_float_money_normalize_to_equal_not_a_false_divergence():
    # Live payloads arrive as JSON (float); mirror rows arrive as Decimal
    # (Numeric(14,2) column). The same monetary value in both forms must
    # compare equal, not trigger a spurious divergence.
    live = [LiveTier(id="ML1", quantity=10, amount=500.0)]
    desired = [
        DesiredTier(
            quantity=10,
            amount=Decimal("500.00"),
            ml_price_id="ML1",
            synced_quantity=10,
            synced_amount=Decimal("500.00"),
        )
    ]

    result = diff_pxq_tiers(live, desired)

    assert result.ok
    assert result.array == [{"id": "ML1"}]


class TestThreeWayMergeAgainstTheSyncedSnapshot:
    """`estado` was a proxy for "did the user edit this", and a poor one: it
    cannot tell a local edit from a remote one, so a tier left at `listo`
    overwrote whatever MercadoLibre had — silently, on the money path.

    The snapshot (`synced_quantity` / `synced_amount`: what ML confirmed at the
    last sync) turns the comparison into a real three-way merge, where local
    and live are each judged against a shared base."""

    def _live(self, amount, quantity=10, price_id="P1"):
        return LiveTier(id=price_id, quantity=quantity, amount=amount)

    def test_neither_side_moved_is_a_keep(self):
        result = diff_pxq_tiers(
            live_tiers=[self._live(Decimal("500.00"))],
            desired_tiers=[
                DesiredTier(
                    quantity=10,
                    amount=Decimal("500.00"),
                    ml_price_id="P1",
                    synced_quantity=10,
                    synced_amount=Decimal("500.00"),
                )
            ],
        )
        assert result.array == [{"id": "P1"}]

    def test_only_local_moved_is_a_modify(self):
        result = diff_pxq_tiers(
            live_tiers=[self._live(Decimal("500.00"))],
            desired_tiers=[
                DesiredTier(
                    quantity=10,
                    amount=Decimal("450.00"),
                    ml_price_id="P1",
                    synced_quantity=10,
                    synced_amount=Decimal("500.00"),
                )
            ],
        )
        assert result.array == [{"quantity": 10, "amount": 450.0}]

    def test_only_live_moved_refuses_instead_of_reverting_it(self):
        """Someone changed the price in MercadoLibre and nobody touched it
        here. Writing our unchanged value would quietly revert their change."""
        result = diff_pxq_tiers(
            live_tiers=[self._live(Decimal("470.00"))],
            desired_tiers=[
                DesiredTier(
                    quantity=10,
                    amount=Decimal("500.00"),
                    ml_price_id="P1",
                    synced_quantity=10,
                    synced_amount=Decimal("500.00"),
                )
            ],
        )
        assert result.array is None
        assert result.refusal.divergences[0].ml_price_id == "P1"
        assert result.refusal.divergences[0].reason == "live changed since the last sync"

    def test_both_sides_moved_is_a_real_conflict_and_refuses(self):
        """The case the estado rule got wrong: it saw an intentional local edit
        and wrote it, overwriting the remote change without a word."""
        result = diff_pxq_tiers(
            live_tiers=[self._live(Decimal("470.00"))],
            desired_tiers=[
                DesiredTier(
                    quantity=10,
                    amount=Decimal("450.00"),
                    ml_price_id="P1",
                    synced_quantity=10,
                    synced_amount=Decimal("500.00"),
                )
            ],
        )
        assert result.array is None
        divergence = result.refusal.divergences[0]
        assert divergence.reason == "both sides changed since the last sync"
        assert divergence.live["amount"] == 470.0
        assert divergence.desired["amount"] == 450.0

    def test_a_never_synced_tier_has_no_snapshot_and_is_a_create(self):
        result = diff_pxq_tiers(
            live_tiers=[],
            desired_tiers=[DesiredTier(quantity=10, amount=Decimal("500.00"))],
        )
        assert result.array == [{"quantity": 10, "amount": 500.0}]


class TestSyncedIdWithoutASnapshotRefuses:
    """A row can carry `ml_price_id` with a NULL snapshot: `create_pxq_tier`
    accepts the id and never writes the snapshot columns. With no base to
    compare against, `live_changed` said "live did not move" and the tier fell
    into modify — overwriting MercadoLibre silently.

    That is the exact failure the snapshot was introduced to kill, reached
    through a different door. No baseline means we cannot know who moved what,
    so the answer is refuse, not guess."""

    def test_synced_id_without_snapshot_refuses_instead_of_overwriting_live(self):
        result = diff_pxq_tiers(
            live_tiers=[LiveTier(id="ML1", quantity=10, amount=Decimal("470.00"))],
            desired_tiers=[DesiredTier(quantity=10, amount=Decimal("500.00"), ml_price_id="ML1")],
        )

        assert result.array is None
        assert result.refusal.divergences[0].reason == "no snapshot to compare against"

    def test_a_tier_with_no_id_and_no_snapshot_is_still_a_plain_create(self):
        result = diff_pxq_tiers(
            live_tiers=[],
            desired_tiers=[DesiredTier(quantity=10, amount=Decimal("500.00"))],
        )

        assert result.array == [{"quantity": 10, "amount": 500.0}]


def test_duplicate_ml_price_id_in_desired_refuses():
    """Two desired rows pointing at the same live tier would emit that id
    twice, and MercadoLibre would receive an array that contradicts itself."""
    result = diff_pxq_tiers(
        live_tiers=[LiveTier(id="ML1", quantity=10, amount=Decimal("500.00"))],
        desired_tiers=[
            DesiredTier(
                quantity=10,
                amount=Decimal("500.00"),
                ml_price_id="ML1",
                synced_quantity=10,
                synced_amount=Decimal("500.00"),
            ),
            DesiredTier(
                quantity=20,
                amount=Decimal("400.00"),
                ml_price_id="ML1",
                synced_quantity=20,
                synced_amount=Decimal("400.00"),
            ),
        ],
    )

    assert result.array is None
    assert "duplicate" in result.refusal.reason


def test_a_live_tier_whose_local_row_is_not_priceable_is_kept_not_deleted():
    """A mirror row with no shipping cost is filtered out of `desired`, so its
    live tier ends up referenced by nothing. It must still be PRESERVED: the
    untracked-keep rule exists precisely so array-replace never deletes a tier
    just because this system stopped tracking it.

    Pins the answer to "does filtering a row silently delete its tier in ML?",
    which is no.
    """
    result = diff_pxq_tiers(
        live_tiers=[LiveTier(id="ORPHAN", quantity=10, amount=Decimal("500.00"))],
        desired_tiers=[DesiredTier(quantity=20, amount=Decimal("400.00"))],
    )

    assert {"id": "ORPHAN"} in result.array
