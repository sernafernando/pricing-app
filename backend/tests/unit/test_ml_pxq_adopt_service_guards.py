"""Adversarial / invariant guards for `ml_pxq_adopt_service.py`
(change `pxq-adopt-live`, slice 3b part 2).

Part 1 (`test_ml_pxq_adopt_service.py`) asks "given this state, what
happens?" -- one test per outcome. This file asks "is this invariant still
TRUE?", which is a different question: these are the regression armour that
stops someone quietly undoing the production repair later, and several of
them guard properties that no behavioural test can observe.

All `ml_webhook_client` calls are mocked. No live-prod calls ever.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Query

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.ml_pxq_tier import ESTADO_INCOMPLETO, MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import ml_pxq_adopt_service as adopt_service
from app.services.ml_pxq_write_service import SYNC_STATUSES
from app.services.ml_webhook_client import MLWebhookClient
from app.services.pxq_diff import MAX_TIERS
from app.services.pxq_permissions_backfill import PXQ_ESCRIBIR_CODE

ADOPT_LOGGER = "app.services.ml_pxq_adopt_service"


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_guard_user",
        email="pxq_guard_user@example.com",
        nombre="PxQ Guard User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    user._permisos_cache = {PXQ_ESCRIBIR_CODE}
    return user


@pytest.fixture()
def sin_permiso_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_guard_nopriv",
        email="pxq_guard_nopriv@example.com",
        nombre="PxQ Guard No Priv",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    user._permisos_cache = set()
    return user


@pytest.fixture()
def publicacion(db) -> PublicacionML:
    producto = ProductoERP(item_id=90311, codigo="SKU-PXQ-GUARD", descripcion="Producto PxQ Guard", costo=1000.0)
    db.add(producto)
    db.flush()
    pub = PublicacionML(mla="MLA930011", item_id=producto.item_id, codigo="SKU-PXQ-GUARD")
    db.add(pub)
    db.flush()
    return pub


def _live(entry_id: Any, quantity: Any, amount: Any) -> Dict[str, Any]:
    return {"id": entry_id, "quantity": quantity, "amount": amount}


def _mock_client(live_prices: Optional[List[Dict[str, Any]]]):
    """Patches `adopt_service.ml_webhook_client`. `get_pxq_prices` is the ONLY
    method given a return value: every other attribute stays an auto-created
    child mock, so any call to one is both harmless and RECORDED in
    `mock_client.method_calls`, which is what guard 2 inspects."""
    patcher = patch.object(adopt_service, "ml_webhook_client")
    mock_client = patcher.start()
    mock_client.get_pxq_prices = AsyncMock(return_value=live_prices)
    return patcher, mock_client


def _adopt_outcome(db, usuario, publicacion) -> adopt_service.AdoptOutcome:
    return adopt_service.adopt_live_pxq_tiers(db, usuario, publicacion.mla, publicacion_ml_id=publicacion.id)


def _adopt(db, usuario, publicacion) -> List[MlPxqTier]:
    """The imported rows alone. Guards that assert on what was SKIPPED use
    `_adopt_outcome` instead."""
    return _adopt_outcome(db, usuario, publicacion).imported


def _tier_count(db, publicacion) -> int:
    return db.query(MlPxqTier).filter(MlPxqTier.publicacion_ml_id == publicacion.id).count()


def _ml_write_method_names() -> Set[str]:
    """Every public non-`get_` method on the REAL client, derived rather than
    hardcoded: a new outbound sibling added next to `post_pxq_prices` is
    covered by guard 2 the moment it exists, without anyone remembering to
    extend a list here."""
    return {
        name
        for name in dir(MLWebhookClient)
        if not name.startswith("_") and not name.startswith("get_") and callable(getattr(MLWebhookClient, name))
    }


ML_WRITE_METHODS = _ml_write_method_names()


def _assert_no_ml_write(mock_client) -> None:
    """`post_pxq_prices` and every sibling stayed untouched, and the ONLY ML
    method reached at all was the live read."""
    for name in ML_WRITE_METHODS:
        getattr(mock_client, name).assert_not_called()
    reached = {str(call[0]).split(".")[0] for call in mock_client.method_calls}
    assert reached <= {"get_pxq_prices"}, f"adopt-live touched non-read ML methods: {sorted(reached)}"


# --- Guard 1: the kill switch must NOT gate this path ---------------------


def test_import_still_succeeds_with_pxq_write_enabled_false(db, publicacion, pxq_user, monkeypatch) -> None:
    """THE MOST IMPORTANT TEST IN THIS CHANGE.

    `PXQ_WRITE_ENABLED` scopes the IRREVERSIBLE outbound array-replace POST:
    that POST replaces MercadoLibre's whole tier array, so a bad one destroys
    live money data. `adopt-live` never performs it. It writes only local,
    operator-deletable mirror rows, exactly like the three `pxq.escribir` CRUD
    endpoints, none of which are gated by the switch either.

    If you are here because you added the gate as a "safety" reflex: that gate
    KILLS the recovery path for the four publications that lost their mirrored
    tiers, which is the entire reason this feature exists. Worse, the flag's
    production value is unverified — if it is false in prod, adopt-live would
    return "disabled" for a payload it read perfectly well, and nobody would
    notice the recovery had silently died. Delete the gate, not this test.
    """
    monkeypatch.setattr(settings, "PXQ_WRITE_ENABLED", False)
    patcher, mock_client = _mock_client([_live("ML1", 3, 900.5), _live("ML2", 6, "850.25")])
    try:
        rows = _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert [r.cantidad_minima for r in rows] == [3, 6]
    assert [r.estado for r in rows] == [ESTADO_INCOMPLETO, ESTADO_INCOMPLETO]
    assert _tier_count(db, publicacion) == 2, "the kill switch must not be able to swallow an import"
    _assert_no_ml_write(mock_client)


# --- Guard 2: import-only, on EVERY outcome -------------------------------


@pytest.mark.parametrize(
    "live_prices, expected_status",
    [
        pytest.param([_live("ML1", 3, 900.0)], None, id="success"),
        pytest.param([], None, id="empty-live"),
        pytest.param(None, 503, id="read-failed"),
        pytest.param([_live(f"ML{n}", n, 100.0 * n) for n in range(2, 3 + MAX_TIERS)], 503, id="above-max-tiers"),
        pytest.param([{"quantity": 3, "amount": 900.0}], 503, id="malformed"),
    ],
)
def test_no_ml_write_endpoint_is_called_on_any_outcome(db, publicacion, pxq_user, live_prices, expected_status) -> None:
    """`Import only` is the feature's core PROMISE, not a happy-path detail:
    a refusal path that reached for `post_pxq_prices` would push a
    half-reconstructed array over live tiers, which is the incident itself.
    So it is proven on every branch, including the ones that raise."""
    patcher, mock_client = _mock_client(live_prices)
    try:
        if expected_status is None:
            _adopt(db, pxq_user, publicacion)
        else:
            with pytest.raises(HTTPException) as exc_info:
                _adopt(db, pxq_user, publicacion)
            assert exc_info.value.status_code == expected_status
    finally:
        patcher.stop()

    _assert_no_ml_write(mock_client)


def test_no_ml_write_endpoint_is_called_on_conflict_or_permission_refusal(
    db, publicacion, pxq_user, sin_permiso_user
) -> None:
    """The two refusals the parametrized sweep cannot express: a non-empty
    mirror (409) and a missing `pxq.escribir` (403, which refuses BEFORE the
    live read, so not even that one call may happen)."""
    patcher, mock_client = _mock_client([_live("ML1", 3, 900.0)])
    try:
        with pytest.raises(HTTPException) as denied:
            _adopt(db, sin_permiso_user, publicacion)
        assert denied.value.status_code == 403
        mock_client.get_pxq_prices.assert_not_called()

        db.add(
            MlPxqTier(
                publicacion_ml_id=publicacion.id,
                item_id=publicacion.mla,
                cantidad_minima=4,
                precio_unitario=999,
                estado=ESTADO_INCOMPLETO,
                usuario_id=pxq_user.id,
            )
        )
        db.flush()
        with pytest.raises(HTTPException) as conflict:
            _adopt(db, pxq_user, publicacion)
        assert conflict.value.status_code == 409
    finally:
        patcher.stop()

    _assert_no_ml_write(mock_client)


# --- Guard 3: the D3 dirty check runs, and runs BEFORE the commit ---------


def test_base_price_dirty_check_runs_immediately_before_the_single_commit(db, publicacion, pxq_user) -> None:
    """`_assert_no_base_price_dirty` is IMPORTED from `ml_pxq_write_service`
    rather than hand-copied, because a second copy of a safety condition is
    the drift class this feature keeps getting bitten by. That import is also
    the only reason `settings` is reachable from this module at all — which is
    exactly why guard 1 (`PXQ_WRITE_ENABLED=False` still imports) exists next
    to this one: transitively dragging `settings` in is NOT this module
    adopting the kill switch, and the assertion below states that in code.
    """
    assert not hasattr(adopt_service, "settings"), (
        "ml_pxq_adopt_service must not bind `settings` — see guard 1, it is not gated by PXQ_WRITE_ENABLED"
    )

    events: List[str] = []
    real_assert = adopt_service._assert_no_base_price_dirty
    real_commit = db.commit

    def spy_assert(session) -> None:
        events.append("dirty_check")
        real_assert(session)

    def spy_commit() -> None:
        events.append("commit")
        real_commit()

    patcher, _ = _mock_client([_live("ML1", 3, 900.0), _live("ML2", 6, 850.0)])
    try:
        with patch.object(adopt_service, "_assert_no_base_price_dirty", spy_assert):
            with patch.object(db, "commit", spy_commit):
                rows = _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert len(rows) == 2
    assert events == ["dirty_check", "commit"], (
        f"expected exactly one dirty check, immediately before the one commit; got {events}"
    )


# --- Guard 4: SYNC_STATUSES is not a dumping ground ----------------------


def test_adopt_live_does_not_extend_sync_statuses() -> None:
    """`SYNC_STATUSES` is 1:1 coupled to the router's `_SYNC_STATUS_TO_HTTP`
    by `test_pxq_router_live_endpoint.py`: every member must have a mapping
    entry. `adopt-live` raises `HTTPException` directly and returns no status
    string at all, so adding `adopt_conflict`/`adopt_read_unavailable` here
    would force mapping entries for outcomes that mapping was never about,
    and dilute a frozenset whose whole value is being exhaustive about ONE
    thing: what `sync_pxq_tiers` can return."""
    assert SYNC_STATUSES == frozenset(
        {
            "disabled",
            "rejected_not_eligible",
            "rejected_eligibility_unknown",
            "rejected_read_unavailable",
            "divergence",
            "rejected_by_proxy",
            "submitted_unconfirmed",
            "ambiguous_needs_reconcile",
            "sincronizado",
        }
    )
    assert not any(status.startswith("adopt") for status in SYNC_STATUSES)


# --- Guard 5: lazy `%s` logging ------------------------------------------


def _adopt_records(caplog) -> List[logging.LogRecord]:
    return [r for r in caplog.records if r.name == ADOPT_LOGGER]


def _assert_lazy_formatting(records) -> None:
    """Same technique slice 1b established: an f-string bakes the message into
    `record.msg` and leaves `record.args` an empty tuple, which is falsy — so
    a truthy `args` on every record is proof of lazy `%s` substitution."""
    assert records, "expected at least one log record to inspect"
    for record in records:
        assert record.args, f"record {record.getMessage()!r} was not lazily formatted (record.args is empty)"


@pytest.mark.parametrize(
    "live_prices, expected_status, expected_level",
    [
        pytest.param([_live("ML1", 3, 900.0)], None, logging.INFO, id="success"),
        pytest.param([], None, logging.INFO, id="empty-live"),
        pytest.param(None, 503, logging.WARNING, id="read-failed"),
        pytest.param(
            [_live(f"ML{n}", n, 100.0 * n) for n in range(2, 3 + MAX_TIERS)], 503, logging.ERROR, id="above-max-tiers"
        ),
        pytest.param([{"quantity": 3, "amount": 900.0}], 503, logging.WARNING, id="malformed"),
    ],
)
def test_every_log_record_uses_lazy_percent_s_args(
    db, publicacion, pxq_user, caplog, live_prices, expected_status, expected_level
) -> None:
    """Covers every call site the service owns, including the ERROR-level one
    for the >MAX_TIERS refusal — the loudest line in the module, and therefore
    the one most likely to be reached for with an f-string."""
    patcher, _ = _mock_client(live_prices)
    try:
        with caplog.at_level(logging.DEBUG, logger=ADOPT_LOGGER):
            if expected_status is None:
                _adopt(db, pxq_user, publicacion)
            else:
                with pytest.raises(HTTPException):
                    _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    records = _adopt_records(caplog)
    _assert_lazy_formatting(records)
    assert max(r.levelno for r in records) == expected_level


def test_conflict_and_permission_refusal_log_lazily(db, publicacion, pxq_user, sin_permiso_user, caplog) -> None:
    """The two refusal call sites the payload sweep cannot reach."""
    db.add(
        MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=4,
            precio_unitario=999,
            estado=ESTADO_INCOMPLETO,
            usuario_id=pxq_user.id,
        )
    )
    db.flush()

    patcher, _ = _mock_client([_live("ML1", 3, 900.0)])
    try:
        with caplog.at_level(logging.DEBUG, logger=ADOPT_LOGGER):
            with pytest.raises(HTTPException):
                _adopt(db, sin_permiso_user, publicacion)
            with pytest.raises(HTTPException):
                _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    records = _adopt_records(caplog)
    _assert_lazy_formatting(records)
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 2, [r.getMessage() for r in warnings]


# --- Guard 6: the row lock is TAKEN (see the docstring for the caveat) ----


@pytest.fixture()
def db_trace(db, monkeypatch) -> List[str]:
    """Records the ordered DB operations adopt-live performs: row locks, the
    conflict read, inserts, commits and rollbacks."""
    events: List[str] = []
    real_wfu, real_all = Query.with_for_update, Query.all
    real_add, real_commit, real_rollback = db.add, db.commit, db.rollback

    def _entities(query) -> str:
        """Deduped: a two-column query on one entity is still one entity."""
        return ",".join(
            dict.fromkeys(d["entity"].__name__ for d in query.column_descriptions if d.get("entity") is not None)
        )

    def traced_wfu(self, *args, **kwargs):
        events.append(f"lock:{_entities(self)}")
        return real_wfu(self, *args, **kwargs)

    def traced_all(self, *args, **kwargs):
        events.append(f"read_all:{_entities(self)}")
        return real_all(self, *args, **kwargs)

    def traced_add(obj) -> None:
        events.append(f"insert:{type(obj).__name__}")
        real_add(obj)

    def traced_commit() -> None:
        events.append("commit")
        real_commit()

    def traced_rollback() -> None:
        events.append("rollback")
        real_rollback()

    monkeypatch.setattr(Query, "with_for_update", traced_wfu)
    monkeypatch.setattr(Query, "all", traced_all)
    monkeypatch.setattr(db, "add", traced_add)
    monkeypatch.setattr(db, "commit", traced_commit)
    monkeypatch.setattr(db, "rollback", traced_rollback)
    return events


def test_publication_row_is_locked_before_the_conflict_check_and_inside_the_insert_transaction(
    db, publicacion, pxq_user, db_trace
) -> None:
    """WHAT THIS PROVES: that `SELECT ... FOR UPDATE` is REQUESTED on the
    publication row, that it is requested BEFORE the conflict check reads the
    mirror, and that no commit or rollback separates that lock from the
    inserts — i.e. check-then-import runs as one locked transaction.

    WHAT THIS DOES NOT PROVE: that any lock is actually HELD. The test
    database is SQLite, where `with_for_update()` is a documented NO-OP —
    `create_pxq_tier` records the same caveat at its own lock. Racing two real
    threads here would therefore prove nothing and, worse, would PASS with the
    lock entirely absent, which is precisely the false comfort this test
    refuses to give. Real mutual exclusion is a PostgreSQL property and can
    only be demonstrated against PostgreSQL.

    What it does buy: deleting the lock, or moving it after the conflict
    check, fails here — and those are the two edits that would turn a
    concurrent double-import into an `IntegrityError` surfacing as a 500
    instead of the clean 409 the contract promises.
    """
    patcher, _ = _mock_client([_live("ML1", 3, 900.0), _live("ML2", 6, 850.0)])
    try:
        rows = _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert len(rows) == 2
    lock_at = db_trace.index("lock:PublicacionML")
    conflict_at = db_trace.index("read_all:MlPxqTier")
    first_insert_at = db_trace.index("insert:MlPxqTier")
    commit_at = db_trace.index("commit")

    assert lock_at < conflict_at < first_insert_at < commit_at, db_trace
    assert db_trace.count("commit") == 1, f"check-then-import must be ONE transaction: {db_trace}"
    assert "rollback" not in db_trace, db_trace


def test_a_second_import_against_a_non_empty_mirror_gets_a_clean_409_not_an_integrity_error(
    db, publicacion, pxq_user, db_trace
) -> None:
    """The serialized half of the race: once the first import has landed, the
    second one takes the lock, sees the now-non-empty mirror and refuses with
    409 — no insert is attempted, so the unique constraint on
    `(publicacion_ml_id, cantidad_minima)` is never reached and no
    `IntegrityError` can surface as a 500."""
    patcher, _ = _mock_client([_live("ML1", 3, 900.0)])
    try:
        _adopt(db, pxq_user, publicacion)
        db_trace.clear()
        with pytest.raises(HTTPException) as exc_info:
            _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["status"] == "adopt_conflict"
    assert "lock:PublicacionML" in db_trace, f"the conflicting import took no row lock at all: {db_trace}"
    assert db_trace.index("lock:PublicacionML") < db_trace.index("read_all:MlPxqTier"), db_trace
    assert not [e for e in db_trace if e.startswith("insert:")], db_trace
    assert "commit" not in db_trace, db_trace
    assert _tier_count(db, publicacion) == 1


# --- Guard 7: the mid-loop 422 the design said could not happen -----------


def test_a_422_raised_mid_loop_persists_nothing(db, publicacion, pxq_user) -> None:
    """The design claims "every refusal path raises before any `db.add`, so
    the transaction has nothing to roll back". THAT CLAIM IS FALSE, and this
    payload is the counterexample: `create_pxq_tier`'s duplicate
    `cantidad_minima` validation fires INSIDE the import loop, after the
    earlier entry was already `db.add`-ed AND flushed. The first assertion
    below pins that reality.

    This used to be parametrized with a second payload, `quantity-of-one`.
    That one no longer raises at all -- it is SKIPPED now (guard 8) -- and
    leaving it here would have asserted the abort this change exists to
    remove.

    The SPEC still holds — zero rows are persisted — but for a different
    reason than the design gives: `get_db` never commits, and closes the
    session in its `finally`, which discards the whole uncommitted
    transaction. So "nothing persisted" is a property of the SESSION
    LIFECYCLE, not of the refusal ordering. That is why the real proof here is
    `commit` never happening: a committed row would survive `close()`, an
    uncommitted one cannot.

    Deliberately no `db.rollback()` is asserted or expected. See the decision
    recorded on `adopt_live_pxq_tiers`' 422 contract: this service does not
    own the session it was handed, so unwinding it is not its call.
    """
    commit_spy = MagicMock(wraps=db.commit)
    rollback_spy = MagicMock(wraps=db.rollback)
    patcher, mock_client = _mock_client([_live("ML1", 3, 900.0), _live("ML2", 3, 850.0)])
    try:
        with patch.object(db, "commit", commit_spy):
            with patch.object(db, "rollback", rollback_spy):
                with pytest.raises(HTTPException) as exc_info:
                    _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert exc_info.value.status_code == 422

    # The design's claim, falsified: the first entry IS staged and flushed
    # before the second one refuses. If this ever reads 0, the ordering
    # genuinely changed and the docstring above must be rewritten, not the
    # number.
    assert _tier_count(db, publicacion) == 1, "expected the first tier to be flushed-but-uncommitted"

    # ...and the reason nothing is PERSISTED, which is a different fact:
    commit_spy.assert_not_called()
    rollback_spy.assert_not_called()
    _assert_no_ml_write(mock_client)


# --- Guard 8: the skip is narrow, and stays narrow ------------------------


def test_a_duplicate_quantity_still_aborts_because_nothing_says_which_entry_wins(db, publicacion, pxq_user) -> None:
    """The skip covers ONE condition and must never be widened into "swallow
    any 422 the import loop raises".

    `cantidad_minima <= 1` is individually decidable and known by design: that
    entry cannot be a tier here, no other entry changes that, and there is
    exactly one right thing to do with it. Two entries sharing a quantity is
    the opposite -- WHICH price wins is a question the payload does not
    answer, and picking one silently would write a money value nobody chose.
    Failing loud is the correct outcome there, and it stays that way.

    Both payloads are asserted in ONE test on purpose: the property being
    guarded is the ASYMMETRY, and split across two tests each half would still
    pass under an implementation that catches `HTTPException` and skips
    everything.
    """
    skippable = [_live("ML1", 1, 999.0), _live("ML2", 4, 900.0)]
    ambiguous = [_live("ML3", 4, 900.0), _live("ML4", 4, 850.0)]

    patcher, _ = _mock_client(skippable)
    try:
        outcome = _adopt_outcome(db, pxq_user, publicacion)
    finally:
        patcher.stop()
    assert [s.cantidad_minima for s in outcome.skipped] == [1]
    assert [r.cantidad_minima for r in outcome.imported] == [4]

    # Same publication, now non-empty -- so a second import would 409 before
    # reaching the loop. A fresh one is what isolates the 422.
    otro = PublicacionML(mla="MLA930012", item_id=publicacion.item_id, codigo="SKU-PXQ-GUARD")
    db.add(otro)
    db.flush()

    patcher, _ = _mock_client(ambiguous)
    try:
        with pytest.raises(HTTPException) as exc_info:
            _adopt(db, pxq_user, otro)
    finally:
        patcher.stop()

    assert exc_info.value.status_code == 422
    assert "cantidad_minima=4" in str(exc_info.value.detail)
