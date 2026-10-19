"""`app/scripts/drain_promo_refresh.py` is a thin manual entry point over `promo_refresh_drain.drain`.

The scheduled drain is the `promo_write.refresh` worker handler (tests/workers/handlers/test_promo_refresh.py);
the script only runs one pass by hand, with no deadline (the per-pass row cap still bounds it).
"""

from __future__ import annotations

from unittest import mock

from app.scripts import drain_promo_refresh
from app.services import promo_refresh_drain


def test_main_runs_one_pass_of_the_shared_drain() -> None:
    with mock.patch.object(promo_refresh_drain, "drain", return_value={"refreshed": 0}) as run:
        drain_promo_refresh.main()

    run.assert_called_once_with(deadline=None)


def test_the_script_holds_no_drain_logic_of_its_own() -> None:
    for name in ("run_drain", "_drain_one", "_due_mlas", "_try_acquire_drain_lock", "MAX_ROWS_PER_PASS"):
        assert not hasattr(drain_promo_refresh, name), name
