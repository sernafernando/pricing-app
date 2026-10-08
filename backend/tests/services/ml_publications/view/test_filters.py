"""P5.T1: the filter model of `/ml-publications/view/items` (design §2): parsing, validation and `q` rules.

Pure: no database. The SQL these filters produce is exercised on Postgres in `test_listing_postgres.py`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.ml_publications.view.filters import (
    EVENT_SINCE,
    EVENT_TYPES,
    FilterError,
    PublicationFilter,
    SearchTerm,
    escape_like,
    normalize_q,
    parse_filter,
)


class TestDefaults:
    def test_no_param_is_an_empty_filter(self) -> None:
        assert parse_filter() == PublicationFilter()

    def test_blank_values_are_no_filter(self) -> None:
        f = parse_filter(q="   ", estado="", tiendas=" , ", marcas="", familia="  ")
        assert f == PublicationFilter()


class TestSearchTerm:
    @pytest.mark.parametrize("raw", ["MLA935110613", "mla935110613", "  MlA935110613  "])
    def test_an_mla_id_is_an_exact_item_id_in_canonical_case(self, raw: str) -> None:
        assert normalize_q(raw) == SearchTerm("item_id", "MLA935110613")

    def test_digits_only_are_exact_keys_not_a_substring(self) -> None:
        # digits are an MLA number, a seller SKU or an EAN: all of them are exact keys
        assert normalize_q("7790001234567") == SearchTerm("digits", "7790001234567")

    def test_any_other_text_is_a_substring_search(self) -> None:
        assert normalize_q("  Router  AC1200 ") == SearchTerm("text", "Router  AC1200")

    def test_mla_with_letters_after_the_digits_is_text(self) -> None:
        assert normalize_q("MLA123abc") == SearchTerm("text", "MLA123abc")

    def test_blank_is_no_search(self) -> None:
        assert normalize_q("") is None
        assert normalize_q("   ") is None
        assert normalize_q(None) is None

    def test_more_than_100_characters_is_rejected(self) -> None:
        assert normalize_q("x" * 100) == SearchTerm("text", "x" * 100)
        with pytest.raises(FilterError) as caught:
            normalize_q("x" * 101)
        assert caught.value.field == "q"

    def test_parse_filter_carries_the_normalized_term(self) -> None:
        assert parse_filter(q="mla1").q == SearchTerm("item_id", "MLA1")


class TestLikeEscaping:
    def test_wildcards_and_the_escape_character_are_literal(self) -> None:
        assert escape_like("50%_off") == r"50\%\_off"
        assert escape_like("a\\b") == "a\\\\b"

    def test_plain_text_is_unchanged(self) -> None:
        assert escape_like("router") == "router"


class TestCsvParams:
    def test_status_is_a_csv_of_known_values_without_duplicates(self) -> None:
        assert parse_filter(estado="active, paused,active").status == ("active", "paused")

    def test_gone_is_a_status_token_of_its_own(self) -> None:
        assert parse_filter(estado="gone").status == ("gone",)

    def test_no_status_is_a_status_token_of_its_own(self) -> None:
        # the status facet offers `sin_estado` for items ML sent without a status: the filter must take it back
        assert parse_filter(estado="sin_estado,active").status == ("sin_estado", "active")
        assert parse_filter(estado_excluir="sin_estado").status_exclude == ("sin_estado",)

    def test_status_exclude_has_the_same_vocabulary(self) -> None:
        assert parse_filter(estado_excluir="closed,inactive").status_exclude == ("closed", "inactive")

    @pytest.mark.parametrize("param", ["estado", "estado_excluir"])
    def test_unknown_status_is_rejected_naming_the_param(self, param: str) -> None:
        with pytest.raises(FilterError) as caught:
            parse_filter(**{param: "active,bogus"})
        assert caught.value.field == param
        assert "bogus" in str(caught.value)

    def test_stores_are_ids_and_none_means_no_store(self) -> None:
        f = parse_filter(tiendas="2645,none,12")
        assert f.stores == (2645, 12)
        assert f.no_store is True

    def test_only_none_is_a_no_store_filter(self) -> None:
        f = parse_filter(tiendas="none")
        assert (f.stores, f.no_store) == ((), True)

    def test_a_store_that_is_not_a_number_is_rejected(self) -> None:
        with pytest.raises(FilterError) as caught:
            parse_filter(tiendas="12,abc")
        assert caught.value.field == "tiendas"

    def test_brands_and_categories_are_free_text_trimmed(self) -> None:
        f = parse_filter(marcas=" TP-Link ,Tenda", categorias="Routers")
        assert f.marcas == ("TP-Link", "Tenda")
        assert f.categorias == ("Routers",)

    def test_subcategories_are_numeric_ids(self) -> None:
        assert parse_filter(subcategorias="3,5").subcategorias == (3, 5)
        with pytest.raises(FilterError) as caught:
            parse_filter(subcategorias="x")
        assert caught.value.field == "subcategorias"

    def test_pms_are_numeric_user_ids(self) -> None:
        assert parse_filter(pms="7,9").pms == (7, 9)
        with pytest.raises(FilterError):
            parse_filter(pms="seven")

    def test_family_is_one_bigint(self) -> None:
        assert parse_filter(familia="1234567890123").family_id == 1234567890123
        with pytest.raises(FilterError) as caught:
            parse_filter(familia="1,2")
        assert caught.value.field == "familia"

    @pytest.mark.parametrize(
        "param, attr, good",
        [
            ("tipo", "listing", "clasica,premium,catalogo,full"),
            ("vinculo", "link", "auto,manual,sin_producto,conflicto,no_evaluado"),
            ("stock", "stock", "sin_stock,full_sin_stock"),
        ],
    )
    def test_closed_vocabularies_accept_every_documented_value_and_reject_the_rest(
        self, param: str, attr: str, good: str
    ) -> None:
        assert getattr(parse_filter(**{param: good}), attr) == tuple(good.split(","))
        with pytest.raises(FilterError) as caught:
            parse_filter(**{param: "nope"})
        assert caught.value.field == param


class TestEventFilter:
    def test_every_real_event_type_is_accepted(self) -> None:
        assert "price_changed" in EVENT_TYPES and "item_restored" in EVENT_TYPES
        assert parse_filter(evento=",".join(sorted(EVENT_TYPES))).event_types == tuple(sorted(EVENT_TYPES))

    def test_an_invented_event_type_is_rejected(self) -> None:
        with pytest.raises(FilterError) as caught:
            parse_filter(evento="venta_registrada")
        assert caught.value.field == "evento"

    @pytest.mark.parametrize(
        "raw, delta", [("24h", timedelta(hours=24)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30))]
    )
    def test_evento_desde_maps_to_an_interval(self, raw: str, delta: timedelta) -> None:
        f = parse_filter(evento="price_changed", evento_desde=raw)
        assert f.event_since == delta == EVENT_SINCE[raw]

    def test_evento_desde_outside_the_vocabulary_is_rejected(self) -> None:
        with pytest.raises(FilterError) as caught:
            parse_filter(evento="price_changed", evento_desde="1y")
        assert caught.value.field == "evento_desde"

    def test_evento_desde_without_evento_is_rejected(self) -> None:
        with pytest.raises(FilterError) as caught:
            parse_filter(evento_desde="7d")
        assert caught.value.field == "evento_desde"

    def test_the_filter_says_whether_it_needs_the_events_flag(self) -> None:
        assert parse_filter(evento="price_changed").needs_events is True
        assert parse_filter(estado="active").needs_events is False
