"""Part of the Publicaciones ML filter matrix (`test_filter_matrix_plans_volume_postgres.py`, whose docstring
says what runs where), in its own module so CI's volume job (`--dist loadfile`) runs it on another worker."""

from __future__ import annotations

import pytest

from tests.services.ml_publications.view.test_filter_matrix_plans_volume_postgres import (  # noqa: F401
    EACH_B,
    assert_each_filter,
    seeded,
    session,
    world,
)

pytestmark = [pytest.mark.postgres, pytest.mark.volume]


@pytest.mark.parametrize("name, kwargs", EACH_B)
def test_each_filter_alone_plans_and_answers(session, monkeypatch, name, kwargs) -> None:  # noqa: F811
    assert_each_filter(session, monkeypatch, kwargs)
