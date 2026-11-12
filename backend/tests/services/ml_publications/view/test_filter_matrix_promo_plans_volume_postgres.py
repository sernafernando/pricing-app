"""Part of the Publicaciones ML filter matrix (`test_filter_matrix_plans_volume_postgres.py`), in its own module so
CI's volume job (`--dist loadfile`) runs it on another worker."""

from __future__ import annotations

import pytest

from tests.services.ml_publications.view.test_filter_matrix_plans_volume_postgres import (  # noqa: F401
    PROMO_SCENARIOS,
    assert_no_per_row_plan,
    seeded,
    session,
    world,
)

pytestmark = [pytest.mark.postgres, pytest.mark.volume]


@pytest.mark.parametrize("name, kwargs, promo, trees", PROMO_SCENARIOS)
def test_no_read_runs_a_per_row_plan_with_the_promo_set(session, name, kwargs, promo, trees) -> None:  # noqa: F811
    assert_no_per_row_plan(session, name, kwargs, promo, trees)
