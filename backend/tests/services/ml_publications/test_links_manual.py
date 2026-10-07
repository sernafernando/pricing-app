"""Manual link operations against a real Postgres (P5L2.T2, design D20, spec Domain 6).

Items are real captures stored through `apply_fetch` (links off, so no link row exists until an
operation or the sweep evaluates it). `productos_erp` and `auditoria` rows are plain test data.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core import database
from app.models.auditoria import TipoAccion
from app.services.ml_publications import links
from tests.services.ml_publications.conftest import item_with_variations, sample_item
from tests.services.ml_publications.test_links_store import (
    ITEM,
    SKU_A,
    SKU_B,
    _with_sku,
    add_product,
    at,
    event_rows,
    link,
    link_rows,
    log_rows,
    put_link,
)
from tests.services.ml_publications.test_store_apply_fetch import apply

pytestmark = pytest.mark.postgres

USER = 17

AUDIT_DDL = """
CREATE TABLE auditoria (
    id serial PRIMARY KEY,
    item_id integer,
    usuario_id integer NOT NULL,
    tipo_accion varchar(50) NOT NULL,
    valores_anteriores json,
    valores_nuevos json,
    es_masivo integer,
    productos_afectados integer,
    comentario varchar(500),
    fecha timestamp NOT NULL
)
"""


@pytest.fixture()
def audited(events_on):
    """The link tables, events on and a plain `auditoria` table (no FK to users: only the audit columns matter)."""
    with events_on.begin() as conn:
        conn.execute(text(AUDIT_DDL))
    return events_on


def audit_rows(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM auditoria ORDER BY id")).mappings().all()


def store(engine, body: dict, item_id: str = ITEM, minutes: float = 0) -> None:
    apply(body, item_id, minutes=minutes)


def run(operation, *args, minutes: float = 10, events: bool = True, **kwargs):
    """One operation in its own transaction, committed like the router does."""
    with database.get_background_db() as db:
        return operation(db, *args, now=at(minutes), events_enabled=events, **kwargs)


def manual(product, note=None, *, variation_id=0, item_id=ITEM, **kwargs):
    return run(links.set_manual, item_id, variation_id, product, note, USER, **kwargs)


class TestSetManual:
    def test_fixing_a_wrong_automatic_link_writes_link_history_event_and_audit_together(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        run(links.evaluate_for_item, ITEM, minutes=1)  # the automatic link to 41, first sighting

        outcome = manual(42, "wrong product, checked by hand")

        assert outcome.changed is True
        row = link(audited)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("manual", "linked", 42)
        assert (row["linked_by"], row["linked_at"], row["note"]) == (USER, at(10), "wrong product, checked by hand")
        # the automatic suggestion keeps pointing at the SKU's product while the manual link stands
        assert (row["suggested_producto_item_id"], row["suggestion_status"]) == (41, "linked")
        (entry,) = log_rows(audited)
        assert (entry["entity_id"], entry["item_id"], entry["observed_at"]) == (f"{ITEM}:0", ITEM, at(10))
        assert entry["changed_paths"] == ["producto_item_id", "source"]
        assert entry["context"]["producto_item_id_old"] == 41 and entry["context"]["producto_item_id_new"] == 42
        assert (entry["context"]["source_old"], entry["context"]["source_new"]) == ("sku_auto", "manual")
        assert entry["context"]["linked_by"] == USER
        (event,) = event_rows(audited)
        assert (event["event_type"], event["old_value"], event["new_value"]) == ("product_link_changed", 41, 42)
        assert event["change_log_id"] == entry["id"]
        (audit,) = audit_rows(audited)
        assert (audit["tipo_accion"], audit["item_id"], audit["usuario_id"]) == ("ML_VINCULO_MANUAL", 42, USER)
        assert audit["comentario"] == "wrong product, checked by hand"
        assert audit["valores_nuevos"] == {
            "mla": ITEM,
            "variation_id": 0,
            "producto_item_id": 42,
            "source": "manual",
            "match_status": "linked",
        }
        assert audit["valores_anteriores"]["producto_item_id"] == 41
        assert audit["valores_anteriores"]["source"] == "sku_auto"

    def test_a_unit_that_was_never_evaluated_is_created_as_manual_with_its_suggestion(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        assert link_rows(audited) == []

        manual(42)

        row = link(audited)
        assert (row["source"], row["producto_item_id"], row["suggested_producto_item_id"]) == ("manual", 42, 41)
        assert row["evaluated_sku_key"] == SKU_A and row["evaluated_at"] == at(10)

    def test_a_variation_unit_is_addressed_by_its_variation_id(self, audited) -> None:
        body = item_with_variations()
        add_product(audited, 7, "OTHER")
        store(audited, body, body["id"])

        manual(7, item_id=body["id"], variation_id=175550253196)

        rows = {r["variation_id"]: r["source"] for r in link_rows(audited)}
        assert rows == {
            175550253195: "sku_auto",
            175550253196: "manual",
            175550253197: "sku_auto",
            175550253198: "sku_auto",
        }

    def test_a_missing_product_is_refused_and_nothing_is_written(self, audited) -> None:
        store(audited, sample_item(ITEM))

        with pytest.raises(links.ProductNotFound):
            manual(999)

        assert link_rows(audited) == [] and log_rows(audited) == [] and audit_rows(audited) == []

    def test_an_unknown_item_is_refused_and_nothing_is_written(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        with pytest.raises(links.UnknownItem):
            manual(41, item_id="MLA1")
        assert link_rows(audited) == [] and audit_rows(audited) == []

    def test_the_chosen_product_cannot_be_deleted_until_the_link_commits(self, audited) -> None:
        """The existence check holds a share lock: a catalog sync deleting the product waits for the link
        transaction instead of leaving a dangling link behind."""
        from sqlalchemy.exc import OperationalError

        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))

        with database.get_background_db() as db:
            links.set_manual(db, ITEM, 0, 42, None, USER, now=at(10), events_enabled=False)
            db.flush()  # the link transaction is open, not committed
            with audited.connect() as other:
                other.execute(text("SET lock_timeout = '300ms'"))
                with pytest.raises(OperationalError, match="lock timeout|LockNotAvailable"):
                    other.execute(text("DELETE FROM productos_erp WHERE item_id = 42"))
        with audited.begin() as conn:  # committed: the delete goes through (the link is then dangling, reported)
            conn.execute(text("DELETE FROM productos_erp WHERE item_id = 42"))

    def test_a_variation_that_is_not_part_of_the_item_is_refused(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        store(audited, sample_item(ITEM))
        with pytest.raises(links.UnknownUnit):
            manual(41, variation_id=123)  # the item has no variations: its only unit is variation 0
        assert link_rows(audited) == [] and audit_rows(audited) == []

    def test_setting_the_same_link_twice_writes_nothing_the_second_time(self, audited) -> None:
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        manual(42, "n", minutes=10)
        before = (link(audited), log_rows(audited), event_rows(audited), audit_rows(audited))

        outcome = manual(42, "n", minutes=20)

        assert outcome.changed is False
        assert (link(audited), log_rows(audited), event_rows(audited), audit_rows(audited)) == before

    def test_a_no_change_request_may_still_refresh_the_suggestion_but_writes_no_decision(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        manual(42, "n", minutes=10)
        store(audited, _with_sku("NOT-IN-THE-CATALOG"), minutes=5)  # the SKU moved since the manual decision
        audits, logs = len(audit_rows(audited)), len(log_rows(audited))

        outcome = manual(42, "n", minutes=20)

        assert outcome.changed is False
        row = link(audited)
        assert (row["suggestion_status"], row["evaluated_sku_key"]) == ("unmatched", "NOT-IN-THE-CATALOG")
        assert (row["source"], row["producto_item_id"], row["linked_at"]) == ("manual", 42, at(10))
        assert (len(audit_rows(audited)), len(log_rows(audited))) == (audits, logs)

    def test_a_new_note_on_the_same_link_updates_the_note_with_an_audit_row_but_no_history(self, audited) -> None:
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        manual(42, "first", minutes=10)

        outcome = manual(42, "second", minutes=20)

        assert outcome.changed is False  # the link itself did not move
        assert link(audited)["note"] == "second" and link(audited)["linked_at"] == at(20)
        assert len(log_rows(audited)) == 1 and len(event_rows(audited)) == 1
        assert [a["tipo_accion"] for a in audit_rows(audited)] == ["ML_VINCULO_MANUAL"] * 2

    def test_without_the_events_flag_the_history_and_audit_are_written_but_no_event(self, audited) -> None:
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))

        manual(42, events=False)

        assert len(log_rows(audited)) == 1 and event_rows(audited) == [] and len(audit_rows(audited)) == 1

    def test_a_failure_writing_the_audit_row_rolls_back_the_whole_operation(self, audited, monkeypatch) -> None:
        add_product(audited, 41, SKU_A)
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        run(links.evaluate_for_item, ITEM, minutes=1)
        before = link(audited)

        def boom(*args, **kwargs):
            raise RuntimeError("audit insert failed")

        monkeypatch.setattr(links, "_record_audit", boom)
        with pytest.raises(RuntimeError):
            manual(42)

        assert link(audited) == before
        assert log_rows(audited) == [] and event_rows(audited) == []

    def test_the_audit_enum_values_exist_and_fit_the_varchar_column(self) -> None:
        for name in ("ML_VINCULO_MANUAL", "ML_VINCULO_SIN_PRODUCTO", "ML_VINCULO_AUTOMATICO"):
            assert len(TipoAccion[name].value) <= 50


class TestSetManualNone:
    def test_marks_the_unit_as_explicitly_without_a_product(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        store(audited, sample_item(ITEM))
        run(links.evaluate_for_item, ITEM, minutes=1)

        outcome = run(links.set_manual_none, ITEM, 0, "bundle, no single product", USER)

        assert outcome.changed is True
        row = link(audited)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("manual_none", "no_product", None)
        assert (row["linked_by"], row["note"]) == (USER, "bundle, no single product")
        assert (row["suggestion_status"], row["suggested_producto_item_id"]) == ("linked", 41)
        (entry,) = log_rows(audited)
        assert entry["context"]["match_status_new"] == "no_product"
        (event,) = event_rows(audited)
        assert (event["old_value"], event["new_value"]) == (41, None)
        (audit,) = audit_rows(audited)
        assert (audit["tipo_accion"], audit["item_id"]) == ("ML_VINCULO_SIN_PRODUCTO", None)

    def test_marking_the_same_unit_twice_writes_nothing_the_second_time(self, audited) -> None:
        store(audited, sample_item(ITEM))
        run(links.set_manual_none, ITEM, 0, None, USER)
        before = (link(audited), log_rows(audited), audit_rows(audited))

        assert run(links.set_manual_none, ITEM, 0, None, USER, minutes=20).changed is False

        assert (link(audited), log_rows(audited), audit_rows(audited)) == before

    def test_a_manual_none_survives_the_automatic_rule_and_shows_as_differing(self, audited) -> None:
        store(audited, sample_item(ITEM))
        run(links.set_manual_none, ITEM, 0, None, USER)
        add_product(audited, 41, SKU_A)

        with database.get_background_db() as db:
            links.evaluate_item(db, ITEM, _typed(), _variations(), now=at(30), events_enabled=True, force=True)

        row = link(audited)
        assert (row["source"], row["match_status"]) == ("manual_none", "no_product")
        assert (row["suggestion_status"], row["suggested_producto_item_id"]) == ("linked", 41)


def _typed() -> dict:
    from app.services.ml_publications.mappers import map_item

    return map_item(sample_item(ITEM))


def _variations() -> list:
    from app.services.ml_publications.mappers import map_variations

    return map_variations(sample_item(ITEM))


class TestRevertToAuto:
    def test_takes_the_current_suggestion_immediately_and_is_logged_and_audited(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        manual(42, "temporary", minutes=10)

        outcome = run(links.revert_to_auto, ITEM, 0, USER, minutes=20)

        assert outcome.changed is True
        row = link(audited)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "linked", 41)
        assert (row["linked_by"], row["linked_at"]) == (None, at(20))
        assert (row["matched_sku"], row["sku_field"]) == (SKU_A, "seller_sku_attr")
        last = max(log_rows(audited), key=lambda entry: entry["id"])
        assert (last["context"]["source_old"], last["context"]["source_new"]) == ("manual", "sku_auto")
        assert last["context"]["linked_by"] == USER  # who reverted it, even though the link has no author
        assert [a["tipo_accion"] for a in audit_rows(audited)] == ["ML_VINCULO_MANUAL", "ML_VINCULO_AUTOMATICO"]
        assert event_rows(audited)[-1]["new_value"] == 41

    def test_resolves_with_the_catalog_as_it_is_now_not_the_stale_suggestion(self, audited) -> None:
        store(audited, sample_item(ITEM))
        run(links.set_manual_none, ITEM, 0, None, USER, minutes=10)  # suggestion at this point: unmatched
        add_product(audited, 41, SKU_A)  # catalog change the sweep has not seen yet

        run(links.revert_to_auto, ITEM, 0, USER, minutes=20)

        row = link(audited)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "linked", 41)

    def test_a_unit_without_a_matching_product_reverts_to_unmatched(self, audited) -> None:
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        manual(42)

        run(links.revert_to_auto, ITEM, 0, USER, minutes=20)

        row = link(audited)
        assert (row["source"], row["match_status"], row["producto_item_id"]) == ("sku_auto", "unmatched", None)
        assert row["matched_sku"] == SKU_A

    def test_the_catalog_sku_change_is_applied_on_revert(self, audited) -> None:
        add_product(audited, 42, SKU_B)
        store(audited, sample_item(ITEM))
        manual(42)
        store(audited, _with_sku(SKU_B), minutes=5)  # the item's SKU now points at product 42 as well

        run(links.revert_to_auto, ITEM, 0, USER, minutes=20)

        assert (link(audited)["producto_item_id"], link(audited)["matched_sku"]) == (42, SKU_B)

    def test_an_already_automatic_unit_is_a_noop_when_nothing_changed(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        store(audited, sample_item(ITEM))
        run(links.evaluate_for_item, ITEM, minutes=1)
        before = (link(audited), log_rows(audited), audit_rows(audited))

        outcome = run(links.revert_to_auto, ITEM, 0, USER, minutes=20)

        assert outcome.changed is False
        assert (link(audited), log_rows(audited), audit_rows(audited)) == before

    def test_an_unknown_item_is_refused(self, audited) -> None:
        with pytest.raises(links.UnknownItem):
            run(links.revert_to_auto, "MLA1", 0, USER)


class TestAutomaticRuleStillLeavesManualAlone:
    def test_the_sweep_style_forced_evaluation_never_moves_a_manual_link(self, audited) -> None:
        add_product(audited, 41, SKU_A)
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        manual(42)

        with database.get_background_db() as db:
            links.evaluate_item(db, ITEM, _typed(), _variations(), now=at(30), events_enabled=True, force=True)

        row = link(audited)
        assert (row["source"], row["producto_item_id"], row["suggested_producto_item_id"]) == ("manual", 42, 41)
        assert len(log_rows(audited)) == 1  # only the manual change

    def test_a_row_written_by_an_earlier_evaluation_can_be_changed_by_hand(self, audited) -> None:
        """A link row that already exists (stored earlier, up to date) is locked and changed like any other."""
        add_product(audited, 41, SKU_A)
        add_product(audited, 42, "OTHER")
        store(audited, sample_item(ITEM))
        put_link(audited, ITEM, 0, "sku_auto", "linked", 41, evaluated_sku_key=SKU_A, evaluated_at=at(1))

        manual(42)

        assert link(audited)["producto_item_id"] == 42
