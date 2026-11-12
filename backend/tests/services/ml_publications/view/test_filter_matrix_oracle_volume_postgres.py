"""Part of the Publicaciones ML filter matrix (`test_filter_matrix_plans_volume_postgres.py`), in its own module so
CI's volume job (`--dist loadfile`) runs it on another worker."""

from __future__ import annotations

import pytest

from tests.services.ml_publications.view.test_filter_matrix_plans_volume_postgres import (  # noqa: F401
    ORACLE,
    assert_previous_answers,
    seeded,
    session,
    world,
)

pytestmark = [pytest.mark.postgres, pytest.mark.volume]


@pytest.mark.parametrize("name, kwargs, promo, trees", ORACLE)
def test_every_read_answers_what_the_previous_shapes_answered(session, monkeypatch, name, kwargs, promo, trees) -> None:  # noqa: F811
    assert_previous_answers(session, monkeypatch, kwargs, promo, trees)
