"""Behavioural tests for the PxQ import service `ml_pxq_adopt_service.py`
(change `pxq-adopt-live`, slice 3b part 1).

Lives in `tests/unit/` beside `test_ml_pxq_write_service.py` and
`test_pxq_confirm.py`, not in `tests/services/`: every other test for an
`ml_pxq*`/`pxq_*` orchestration module in this feature is here, and the plan's
`tests/services/` path was already found wrong once (slice 2).

Covers BEHAVIOUR only, one test per outcome of `adopt_live_pxq_tiers`. The
adversarial/invariant matrix (concurrency, `PXQ_WRITE_ENABLED=False`, the
no-ML-write guard, the `_assert_no_base_price_dirty` spy, the `SYNC_STATUSES`
guard and the lazy-`%s` logging guard) is deliberately NOT here — it is slice
3b part 2.

All `ml_webhook_client` calls are mocked. No live-prod calls ever.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.ml_pxq_tier import ESTADO_INCOMPLETO, MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import ml_pxq_adopt_service as adopt_service
from app.services.ml_pxq_write_service import _desired_tiers_from_mirror
from app.services.pxq_diff import MAX_TIERS, LiveTier, diff_pxq_tiers
from app.services.pxq_permissions_backfill import PXQ_ESCRIBIR_CODE


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_adopt_user",
        email="pxq_adopt_user@example.com",
        nombre="PxQ Adopt User",
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
def producto(db) -> ProductoERP:
    p = ProductoERP(item_id=90301, codigo="SKU-PXQ-ADOPT", descripcion="Producto PxQ Adopt", costo=1000.0)
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA930001", item_id=producto.item_id, codigo="SKU-PXQ-ADOPT")
    db.add(pub)
    db.flush()
    return pub


def _live(entry_id: Any, quantity: Any, amount: Any) -> Dict[str, Any]:
    return {"id": entry_id, "quantity": quantity, "amount": amount}


def _mock_client(live_prices: Optional[List[Dict[str, Any]]]):
    """Patches `adopt_service.ml_webhook_client`; the live read is the only
    ML call this service is ever allowed to make."""
    patcher = patch.object(adopt_service, "ml_webhook_client")
    mock_client = patcher.start()
    mock_client.get_pxq_prices = AsyncMock(return_value=live_prices)
    return patcher, mock_client


def _adopt(db, usuario, publicacion) -> List[MlPxqTier]:
    return adopt_service.adopt_live_pxq_tiers(
        db,
        usuario,
        publicacion.mla,
        publicacion_ml_id=publicacion.id,
    )


def _tier_count(db, publicacion) -> int:
    return db.query(MlPxqTier).filter(MlPxqTier.publicacion_ml_id == publicacion.id).count()


def test_happy_path_imports_every_live_tier_with_its_snapshot(db, publicacion, pxq_user) -> None:
    """Each row gets quantity, price, `ml_price_id` AND both snapshot columns
    from the SAME live read; `costo_envio_total` stays NULL, so the row is
    genuinely `incompleto` until the operator supplies the shipping cost."""
    patcher, _ = _mock_client([_live("ML1", 3, 900.5), _live(2222, 6, "850.25"), _live("ML3", 12, 800)])
    try:
        rows = _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert len(rows) == 3
    assert [r.cantidad_minima for r in rows] == [3, 6, 12]
    assert [r.ml_price_id for r in rows] == ["ML1", "2222", "ML3"]
    assert [r.precio_unitario for r in rows] == [Decimal("900.5"), Decimal("850.25"), Decimal("800")]
    for row in rows:
        assert row.cantidad_sincronizada == row.cantidad_minima
        assert row.precio_sincronizado == row.precio_unitario
        assert row.costo_envio_total is None
        assert row.estado == ESTADO_INCOMPLETO
    assert _tier_count(db, publicacion) == 3


def test_failed_live_read_refuses_with_503_and_writes_nothing(db, publicacion, pxq_user) -> None:
    """`None` means we have NO view of live state. Importing anyway would be
    inventing the very data this change exists to recover."""
    patcher, _ = _mock_client(None)
    try:
        with pytest.raises(HTTPException) as exc_info:
            _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["status"] == "adopt_read_unavailable"
    assert _tier_count(db, publicacion) == 0


def test_genuinely_empty_live_set_is_a_clean_no_op_success(db, publicacion, pxq_user) -> None:
    """`[]` and `None` are two DIFFERENT facts. Collapsing them is the exact
    bug class this change repairs, so `[]` succeeds with zero imported and
    never reaches a commit."""
    commit_spy = MagicMock(wraps=db.commit)
    patcher, _ = _mock_client([])
    try:
        with patch.object(db, "commit", commit_spy):
            rows = _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert rows == []
    assert _tier_count(db, publicacion) == 0
    commit_spy.assert_not_called()


def test_any_pre_existing_local_row_refuses_naming_quantities_and_tier_ids(db, publicacion, pxq_user) -> None:
    """A quantity match with a differing price is undecidable without a human.
    The refusal must NAME what blocks it: the operator's recovery path is
    `DELETE /pxq/{item_id}/tiers/{tier_id}` and a retry, and a blind "there
    are local rows" would send them hunting for the ids."""
    existing = [
        MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=cantidad,
            precio_unitario=Decimal("999.00"),
            estado=ESTADO_INCOMPLETO,
            usuario_id=pxq_user.id,
        )
        for cantidad in (4, 9)
    ]
    db.add_all(existing)
    db.flush()

    patcher, _ = _mock_client([_live("ML1", 3, 900.0)])
    try:
        with pytest.raises(HTTPException) as exc_info:
            _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["status"] == "adopt_conflict"
    assert detail["conflicts"] == [
        {"tier_id": existing[0].id, "cantidad_minima": 4},
        {"tier_id": existing[1].id, "cantidad_minima": 9},
    ]
    assert _tier_count(db, publicacion) == 2


def test_more_live_tiers_than_max_refuses_before_importing_any(db, publicacion, pxq_user, caplog) -> None:
    """`MAX_TIERS` is MercadoLibre's OWN platform limit, so more than
    `MAX_TIERS` live entries is an IMPOSSIBLE state — the read is
    untrustworthy (ML changed the limit, the proxy returned garbage, or we
    read the wrong item), not a conflict an operator can resolve: they cannot
    delete tiers ML would never have let them create.

    So it must degrade to the SAME read-unavailable refusal as a failed read,
    and must be logged at ERROR — louder than every other refusal here —
    because an invariant broke and somebody has to see it. Truncating instead
    would silently drop money data with an arbitrary choice of which 5 to
    keep, and letting `create_pxq_tier` 422 on the 6th would report OUR local
    ceiling as a fact about ML's payload."""
    commit_spy = MagicMock(wraps=db.commit)
    live_count = MAX_TIERS + 1
    patcher, _ = _mock_client([_live(f"ML{n}", n, 100.0 * n) for n in range(2, 2 + live_count)])
    try:
        with patch.object(db, "commit", commit_spy):
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_adopt_service"):
                with pytest.raises(HTTPException) as exc_info:
                    _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert detail["status"] == "adopt_read_unavailable"
    assert str(live_count) in detail["reason"], detail["reason"]
    assert str(MAX_TIERS) in detail["reason"], detail["reason"]

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1, (
        f"expected exactly one ERROR log line, got: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    message = error_records[0].getMessage()
    assert str(live_count) in message, message
    assert str(MAX_TIERS) in message, message
    assert publicacion.mla in message, message

    assert _tier_count(db, publicacion) == 0
    commit_spy.assert_not_called()


@pytest.mark.parametrize(
    "bad_entry",
    [
        pytest.param({"quantity": 3, "amount": 900.0}, id="missing-id"),
        pytest.param(_live("ML2", 3, "not-a-number"), id="junk-amount"),
    ],
)
def test_malformed_live_entry_degrades_to_read_unavailable_not_a_500(
    db, publicacion, pxq_user, bad_entry: Dict[str, Any]
) -> None:
    """`live_entry_to_tier_fields` is pure and raises; a payload we cannot
    parse is the same situation as no read at all, and the caller must see the
    refusal rather than an unhandled 500. `ArithmeticError`
    (`decimal.InvalidOperation`) is NOT a `ValueError` — the bug
    `_live_tiers_from_raw` was already fixed for."""
    patcher, _ = _mock_client([_live("ML1", 3, 900.0), bad_entry])
    try:
        with pytest.raises(HTTPException) as exc_info:
            _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["status"] == "adopt_read_unavailable"
    assert _tier_count(db, publicacion) == 0


def test_imported_mirror_diffs_clean_against_the_same_live_state(db, publicacion, pxq_user) -> None:
    """END-TO-END FIDELITY — the point of the whole slice.

    An import that reconstructed state APPROXIMATELY would still look right
    row by row and then be refused, or worse silently overwrite ML, on the
    very next sync. So: import, supply the shipping cost the operator has to
    supply anyway (that is what makes a row priceable, `pxq_confirm.
    is_priceable`), and run the real `diff_pxq_tiers` against the SAME live
    state. Everything must classify as a keep — no divergence, no create, no
    modify, no delete.
    """
    live_raw = [_live("ML1", 3, 900.5), _live(2222, 6, "850.25")]
    patcher, _ = _mock_client(live_raw)
    try:
        rows = _adopt(db, pxq_user, publicacion)
    finally:
        patcher.stop()

    for row in rows:
        row.costo_envio_total = Decimal("50.00")
    db.flush()

    live_tiers = [LiveTier(id=str(e["id"]), quantity=int(e["quantity"]), amount=e["amount"]) for e in live_raw]
    result = diff_pxq_tiers(live_tiers, _desired_tiers_from_mirror(rows))

    assert result.ok, result.refusal
    assert result.array == [{"id": "ML1"}, {"id": "2222"}]
    assert result.counts.keeps == 2
    assert (result.counts.creates, result.counts.modifies, result.counts.deletes) == (0, 0, 0)
