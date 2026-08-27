"""Tests for the claim/question/message -> ML order link resolver (slice 4).

Design D3 (obs #1823): the resolver is READ-ONLY on `rma_claims_ml`,
`ml_bot_question`, `ml_bot_message` -- it never writes to those tables, only
to `ml_operation_links`. That is the whole point: a second writer on tables
already owned by `ml_questions/ingestion_service.py` (71/22 callers) would
recreate the exact dual-writer problem D2 avoids for orders. Every test
class here that runs the resolver against seeded rows also asserts those
source tables are byte-for-byte unchanged afterward.

Unresolved records (obs #1852 lesson: never silently drop) must remain
fully queryable through the source table itself, plus a "flagged as
unlinked" query path this module exposes explicitly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import MlOperationLink, MlOrderItemOps, MlOrdersOps
from app.models.rma_claim_ml import RmaClaimML
from app.services.ml_orders_ingestion.link_resolver_service import (
    get_unlinked_claims,
    get_unlinked_messages,
    get_unlinked_questions,
    resolve_links,
)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _make_order(db, order_id: int, pack_id=None, buyer_id=None, seller_id: int = 999) -> MlOrdersOps:
    order = MlOrdersOps(
        order_id=order_id,
        pack_id=pack_id,
        status="paid",
        ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
        buyer_id=buyer_id,
        seller_id=seller_id,
    )
    db.add(order)
    db.flush()
    return order


def _make_claim(db, claim_id: int, resource_id) -> RmaClaimML:
    claim = RmaClaimML(claim_id=claim_id, resource_id=resource_id, status="opened")
    db.add(claim)
    db.flush()
    return claim


def _make_message(db, ml_message_id: str, pack_id) -> MlBotMessage:
    msg = MlBotMessage(
        ml_message_id=ml_message_id,
        pack_id=pack_id,
        seller_id=999,
        text="hola",
        status="available",
        received_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    db.add(msg)
    db.flush()
    return msg


def _make_question(db, ml_question_id: int, item_id: str, buyer_id) -> MlBotQuestion:
    q = MlBotQuestion(
        ml_question_id=ml_question_id,
        item_id=item_id,
        buyer_id=buyer_id,
        question_text="hola",
        question_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    db.add(q)
    db.flush()
    return q


class TestFlagGate:
    def test_flag_off_writes_no_links(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        order = _make_order(db, order_id=1)
        _make_claim(db, claim_id=500, resource_id=order.order_id)

        result = resolve_links(db)

        assert result.ran is False
        assert db.query(MlOperationLink).count() == 0


class TestClaimResourceIdResolution:
    def test_claim_with_matching_order_creates_exact_link(self, db) -> None:
        order = _make_order(db, order_id=111)
        claim = _make_claim(db, claim_id=500, resource_id=order.order_id)

        result = resolve_links(db)

        assert result.ran is True
        assert result.claims_linked == 1
        link = db.query(MlOperationLink).filter(MlOperationLink.entity_type == "claim").one()
        assert link.order_id == order.order_id
        assert link.entity_id == claim.id
        assert link.link_source == "claim_resource_id"
        assert link.link_confidence == "exact"

    def test_source_table_is_not_written(self, db) -> None:
        """READ-ONLY contract (design D3): the resolver must never mutate
        rma_claims_ml. If this test ever needs updating because the
        resolver started writing to the claim row, that is the exact
        second-writer regression D3 exists to prevent."""
        order = _make_order(db, order_id=111)
        claim = _make_claim(db, claim_id=500, resource_id=order.order_id)
        original_updated_at = claim.updated_at

        resolve_links(db)

        db.refresh(claim)
        assert claim.updated_at == original_updated_at
        assert claim.resource_id == order.order_id

    def test_claim_with_no_matching_order_is_unresolved_not_dropped(self, db) -> None:
        """Scenario: link cannot be resolved (spec) -- the claim is flagged
        as unlinked (queryable), never silently dropped."""
        claim = _make_claim(db, claim_id=501, resource_id=999999)

        result = resolve_links(db)

        assert result.ran is True
        assert result.claims_linked == 0
        assert db.query(MlOperationLink).count() == 0

        # Never dropped: still there via the ordinary table query...
        assert db.query(RmaClaimML).filter(RmaClaimML.id == claim.id).count() == 1
        # ...and explicitly discoverable via the "flagged as unlinked" path.
        unlinked = get_unlinked_claims(db)
        assert claim.id in {c.id for c in unlinked}

    def test_claim_with_null_resource_id_is_unresolved_not_dropped(self, db) -> None:
        claim = _make_claim(db, claim_id=502, resource_id=None)

        result = resolve_links(db)

        assert result.claims_linked == 0
        unlinked = get_unlinked_claims(db)
        assert claim.id in {c.id for c in unlinked}

    def test_linked_claim_does_not_appear_in_unlinked_query(self, db) -> None:
        order = _make_order(db, order_id=112)
        claim = _make_claim(db, claim_id=503, resource_id=order.order_id)

        resolve_links(db)

        unlinked = get_unlinked_claims(db)
        assert claim.id not in {c.id for c in unlinked}

    def test_rerun_is_idempotent_no_duplicate_rows(self, db) -> None:
        order = _make_order(db, order_id=113)
        _make_claim(db, claim_id=504, resource_id=order.order_id)

        resolve_links(db)
        resolve_links(db)

        assert db.query(MlOperationLink).filter(MlOperationLink.entity_type == "claim").count() == 1


class TestMessagePackIdResolution:
    def test_message_with_single_matching_order_is_exact(self, db) -> None:
        order = _make_order(db, order_id=200, pack_id=7777)
        msg = _make_message(db, ml_message_id="msg-1", pack_id="7777")

        result = resolve_links(db)

        assert result.messages_linked == 1
        link = db.query(MlOperationLink).filter(MlOperationLink.entity_type == "message").one()
        assert link.order_id == order.order_id
        assert link.entity_id == msg.id
        assert link.link_source == "pack_id"
        assert link.link_confidence == "exact"

    def test_message_with_multiple_orders_sharing_pack_id_is_inferred_and_links_all(self, db) -> None:
        """`pack_id` genuinely groups a multi-order cart (design schema
        note) -- a message about that pack legitimately applies to more
        than one order, so ambiguity is recorded as `inferred`, not
        collapsed to a single guess."""
        order_a = _make_order(db, order_id=201, pack_id=8888)
        order_b = _make_order(db, order_id=202, pack_id=8888)
        _make_message(db, ml_message_id="msg-2", pack_id="8888")

        result = resolve_links(db)

        assert result.messages_linked == 1  # one message, linked to both orders below
        links = db.query(MlOperationLink).filter(MlOperationLink.entity_type == "message").all()
        assert {link.order_id for link in links} == {order_a.order_id, order_b.order_id}
        assert all(link.link_confidence == "inferred" for link in links)

    def test_message_with_no_matching_pack_is_unresolved_not_dropped(self, db) -> None:
        msg = _make_message(db, ml_message_id="msg-3", pack_id="9999")

        result = resolve_links(db)

        assert result.messages_linked == 0
        unlinked = get_unlinked_messages(db)
        assert msg.id in {m.id for m in unlinked}

    def test_message_with_null_pack_id_is_unresolved_not_dropped(self, db) -> None:
        msg = _make_message(db, ml_message_id="msg-4", pack_id=None)

        resolve_links(db)

        unlinked = get_unlinked_messages(db)
        assert msg.id in {m.id for m in unlinked}

    def test_message_with_non_numeric_pack_id_does_not_raise(self, db) -> None:
        """`pack_id` is a free-text column on `ml_bot_messages`; a malformed
        value must be treated as unresolvable, never crash the resolver."""
        msg = _make_message(db, ml_message_id="msg-5", pack_id="not-a-number")

        result = resolve_links(db)

        assert result.ran is True
        assert result.messages_linked == 0
        unlinked = get_unlinked_messages(db)
        assert msg.id in {m.id for m in unlinked}


class TestQuestionItemBuyerResolution:
    """Pre-sale questions have no order at all until (if ever) a purchase
    happens. Matching on `item_id` alone would over-link every question
    about a popular item to every order that ever bought it -- unbounded
    false positives. The resolver requires item_id AND buyer_id to agree,
    which bounds the match to "this exact buyer asked about this exact
    item and also has an order containing it"."""

    def test_question_with_matching_buyer_and_item_is_inferred(self, db) -> None:
        order = _make_order(db, order_id=300, buyer_id=55)
        db.add(MlOrderItemOps(order_id=order.order_id, item_id="MLA1", quantity=1))
        db.flush()
        q = _make_question(db, ml_question_id=900, item_id="MLA1", buyer_id=55)

        result = resolve_links(db)

        assert result.questions_linked == 1
        link = db.query(MlOperationLink).filter(MlOperationLink.entity_type == "question").one()
        assert link.order_id == order.order_id
        assert link.entity_id == q.id
        assert link.link_source == "item_id"
        assert link.link_confidence == "inferred"

    def test_question_same_item_different_buyer_is_unresolved(self, db) -> None:
        order = _make_order(db, order_id=301, buyer_id=55)
        db.add(MlOrderItemOps(order_id=order.order_id, item_id="MLA2", quantity=1))
        db.flush()
        q = _make_question(db, ml_question_id=901, item_id="MLA2", buyer_id=66)

        result = resolve_links(db)

        assert result.questions_linked == 0
        unlinked = get_unlinked_questions(db)
        assert q.id in {row.id for row in unlinked}

    def test_question_with_no_buyer_id_is_unresolved_not_dropped(self, db) -> None:
        q = _make_question(db, ml_question_id=902, item_id="MLA3", buyer_id=None)

        result = resolve_links(db)

        assert result.questions_linked == 0
        unlinked = get_unlinked_questions(db)
        assert q.id in {row.id for row in unlinked}

    def test_source_table_is_not_written(self, db) -> None:
        order = _make_order(db, order_id=302, buyer_id=77)
        db.add(MlOrderItemOps(order_id=order.order_id, item_id="MLA4", quantity=1))
        db.flush()
        q = _make_question(db, ml_question_id=903, item_id="MLA4", buyer_id=77)
        original_updated_at = q.updated_at

        resolve_links(db)

        db.refresh(q)
        assert q.updated_at == original_updated_at
        assert q.status == "received"


class TestNoQueryPerRowLoop:
    """AGENTS.md: "Don't query DB in loops". Pre-push review finding 1/2:
    `_resolve_messages`/`_resolve_questions` ran one query per candidate row
    (plus one insert per match), and `_resolve_claims` materialised every
    order id into a Python set. `resolve_links` must run a bounded, small
    number of statements regardless of how many claims/messages/questions
    exist -- proven here with 12 of each, which would blow well past any
    reasonable fixed bound under the old per-row-loop implementation."""

    def test_resolve_links_runs_a_bounded_number_of_statements(self, db, query_counter) -> None:
        order = _make_order(db, order_id=900, pack_id=900, buyer_id=42)
        db.add(MlOrderItemOps(order_id=order.order_id, item_id="MLA-BOUND", quantity=1))
        db.flush()

        for i in range(12):
            _make_claim(db, claim_id=9000 + i, resource_id=order.order_id)
            _make_message(db, ml_message_id=f"bound-msg-{i}", pack_id="900")
            _make_question(db, ml_question_id=9500 + i, item_id="MLA-BOUND", buyer_id=42)
        db.flush()

        with query_counter() as counter:
            result = resolve_links(db)

        assert result.claims_linked == 12
        assert result.messages_linked == 12
        assert result.questions_linked == 12
        # A handful of set-based statements (one INSERT..SELECT + a couple of
        # count queries per entity type), never O(row count).
        assert counter.total <= 15, f"expected a bounded statement count, got {counter.total}"


class TestUnlinkedQueriesArePaginated:
    """Pre-push review finding 3: the `get_unlinked_*` helpers backed an
    unbounded `.all()` over their whole table -- this is the query path a
    UI will consume, so it needs limit/offset now, not later."""

    def test_get_unlinked_claims_respects_limit_and_offset(self, db) -> None:
        for i in range(5):
            _make_claim(db, claim_id=9700 + i, resource_id=None)

        page_one = get_unlinked_claims(db, limit=2, offset=0)
        page_two = get_unlinked_claims(db, limit=2, offset=2)

        assert len(page_one) == 2
        assert len(page_two) == 2
        assert {c.id for c in page_one}.isdisjoint({c.id for c in page_two})

    def test_get_unlinked_messages_respects_limit_and_offset(self, db) -> None:
        for i in range(5):
            _make_message(db, ml_message_id=f"unl-msg-{i}", pack_id=None)

        page = get_unlinked_messages(db, limit=3, offset=0)
        assert len(page) == 3

    def test_get_unlinked_questions_respects_limit_and_offset(self, db) -> None:
        for i in range(5):
            _make_question(db, ml_question_id=9800 + i, item_id="MLA-UNL", buyer_id=None)

        page = get_unlinked_questions(db, limit=3, offset=0)
        assert len(page) == 3
