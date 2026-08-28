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

Set-based, not per-row (pre-push review finding 1/2, AGENTS.md "Don't query
DB in loops"): every resolution is one `INSERT ... SELECT` statement plus a
couple of small aggregate queries to report counts, regardless of how many
claims/questions/messages exist. No row is ever loaded into Python to be
inspected or matched -- the match itself is a JOIN, and `_resolve_claims`
no longer materialises `ml_orders_ops.order_id` into a Python set (it used
to; that was one of the findings this rewrite fixes).

Resolution rules (each entity type resolves independently; an entity with
no match is simply not linked -- never dropped, still fully queryable
through its own table, and additionally discoverable through the
`get_unlinked_*` helpers below):

- claim -> exact match on `rma_claims_ml.resource_id == ml_orders_ops.order_id`.
  `resource_id` already IS the ML order id (model docstring), so this is a
  direct key JOIN, `link_source='claim_resource_id'`, `link_confidence='exact'`.
- message -> `ml_bot_messages.pack_id` (free-text string) matched against
  `ml_orders_ops.pack_id` (BigInteger) by casting the ORDER side to text
  (`CAST(order.pack_id AS TEXT) = message.pack_id`) rather than parsing the
  message side to int in Python -- this is what makes the match a plain SQL
  JOIN condition (portable across PostgreSQL/SQLite) instead of a per-row
  Python `int()` that could raise on a malformed value. `pack_id` genuinely
  groups a multi-order cart (schema note on `ml_orders_ops.pack_id`), so
  more than one order can legitimately match: exactly one match is `exact`,
  more than one is `inferred` and links to ALL of them (a message about the
  pack applies to every order in it, we just cannot tell which one
  specifically without more information) -- computed with a window
  `COUNT(*) OVER (PARTITION BY message.id)` in the same SELECT.
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

from sqlalchemy import String, case, cast, func, literal, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import MlOperationLink, MlOrderItemOps, MlOrdersOps
from app.models.rma_claim_ml import RmaClaimML

_LINK_COLUMNS = ["order_id", "entity_type", "entity_id", "link_source", "link_confidence"]

DEFAULT_UNLINKED_LIMIT = 50


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
    `on_conflict_do_nothing`/`from_select` with the same call shape."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(MlOperationLink.__table__)
    return postgresql.insert(MlOperationLink.__table__)


def _run_insert_select(db: Session, select_stmt, refresh_confidence: bool = False) -> None:
    """`refresh_confidence` re-applies `link_confidence` on an existing
    row. DO NOTHING is right when a link is immutable, which is true for
    claims and questions but NOT for messages: packs fill in over time, so
    a message linked as `exact` while only one order of its pack existed
    is lying once a second one arrives, and the old row would never be
    revisited."""
    stmt = _insert_stmt(db).from_select(_LINK_COLUMNS, select_stmt)
    conflict_cols = ["entity_type", "entity_id", "order_id"]
    if refresh_confidence:
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols,
            set_={"link_confidence": stmt.excluded.link_confidence},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
    db.execute(stmt)


def _resolve_claims(db: Session) -> tuple[int, int]:
    match = (
        select(
            RmaClaimML.resource_id.label("order_id"),
            literal("claim").label("entity_type"),
            RmaClaimML.id.label("entity_id"),
            literal("claim_resource_id").label("link_source"),
            literal("exact").label("link_confidence"),
        )
        .select_from(RmaClaimML)
        .join(MlOrdersOps, MlOrdersOps.order_id == RmaClaimML.resource_id)
        .where(RmaClaimML.resource_id.isnot(None))
    )
    _run_insert_select(db, match)

    total = db.query(func.count(RmaClaimML.id)).scalar() or 0
    linked = (
        db.query(func.count(func.distinct(RmaClaimML.id)))
        .select_from(RmaClaimML)
        .join(MlOrdersOps, MlOrdersOps.order_id == RmaClaimML.resource_id)
        .scalar()
        or 0
    )
    return linked, total - linked


def _resolve_messages(db: Session) -> tuple[int, int]:
    join_condition = cast(MlOrdersOps.pack_id, String) == MlBotMessage.pack_id

    match = (
        select(
            MlOrdersOps.order_id.label("order_id"),
            literal("message").label("entity_type"),
            MlBotMessage.id.label("entity_id"),
            literal("pack_id").label("link_source"),
            case(
                (func.count().over(partition_by=MlBotMessage.id) == 1, "exact"),
                else_="inferred",
            ).label("link_confidence"),
        )
        .select_from(MlBotMessage)
        .join(MlOrdersOps, join_condition)
        .where(MlBotMessage.pack_id.isnot(None))
    )
    _run_insert_select(db, match, refresh_confidence=True)

    total = db.query(func.count(MlBotMessage.id)).scalar() or 0
    linked = (
        db.query(func.count(func.distinct(MlBotMessage.id)))
        .select_from(MlBotMessage)
        .join(MlOrdersOps, join_condition)
        .scalar()
        or 0
    )
    return linked, total - linked


def _question_order_join(from_clause):
    """Shared JOIN condition: same item_id AND same buyer_id."""
    return from_clause.join(MlOrderItemOps, MlOrderItemOps.item_id == MlBotQuestion.item_id).join(
        MlOrdersOps,
        (MlOrdersOps.order_id == MlOrderItemOps.order_id) & (MlOrdersOps.buyer_id == MlBotQuestion.buyer_id),
    )


def _resolve_questions(db: Session) -> tuple[int, int]:
    match = _question_order_join(
        select(
            MlOrdersOps.order_id.label("order_id"),
            literal("question").label("entity_type"),
            MlBotQuestion.id.label("entity_id"),
            literal("item_id").label("link_source"),
            literal("inferred").label("link_confidence"),
        ).select_from(MlBotQuestion)
    ).where(MlBotQuestion.buyer_id.isnot(None))
    _run_insert_select(db, match)

    total = db.query(func.count(MlBotQuestion.id)).scalar() or 0
    linked_query = _question_order_join(db.query(func.distinct(MlBotQuestion.id)).select_from(MlBotQuestion))
    linked = db.query(func.count()).select_from(linked_query.subquery()).scalar() or 0
    return linked, total - linked


def resolve_links(db: Session) -> LinkResolutionResult:
    """Reads claims/questions/messages (READ-ONLY, see module docstring)
    and writes resolvable links into `ml_operation_links`. Never raises for
    an unresolvable entity -- an unresolved entity is simply not linked.
    Set-based: bounded number of statements regardless of table size."""
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


def get_unlinked_claims(db: Session, limit: int = DEFAULT_UNLINKED_LIMIT, offset: int = 0) -> List[RmaClaimML]:
    """Claims with no row in `ml_operation_links` -- the "flagged as
    unlinked" query path (spec: unresolved links MUST be recorded/queryable,
    never silently dropped). Paginated: this is a query path a UI consumes
    directly (pre-push review finding 3)."""
    linked_ids = db.query(MlOperationLink.entity_id).filter(MlOperationLink.entity_type == "claim")
    return (
        db.query(RmaClaimML)
        .filter(~RmaClaimML.id.in_(linked_ids))
        .order_by(RmaClaimML.id)
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_unlinked_messages(db: Session, limit: int = DEFAULT_UNLINKED_LIMIT, offset: int = 0) -> List[MlBotMessage]:
    linked_ids = db.query(MlOperationLink.entity_id).filter(MlOperationLink.entity_type == "message")
    return (
        db.query(MlBotMessage)
        .filter(~MlBotMessage.id.in_(linked_ids))
        .order_by(MlBotMessage.id)
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_unlinked_questions(db: Session, limit: int = DEFAULT_UNLINKED_LIMIT, offset: int = 0) -> List[MlBotQuestion]:
    linked_ids = db.query(MlOperationLink.entity_id).filter(MlOperationLink.entity_type == "question")
    return (
        db.query(MlBotQuestion)
        .filter(~MlBotQuestion.id.in_(linked_ids))
        .order_by(MlBotQuestion.id)
        .limit(limit)
        .offset(offset)
        .all()
    )
