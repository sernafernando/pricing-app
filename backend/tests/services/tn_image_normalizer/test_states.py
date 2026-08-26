"""Tests for the shared pipeline state vocabulary.

These read like tautologies and are not. They pin down the two properties
the whole change's safety rests on — the delete gate has exactly one
member, and `inconclusive` is nobody's synonym — so that a future edit
widening either one fails here, loudly, instead of in a live store.
"""

from app.services.tn_image_normalizer import states


class TestDeleteGate:
    def test_exactly_one_state_authorises_a_delete(self) -> None:
        # The single most important invariant in this change. Widening this
        # set is how a product ends up with zero images.
        assert states.TXN_STATES_DELETE_ELIGIBLE == frozenset({states.TXN_ALL_CONFIRMED})

    def test_partial_confirmation_cannot_delete(self) -> None:
        assert states.TXN_PARTIAL not in states.TXN_STATES_DELETE_ELIGIBLE

    def test_inconclusive_cannot_delete(self) -> None:
        assert states.TXN_INCONCLUSIVE not in states.TXN_STATES_DELETE_ELIGIBLE

    def test_a_failed_baseline_read_cannot_delete(self) -> None:
        # No baseline means no way to scope a delete to the pre-existing
        # ids, so this must never be delete-eligible.
        assert states.TXN_ABORTED_NO_BASELINE not in states.TXN_STATES_DELETE_ELIGIBLE

    def test_states_that_wrote_nothing_are_never_delete_eligible(self) -> None:
        assert not (states.TXN_STATES_WROTE_NOTHING & states.TXN_STATES_DELETE_ELIGIBLE)


class TestInconclusiveIsItsOwnThing:
    def test_upload_inconclusive_is_distinct_from_every_other_item_state(self) -> None:
        others = {
            states.ITEM_UPLOAD_CONFIRMED,
            states.ITEM_UPLOAD_REJECTED,
            states.ITEM_UPLOAD_ABSENT,
        }
        assert states.ITEM_UPLOAD_INCONCLUSIVE not in others

    def test_upload_absent_is_reviewable_not_a_success(self) -> None:
        # Absence proves an upload failed, not that old images are
        # expendable — so it must surface to an operator.
        assert states.ITEM_UPLOAD_ABSENT in states.ITEM_STATES_REVIEWABLE
        assert states.ITEM_UPLOAD_ABSENT not in states.ITEM_STATES_OPEN

    def test_inconclusive_is_reviewable(self) -> None:
        assert states.ITEM_UPLOAD_INCONCLUSIVE in states.ITEM_STATES_REVIEWABLE


class TestVocabularyHygiene:
    def test_open_and_reviewable_item_states_do_not_overlap(self) -> None:
        # A row cannot simultaneously still have work to do and be waiting
        # on a human.
        assert not (states.ITEM_STATES_OPEN & states.ITEM_STATES_REVIEWABLE)

    def test_no_source_images_is_reviewable_not_silently_dropped(self) -> None:
        assert states.ITEM_NO_SOURCE_IMAGES in states.ITEM_STATES_REVIEWABLE

    def test_every_item_state_fits_the_persisted_column(self) -> None:
        # `TnImageNormalizationItem.state` is String(32).
        item_states = [
            value for name, value in vars(states).items() if name.startswith("ITEM_") and isinstance(value, str)
        ]
        assert item_states, "expected to find ITEM_* state constants"
        too_long = [s for s in item_states if len(s) > 32]
        assert too_long == []

    def test_item_states_are_unique(self) -> None:
        item_states = [
            value for name, value in vars(states).items() if name.startswith("ITEM_") and isinstance(value, str)
        ]
        assert len(item_states) == len(set(item_states))
