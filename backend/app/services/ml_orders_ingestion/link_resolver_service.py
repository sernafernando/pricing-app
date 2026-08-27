"""Claim/question/message -> ML order link resolver (slice 4 of
ml-ventas-fuente-de-verdad).

Design D3 (obs #1823): this module is READ-ONLY on `rma_claims_ml`,
`ml_bot_question`, and `ml_bot_message`. It reads those existing tables and
writes ONLY `ml_operation_links`. Populating a column on those tables would
make this resolver a second writer on tables already owned by
`ml_questions/ingestion_service.py` (71 `MlBotConfig` callers / 22
`MlBotQuestion` callers) and `seriales_claims.py` -- exactly the dual-writer
problem D2 avoids for the order tables themselves. Never add an ORM write
(`db.add`/`db.delete`/attribute assignment followed by flush) against
`RmaClaimML`, `MlBotQuestion`, or `MlBotMessage` in this module.

Resolution rules (each entity type resolves independently; an entity with
no match is simply not linked -- never dropped, still fully queryable
through its own table, and additionally discoverable through the
`get_unlinked_*` helpers below):

- claim -> exact match on `rma_claims_ml.resource_id == ml_orders_ops.order_id`.
  `resource_id` already IS the ML order id (model docstring), so this is a
  direct key lookup, `link_source='claim_resource_id'`, `link_confidence='exact'`.
- message -> `ml_bot_messages.pack_id` (free-text string) parsed to int and
  matched against `ml_orders_ops.pack_id`. `pack_id` genuinely groups a
  multi-order cart (schema note on `ml_orders_ops.pack_id`), so more than
  one order can legitimately match: exactly one match is `exact`, more than
  one is `inferred` and links to ALL of them (a message about the pack
  applies to every order in it, we just cannot tell which one specifically
  without more information).
- question -> `ml_bot_questions.item_id` AND `.buyer_id` must BOTH match an
  order's item/buyer. `item_id` alone is unbounded (every order that ever
  sold that item would match a pre-sale question about it, most of them
  unrelated); requiring the same buyer to also have an order containing
  that item bounds the match to a defensible heuristic. Always
  `link_source='item_id'`, `link_confidence='inferred'` (a question is
  fundamentally uncertain: asking about an item is not the same act as
  buying it).

Idempotent: writes use `INSERT ... ON CONFLICT DO NOTHING` keyed on the
`(entity_type, entity_id, order_id)` unique constraint, so a re-run never
duplicates a link already recorded (same convention as
`ingestion_service.py`'s `ON CONFLICT` upsert).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import MlOperationLink, MlOrderItemOps, MlOrdersOps
from app.models.rma_claim_ml import RmaClaimML


@dataclass
class LinkResolutionResult:
    ran: bool
    claims_linked: int = 0
    claims_unresolved: int = 0
    messages_linked: int = 0
    messages_unresolved: int = 0
    questions_linked: int = 0
    questions_unresolved: int = 0


def _insert_stmt(db: Session):
    """Same dialect-appropriate `INSERT ... ON CONFLICT` selection as
    `ingestion_service._insert_stmt` -- both PostgreSQL (production) and
    SQLite (`tests/conftest.py`'s in-memory test DB) support
    `on_conflict_do_nothing` with the same call shape."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(MlOperationLink.__table__)
    return postgresql.insert(MlOperationLink.__table__)


def _write_link(
    db: Session, order_id: int, entity_type: str, entity_id: int, link_source: str, link_confidence: str
) -> None:
    stmt = _insert_stmt(db).values(
        order_id=order_id,
        entity_type=entity_type,
        entity_id=entity_id,
        link_source=link_source,
        link_confidence=link_confidence,
    )
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["entity_type", "entity_id", "order_id"],
    )
    db.execute(stmt)


def _resolve_claims(db: Session) -> tuple[int, int]:
    linked = 0
    unresolved = 0
    order_ids = {row[0] for row in db.query(MlOrdersOps.order_id).all()}

    claims = db.query(RmaClaimML).filter(RmaClaimML.resource_id.isnot(None)).all()
    for claim in claims:
        if claim.resource_id in order_ids:
            _write_link(
                db,
                order_id=claim.resource_id,
                entity_type="claim",
                entity_id=claim.id,
                link_source="claim_resource_id",
                link_confidence="exact",
            )
            linked += 1
        else:
            unresolved += 1
    return linked, unresolved


def _resolve_messages(db: Session) -> tuple[int, int]:
    linked = 0
    unresolved = 0

    messages = db.query(MlBotMessage).filter(MlBotMessage.pack_id.isnot(None)).all()
    for msg in messages:
        try:
            pack_id_int = int(msg.pack_id)
        except (TypeError, ValueError):
            unresolved += 1
            continue

        matching_order_ids = [
            row[0] for row in db.query(MlOrdersOps.order_id).filter(MlOrdersOps.pack_id == pack_id_int).all()
        ]
        if not matching_order_ids:
            unresolved += 1
            continue

        confidence = "exact" if len(matching_order_ids) == 1 else "inferred"
        for order_id in matching_order_ids:
            _write_link(
                db,
                order_id=order_id,
                entity_type="message",
                entity_id=msg.id,
                link_source="pack_id",
                link_confidence=confidence,
            )
        linked += 1
    return linked, unresolved


def _resolve_questions(db: Session) -> tuple[int, int]:
    linked = 0
    unresolved = 0

    questions = db.query(MlBotQuestion).filter(MlBotQuestion.buyer_id.isnot(None)).all()
    for q in questions:
        matching_order_ids = [
            row[0]
            for row in db.query(MlOrdersOps.order_id)
            .join(MlOrderItemOps, MlOrderItemOps.order_id == MlOrdersOps.order_id)
            .filter(MlOrderItemOps.item_id == q.item_id, MlOrdersOps.buyer_id == q.buyer_id)
            .all()
        ]
        if not matching_order_ids:
            unresolved += 1
            continue

        for order_id in matching_order_ids:
            _write_link(
                db,
                order_id=order_id,
                entity_type="question",
                entity_id=q.id,
                link_source="item_id",
                link_confidence="inferred",
            )
        linked += 1
    return linked, unresolved


def resolve_links(db: Session) -> LinkResolutionResult:
    """Reads claims/questions/messages (READ-ONLY, see module docstring)
    and writes resolvable links into `ml_operation_links`. Never raises for
    an unresolvable entity -- an unresolved entity is simply not linked."""
    if not settings.ML_ORDERS_OPS_ENABLED:
        return LinkResolutionResult(ran=False)

    claims_linked, claims_unresolved = _resolve_claims(db)
    messages_linked, messages_unresolved = _resolve_messages(db)
    questions_linked, questions_unresolved = _resolve_questions(db)
    db.flush()

    return LinkResolutionResult(
        ran=True,
        claims_linked=claims_linked,
        claims_unresolved=claims_unresolved,
        messages_linked=messages_linked,
        messages_unresolved=messages_unresolved,
        questions_linked=questions_linked,
        questions_unresolved=questions_unresolved,
    )


def get_unlinked_claims(db: Session) -> List[RmaClaimML]:
    """Claims with no row in `ml_operation_links` -- the "flagged as
    unlinked" query path (spec: unresolved links MUST be recorded/queryable,
    never silently dropped)."""
    linked_ids = db.query(MlOperationLink.entity_id).filter(MlOperationLink.entity_type == "claim")
    return db.query(RmaClaimML).filter(~RmaClaimML.id.in_(linked_ids)).all()


def get_unlinked_messages(db: Session) -> List[MlBotMessage]:
    linked_ids = db.query(MlOperationLink.entity_id).filter(MlOperationLink.entity_type == "message")
    return db.query(MlBotMessage).filter(~MlBotMessage.id.in_(linked_ids)).all()


def get_unlinked_questions(db: Session) -> List[MlBotQuestion]:
    linked_ids = db.query(MlOperationLink.entity_id).filter(MlOperationLink.entity_type == "question")
    return db.query(MlBotQuestion).filter(~MlBotQuestion.id.in_(linked_ids)).all()
