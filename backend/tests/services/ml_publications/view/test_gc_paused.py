"""`gc_paused`: the cyclic collector is off inside the block and back as it was after it."""

from __future__ import annotations

import gc

import pytest

from app.services.ml_publications.view.markup_service import gc_paused


@pytest.fixture(autouse=True)
def collector_on():
    was = gc.isenabled()
    gc.enable()
    yield
    gc.enable() if was else gc.disable()


def test_the_collector_is_off_inside_and_on_after() -> None:
    with gc_paused():
        assert not gc.isenabled()
    assert gc.isenabled()


def test_it_is_restored_when_the_block_raises() -> None:
    with pytest.raises(RuntimeError):
        with gc_paused():
            raise RuntimeError("boom")
    assert gc.isenabled()


def test_nested_pauses_do_not_turn_it_on_early_and_a_disabled_collector_stays_disabled() -> None:
    with gc_paused():
        with gc_paused():
            assert not gc.isenabled()
        assert not gc.isenabled()  # the outer block still holds the pause
    assert gc.isenabled()
    gc.disable()
    with gc_paused():
        pass
    assert not gc.isenabled()  # it was off before: not ours to turn on
