"""Tests for `pxq_confirm`: matching the post-write re-read to mirror rows.

This logic decides whether the snapshot advances, and a stale snapshot is what
lets the next sync overwrite somebody else's change. Five separate defects
were found here while it lived inside the orchestration module — several of
them introduced while fixing the previous one — which is why it now has its
own module and its own tests.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.ml_pxq_tier import (
    ESTADO_DESCONOCIDO,
    ESTADO_LISTO,
    ESTADO_SINCRONIZADO,
)
from app.services import pxq_confirm, pxq_diff
from app.services.pxq_confirm import (
    ImportedTierFields,
    is_priceable,
    live_entry_to_tier_fields,
    remap_and_confirm,
)


class TestPartialConfirmationIsNotSuccess:
    """The previous fix covered the case where the confirmation re-read failed
    ENTIRELY. It left open the case where the re-read arrived but one row did
    not match: that row goes to `desconocido` and the caller still received
    `synced: True` with a 200. Same defect, one branch over."""

    def test_a_row_that_cannot_be_confirmed_makes_the_whole_outcome_unconfirmed(self) -> None:

        rows = [
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=10,
                precio_unitario=Decimal("500.00"),
                ml_price_id="ML1",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            ),
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=20,
                precio_unitario=Decimal("400.00"),
                ml_price_id="ML2",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            ),
        ]
        # The re-read only accounts for the first row.
        confirmed = [{"id": "ML1", "quantity": 10, "amount": 500.00}]

        all_confirmed = remap_and_confirm(rows, confirmed)

        assert all_confirmed is False
        assert rows[1].estado == ESTADO_DESCONOCIDO
        assert rows[1].cantidad_sincronizada is None

    def test_every_row_confirmed_reports_confirmed(self) -> None:
        from app.models.ml_pxq_tier import ESTADO_SINCRONIZADO

        rows = [
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=10,
                precio_unitario=Decimal("500.00"),
                ml_price_id="ML1",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            )
        ]
        confirmed = [{"id": "ML1", "quantity": 10, "amount": 500.00}]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].cantidad_sincronizada == 10

    def test_money_is_matched_as_decimal_not_binary_float(self) -> None:
        """The one comparison deciding whether the snapshot advances was
        float == float, in a module whose whole point is that a stale snapshot
        reintroduces the overwrite bug."""

        from app.models.ml_pxq_tier import ESTADO_SINCRONIZADO

        rows = [
            SimpleNamespace(
                estado=ESTADO_SINCRONIZADO,
                cantidad_minima=3,
                precio_unitario=Decimal("1234.56"),
                ml_price_id="ML1",
                costo_envio_total=Decimal("3200.00"),
                cantidad_sincronizada=None,
                precio_sincronizado=None,
            )
        ]
        confirmed = [{"id": "ML1", "quantity": 3, "amount": "1234.56"}]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].precio_sincronizado == Decimal("1234.56")


class TestOnlyTiersWithAShippingCostAreEverWritten:
    """The founding rule of this feature: a tier without a resolved
    whole-shipment cost is never priced and never written.

    Priceability reads the DATA, not `estado` — nothing recomputes `estado`
    when a cost is cleared, so a row sitting at `listo` or `desconocido` with a
    NULL cost would otherwise go straight into the write."""

    def _row(self, estado, cost):
        return SimpleNamespace(estado=estado, costo_envio_total=cost)

    def test_a_row_without_a_shipping_cost_is_not_priceable_whatever_its_estado(self) -> None:
        assert is_priceable(self._row(ESTADO_LISTO, None)) is False
        assert is_priceable(self._row(ESTADO_DESCONOCIDO, None)) is False
        assert is_priceable(self._row(ESTADO_SINCRONIZADO, None)) is False

    def test_a_row_with_a_shipping_cost_is_priceable(self) -> None:
        assert is_priceable(self._row(ESTADO_LISTO, Decimal("3200.00"))) is True


class TestConfirmationMatchesByIdWhenItIsKnown:
    """Matching purely on (quantity, amount) lets a row claim a tier it did
    not create. An untracked tier — one alive in ML that we preserve as a keep
    and never owned — with the same quantity and price as one of our rows can
    be claimed by it, and then the next sync will happily modify or delete
    somebody else's tier. Which row wins is decided by list order.

    When the row already carries an ml_price_id, that id IS the answer; only
    creates need to be matched by value."""

    def _row(self, quantity, amount, price_id=None, synced=False):
        return SimpleNamespace(
            estado="listo",
            cantidad_minima=quantity,
            precio_unitario=amount,
            costo_envio_total=Decimal("3200.00"),
            ml_price_id=price_id,
            cantidad_sincronizada=quantity if synced else None,
            precio_sincronizado=amount if synced else None,
        )

    def test_a_row_with_an_id_does_not_claim_an_untracked_tier_with_the_same_values(self) -> None:

        # A keep: values still equal the snapshot, so this row's id survived
        # the write and is the only correct match.
        rows = [self._row(10, Decimal("500.00"), "OURS", synced=True)]
        # The untracked tier is listed FIRST and has identical values.
        confirmed = [
            {"id": "THEIRS", "quantity": 10, "amount": "500.00"},
            {"id": "OURS", "quantity": 10, "amount": "500.00"},
        ]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].ml_price_id == "OURS"

    def test_a_created_row_without_an_id_still_matches_by_value(self) -> None:

        rows = [self._row(20, Decimal("400.00"))]
        confirmed = [{"id": "NEW", "quantity": 20, "amount": "400.00"}]

        assert remap_and_confirm(rows, confirmed) is True
        assert rows[0].ml_price_id == "NEW"


def test_a_created_row_cannot_adopt_an_untracked_tier_with_identical_values() -> None:
    """The case the keep-vs-id test does not reach. A create has no id, so it
    must match by value — and an untracked tier we preserved but never owned
    can carry the same quantity and price. Whoever is first in the re-read
    wins, and adopting a stranger's tier means the next sync modifies or
    deletes it.

    `untracked_ids` exists to claim those up front. It was accepted as a
    parameter, documented as the protection, and never passed by the one
    caller — the guard was there and unplugged."""

    row = SimpleNamespace(
        estado="listo",
        cantidad_minima=10,
        precio_unitario=Decimal("500.00"),
        costo_envio_total=Decimal("3200.00"),
        ml_price_id=None,
        cantidad_sincronizada=None,
        precio_sincronizado=None,
    )
    confirmed = [
        {"id": "THEIRS", "quantity": 10, "amount": "500.00"},
        {"id": "OURS", "quantity": 10, "amount": "500.00"},
    ]

    assert remap_and_confirm([row], confirmed, untracked_ids=["THEIRS"]) is True
    assert row.ml_price_id == "OURS"


def test_a_keep_whose_id_vanished_from_the_reread_is_not_confirmed() -> None:
    """Introduced by the two-pass matcher: pass 1 looked the id up and, on a
    miss, did nothing at all — no desconocido, no all_confirmed=False — while
    pass 2 skipped the row as "already resolved". It fell through the gap, and
    the caller got synced: True.

    Concretely: ML applies the write but rotates the id. The row stays
    `sincronizado` pointing at an id that no longer exists, the next sync
    refuses with `mirror ml_price_id absent from live read`, and the success
    the user was shown was never true."""

    row = SimpleNamespace(
        estado="sincronizado",
        cantidad_minima=10,
        precio_unitario=Decimal("500.00"),
        costo_envio_total=Decimal("3200.00"),
        ml_price_id="ML1",
        cantidad_sincronizada=10,
        precio_sincronizado=Decimal("500.00"),
    )
    # ML rotated the id: our keep is gone from the confirmation.
    confirmed = [{"id": "ML9", "quantity": 10, "amount": "500.00"}]

    assert remap_and_confirm([row], confirmed) is False
    assert row.estado == ESTADO_DESCONOCIDO


class TestLiveEntryToTierFields:
    """Maps ONE raw live ML entry to the fields of a new mirror row.

    The snapshot columns are the whole reason this helper exists rather than
    the caller building the row inline: `diff_pxq_tiers` refuses FOREVER, with
    reason "no snapshot to compare against" (`pxq_diff.py:366`), any row that
    carries an `ml_price_id` but records no baseline. A row imported without
    its snapshot is therefore permanently un-syncable — the exact shape of
    damage this whole change exists to repair.
    """

    def _entry(self, **overrides) -> dict:
        entry = {"id": "MLP-1", "quantity": 10, "amount": "500.00"}
        entry.update(overrides)
        return entry

    def test_a_numeric_id_is_coerced_to_a_string(self) -> None:
        """The proxy hands `id` back as a NUMBER. `ml_price_id` is
        `String(64)`, and every other reader in this feature already does
        `str(entry["id"])` — an int here would compare unequal to the stored
        string on the very next sync and read as "absent from live read"."""
        fields = live_entry_to_tier_fields(self._entry(id=12345))

        assert fields.ml_price_id == "12345"
        assert isinstance(fields.ml_price_id, str)

    def test_a_float_amount_goes_through_decimal_str_not_decimal_float(self) -> None:
        """`Decimal(0.1)` is 0.1000000000000000055511151231257827..., which
        compares unequal to the `Decimal("0.1")` the DB hands back — a false
        "differs" verdict on every subsequent sync."""
        fields = live_entry_to_tier_fields(self._entry(amount=0.1))

        assert fields.precio_unitario == Decimal("0.1")
        assert fields.precio_unitario != Decimal(0.1)

    def test_the_snapshot_equals_the_imported_values(self) -> None:
        """On an import the local value IS the value ML reported, in the same
        read, so the baseline is already correct and there is nothing to have
        diverged from."""
        fields = live_entry_to_tier_fields(self._entry(quantity=6, amount="1234.56"))

        assert fields.cantidad_minima == 6
        assert fields.precio_unitario == Decimal("1234.56")
        assert fields.cantidad_sincronizada == fields.cantidad_minima
        assert fields.precio_sincronizado == fields.precio_unitario

    def test_the_snapshot_is_never_left_unset(self) -> None:
        """A NULL snapshot on a row carrying an `ml_price_id` is what
        `diff_pxq_tiers` refuses permanently. Carrying the columns as fields
        rather than letting the caller re-derive them is what stops a caller
        from forgetting them."""
        fields = live_entry_to_tier_fields(self._entry())

        assert fields.cantidad_sincronizada is not None
        assert fields.precio_sincronizado is not None

    def test_pxq_diff_still_refuses_a_row_with_no_snapshot(self) -> None:
        """Pins the reason this helper populates the snapshot at all. If this
        refusal is ever removed, the justification above is stale and this
        test says so instead of leaving it to prose."""
        source = Path(pxq_diff.__file__).read_text(encoding="utf-8")

        assert "no snapshot to compare against" in source
        assert "if not desired.has_snapshot:" in source

    def test_the_result_is_frozen(self) -> None:
        fields = live_entry_to_tier_fields(self._entry())

        with pytest.raises(FrozenInstanceError):
            fields.precio_sincronizado = Decimal("1.00")

    def test_a_quantity_is_returned_as_an_int(self) -> None:
        """`cantidad_minima` is an integer column and the live payload is
        JSON, so a string quantity must not reach the row as a string."""
        fields = live_entry_to_tier_fields(self._entry(quantity="10"))

        assert fields.cantidad_minima == 10
        assert isinstance(fields.cantidad_minima, int)


class TestLiveEntryToTierFieldsRefusesMalformedEntries:
    """The documented contract: this module is PURE and has no outcome
    vocabulary, so it raises instead of inventing a status. It raises exactly
    the tuple the orchestrator catches —
    `(KeyError, TypeError, ValueError, ArithmeticError)`, the same tuple
    `_live_tiers_from_raw` catches.

    `ArithmeticError` is in that tuple for a hard-won reason:
    `decimal.InvalidOperation` is NOT a `ValueError`, and once escaped an
    except clause as a raw 500.
    """

    def test_a_missing_id_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            live_entry_to_tier_fields({"quantity": 10, "amount": "500.00"})

    def test_a_missing_quantity_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            live_entry_to_tier_fields({"id": "MLP-1", "amount": "500.00"})

    def test_a_missing_amount_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            live_entry_to_tier_fields({"id": "MLP-1", "quantity": 10})

    def test_a_junk_amount_raises_invalid_operation_which_is_an_arithmetic_error(self) -> None:
        """THE case `_live_tiers_from_raw` was already fixed for. Catching
        `ValueError` alone does not catch this, and the 500 it produced is why
        `ArithmeticError` is in the documented tuple."""
        with pytest.raises(InvalidOperation) as excinfo:
            live_entry_to_tier_fields({"id": "MLP-1", "quantity": 10, "amount": "not-a-number"})

        assert isinstance(excinfo.value, ArithmeticError)
        assert not isinstance(excinfo.value, ValueError)

    def test_a_none_amount_also_raises_an_arithmetic_error(self) -> None:
        with pytest.raises(ArithmeticError):
            live_entry_to_tier_fields({"id": "MLP-1", "quantity": 10, "amount": None})

    def test_a_junk_quantity_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            live_entry_to_tier_fields({"id": "MLP-1", "quantity": "many", "amount": "500.00"})

    def test_a_none_quantity_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            live_entry_to_tier_fields({"id": "MLP-1", "quantity": None, "amount": "500.00"})

    def test_every_documented_failure_is_inside_the_tuple_the_caller_catches(self) -> None:
        """The contract is the TUPLE, not the individual classes. If a new
        failure mode ever escapes it, the orchestrator answers with a 500
        instead of `adopt_read_unavailable`."""
        caught = (KeyError, TypeError, ValueError, ArithmeticError)
        malformed = [
            {"quantity": 10, "amount": "500.00"},
            {"id": "MLP-1", "amount": "500.00"},
            {"id": "MLP-1", "quantity": 10},
            {"id": "MLP-1", "quantity": 10, "amount": "not-a-number"},
            {"id": "MLP-1", "quantity": 10, "amount": None},
            {"id": "MLP-1", "quantity": "many", "amount": "500.00"},
            {"id": "MLP-1", "quantity": None, "amount": "500.00"},
        ]

        for entry in malformed:
            with pytest.raises(caught):
                live_entry_to_tier_fields(entry)

    def test_nothing_is_returned_on_a_malformed_entry(self) -> None:
        """It raises rather than returning a half-built `ImportedTierFields`
        with a defaulted snapshot — a partially mapped row is how a NULL
        snapshot would reach the DB in the first place."""
        with pytest.raises(KeyError):
            result = live_entry_to_tier_fields({"quantity": 10, "amount": "500.00"})
            assert not isinstance(result, ImportedTierFields)


class TestPxqConfirmModuleStaysPure:
    """`pxq_confirm` holds the rule the whole feature rests on and its module
    docstring promises "Pure: no DB session, no HTTP". Nothing enforced that
    promise until this test: the sibling guard in `test_pxq_diff.py` covers
    `pxq_diff` only, and `test_pxq_base_price_boundary.py` scans for
    `ProductoPricing`, not for impurity.

    `app` is deliberately NOT forbidden here, unlike in `pxq_diff`: this
    module already imports `app.models.ml_pxq_tier` and `app.services.pxq_diff`
    by design, and both of those are themselves pure. What must never appear
    is a framework, a session, a transport or a logger.
    """

    _FORBIDDEN_ROOTS = {"fastapi", "sqlalchemy", "logging", "requests", "httpx"}

    def _imported_roots(self, source: str) -> set:
        tree = ast.parse(source)

        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import: reaches into the app package
                    roots.add("app")
                elif node.module:
                    roots.add(node.module.split(".")[0])
        return roots

    def test_pxq_confirm_imports_nothing_impure(self) -> None:
        source = Path(pxq_confirm.__file__).read_text(encoding="utf-8")

        offenders = self._imported_roots(source) & self._FORBIDDEN_ROOTS

        assert offenders == set(), f"pxq_confirm must stay pure; forbidden imports found: {sorted(offenders)}"

    def test_the_scan_would_actually_catch_an_impure_import(self) -> None:
        """Keeps the guard above from going vacuously green if the AST walk
        ever stops seeing imports."""
        roots = self._imported_roots("import logging\nfrom sqlalchemy.orm import Session\n")

        assert roots & self._FORBIDDEN_ROOTS == {"logging", "sqlalchemy"}

    def test_pxq_confirm_never_touches_a_logger(self) -> None:
        """The orchestrator holds the full context and logs the outcomes; the
        pure modules stay logging-free by contract."""
        source = Path(pxq_confirm.__file__).read_text(encoding="utf-8")

        assert "getLogger" not in source
        assert "logger." not in source


class TestSnapshotWriterInvariantIsDocumentedTruthfully:
    """`remap_and_confirm` used to claim it was "the only place in the whole
    service allowed to advance" the snapshot. That claim is FALSE the moment
    `live_entry_to_tier_fields` exists, and a reviewer trusting the untouched
    text could authorise a third, ad-hoc snapshot writer.

    This repo has a measured track record of exactly that failure: three
    separate invariants were written in prose and never enforced, and the one
    that mattered most (`adopt-live`) went unimplemented for months while the
    document said it existed. So the corrected prose gets a test. An invariant
    with no test is not an invariant — it is a wish.
    """

    STALE_CLAIM = "only place in the whole service"

    def test_the_docstring_no_longer_makes_the_false_exclusivity_claim(self) -> None:
        assert self.STALE_CLAIM not in remap_and_confirm.__doc__

    def test_the_docstring_names_the_other_legitimate_snapshot_writer(self) -> None:
        assert "live_entry_to_tier_fields" in remap_and_confirm.__doc__

    def test_the_docstring_states_why_that_other_writer_is_legitimate(self) -> None:
        """Naming the function without its justification is how the next
        reader concludes "so anyone may write the snapshot"."""
        doc = remap_and_confirm.__doc__

        assert "live read" in doc
        assert "post-write confirmation" in doc.lower()

    def test_these_assertions_are_not_vacuous(self) -> None:
        """A stripped docstring (`python -OO`) turns `__doc__` into None, and a
        forgiving `(__doc__ or "")` would then make every assertion above pass
        against NO documentation at all. Pin the precondition explicitly.

        The positive assertions cannot be satisfied by an empty docstring, and
        this test proves the negative one cannot either.
        """
        assert remap_and_confirm.__doc__ is not None
        assert len(remap_and_confirm.__doc__) > 500
        assert self.STALE_CLAIM in (
            "This is the only place in the whole service allowed to advance "
            "`cantidad_sincronizada`/`precio_sincronizado`."
        ), "the stale phrase must still match the sentence it was written to detect"
