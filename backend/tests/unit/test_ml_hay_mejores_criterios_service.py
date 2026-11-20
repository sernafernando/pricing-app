"""Unit tests for hay_mejores application criteria (C1 gate + defaults)."""

from __future__ import annotations

from decimal import Decimal

from app.services.ml_hay_mejores_criterios_service import (
    catalog_win_con_precio,
    default_criterios,
    markup_pasa_c1,
    markup_pasa_c2,
)


class TestMarkupPasaC1:
    def test_inactive_always_passes(self) -> None:
        assert markup_pasa_c1(
            -50.0,
            c1_activo=False,
            c1_markup_min=Decimal("0"),
            c1_markup_max=Decimal("20"),
        )

    def test_active_requires_markup(self) -> None:
        assert not markup_pasa_c1(
            None,
            c1_activo=True,
            c1_markup_min=None,
            c1_markup_max=None,
        )

    def test_floor_and_ceiling(self) -> None:
        assert markup_pasa_c1(
            10.0,
            c1_activo=True,
            c1_markup_min=Decimal("5"),
            c1_markup_max=Decimal("15"),
        )
        assert not markup_pasa_c1(
            4.0,
            c1_activo=True,
            c1_markup_min=Decimal("5"),
            c1_markup_max=Decimal("15"),
        )
        assert not markup_pasa_c1(
            16.0,
            c1_activo=True,
            c1_markup_min=Decimal("5"),
            c1_markup_max=Decimal("15"),
        )

    def test_open_sided_band(self) -> None:
        assert markup_pasa_c1(
            100.0,
            c1_activo=True,
            c1_markup_min=Decimal("0"),
            c1_markup_max=None,
        )
        assert not markup_pasa_c1(
            -1.0,
            c1_activo=True,
            c1_markup_min=Decimal("0"),
            c1_markup_max=None,
        )


class TestDefaultCriterios:
    def test_defaults_match_product(self) -> None:
        view = default_criterios("MLA1")
        assert view.exists is False
        assert view.c1_activo is False
        assert view.c2_solo_markup_positivo is True
        assert view.auto_aplicacion is False
        assert view.sellers_excluidos == []


class TestCatalogWinAndC2:
    def test_catalog_win_requires_strictly_cheaper(self) -> None:
        assert catalog_win_con_precio(900.0, 1000.0)
        assert not catalog_win_con_precio(1000.0, 1000.0)
        assert not catalog_win_con_precio(900.0, None)

    def test_c2_inactive_never_passes(self) -> None:
        assert not markup_pasa_c2(10.0, c2_activo=False, c2_solo_markup_positivo=True)

    def test_c2_solo_positivo_requires_gt_zero(self) -> None:
        assert markup_pasa_c2(0.1, c2_activo=True, c2_solo_markup_positivo=True)
        assert not markup_pasa_c2(0.0, c2_activo=True, c2_solo_markup_positivo=True)
        assert not markup_pasa_c2(-1.0, c2_activo=True, c2_solo_markup_positivo=True)

    def test_c2_allows_negative_when_toggle_off(self) -> None:
        assert markup_pasa_c2(-5.0, c2_activo=True, c2_solo_markup_positivo=False)


