"""
Unit tests for `select_promo_resolver` (D2 decision table) —
`app/services/promo_filter_resolver.py`.

Single source of truth for (promo_tipos, promo_estado) -> resolver
dispatch, shared by `productos_listing.py` (list-level fold) and
`productos_detail.py` (lite per-MLA `matches_filter`).

TDD: written before the implementation (T5, RED).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.promo_filter_resolver import PromoResolverFns, select_promo_resolver


def _fns() -> PromoResolverFns:
    return PromoResolverFns(
        active_promo_type=MagicMock(name="active_promo_type", return_value={"MLA1"}),
        started=MagicMock(name="started", return_value={"MLA2"}),
        candidate_only=MagicMock(name="candidate_only", return_value={"MLA3"}),
        candidate_only_for_types=MagicMock(name="candidate_only_for_types", return_value={"MLA4"}),
    )


class TestSelectPromoResolverDecisionTable:
    def test_tipos_present_disponible_dispatches_active_promo_type_applied_only_false(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, ["SMART"], "disponible")
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.active_promo_type.assert_called_once_with(["SMART"], False, mla_ids=None)
        fns.started.assert_not_called()
        fns.candidate_only.assert_not_called()
        fns.candidate_only_for_types.assert_not_called()

    def test_tipos_present_no_estado_defaults_to_disponible(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, ["SMART"], None)
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.active_promo_type.assert_called_once_with(["SMART"], False, mla_ids=None)

    def test_tipos_present_aplicada_dispatches_active_promo_type_applied_only_true(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, ["SMART"], "aplicada")
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.active_promo_type.assert_called_once_with(["SMART"], True, mla_ids=None)
        fns.started.assert_not_called()
        fns.candidate_only.assert_not_called()
        fns.candidate_only_for_types.assert_not_called()

    def test_tipos_present_sin_aplicar_dispatches_candidate_only_for_types(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, ["SMART"], "sin_aplicar")
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.candidate_only_for_types.assert_called_once_with(["SMART"], mla_ids=None)
        fns.active_promo_type.assert_not_called()
        fns.started.assert_not_called()
        fns.candidate_only.assert_not_called()

    def test_no_tipos_legacy_aplicada_dispatches_started(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, None, None, con_promo_aplicada=True)
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.started.assert_called_once_with(mla_ids=None)
        fns.active_promo_type.assert_not_called()
        fns.candidate_only.assert_not_called()
        fns.candidate_only_for_types.assert_not_called()

    def test_no_tipos_legacy_sin_aplicar_dispatches_candidate_only(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, None, None, con_promo_sin_aplicar=True)
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.candidate_only.assert_called_once_with(mla_ids=None)
        fns.active_promo_type.assert_not_called()
        fns.started.assert_not_called()
        fns.candidate_only_for_types.assert_not_called()

    def test_no_filter_returns_none(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, None, None)

        assert entry is None
        fns.active_promo_type.assert_not_called()
        fns.started.assert_not_called()
        fns.candidate_only.assert_not_called()
        fns.candidate_only_for_types.assert_not_called()

    def test_empty_tipos_list_treated_as_absent(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, [], None, con_promo_aplicada=True)

        assert entry is not None
        resolver, _log_context = entry
        resolver()
        fns.started.assert_called_once_with(mla_ids=None)

    def test_legacy_params_ignored_when_tipos_present(self) -> None:
        """D2 precedence: promo_tipos present -> legacy con_promo_aplicada /
        con_promo_sin_aplicar are IGNORED entirely (only tipos + estado
        drive dispatch). Regression proof companion to the integration-level
        rewrite (T7)."""
        fns = _fns()

        entry = select_promo_resolver(fns, ["SMART"], "aplicada", con_promo_aplicada=True, con_promo_sin_aplicar=True)
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.active_promo_type.assert_called_once_with(["SMART"], True, mla_ids=None)
        fns.started.assert_not_called()
        fns.candidate_only.assert_not_called()

    def test_mla_ids_forwarded_to_resolver(self) -> None:
        fns = _fns()

        entry = select_promo_resolver(fns, ["SMART"], "aplicada", mla_ids=["MLA9"])
        assert entry is not None
        resolver, _log_context = entry
        resolver()

        fns.active_promo_type.assert_called_once_with(["SMART"], True, mla_ids=["MLA9"])
