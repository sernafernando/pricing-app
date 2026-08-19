"""Service-layer validation for creating `MlPxqTier` rows (PR2, task 9/10).

Max 5 tiers per publication and `cantidad_minima >= 1` are validated here
(422) BEFORE hitting the DB — the DB CheckConstraint/UniqueConstraint are a
second, independent line of defense (see tests/models/test_ml_pxq_tier.py),
not the primary UX-facing validation path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.pxq_tier_service import (
    MAX_TIERS_PER_PUBLICATION,
    create_pxq_tier,
    delete_pxq_tier,
    update_pxq_tier,
)


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_svc_user",
        email="pxq_svc_user@example.com",
        nombre="PxQ Service User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def producto(db) -> ProductoERP:
    producto = ProductoERP(item_id=90101, codigo="SKU-PXQ-SVC", descripcion="Producto PxQ", costo=1000.0)
    db.add(producto)
    db.flush()
    return producto


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA910001", item_id=producto.item_id, codigo="SKU-PXQ-SVC")
    db.add(pub)
    db.flush()
    return pub


def test_create_tier_happy_path(db, publicacion, pxq_user) -> None:
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=500.0,
        usuario_id=pxq_user.id,
    )
    assert tier.id is not None
    assert tier.estado == "incompleto"


def test_a_one_unit_tier_is_created_because_it_is_what_turns_on_venta_para_negocios(db, publicacion, pxq_user) -> None:
    """The one-unit tier is not a leftover: it is what makes the publication
    show up as "Venta para negocios" on MercadoLibre. Without it the listing
    does not appear in that B2B shelf at all, so a mirror that cannot hold it
    cannot describe the state that matters.

    The previous 422 came from reading ML's documentation literally
    (`min_purchase_unit` must be greater than 1). Production contradicts the
    documentation on both counts: ML ACCEPTS it -- MLA1563835240 holds
    `{"id": "3396", "amount": 80999, "min_purchase_unit": 1}` with both
    `context_restrictions` -- and the entry does a job.
    """
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=1,
        precio_unitario=500.0,
        usuario_id=pxq_user.id,
    )

    assert tier.id is not None
    assert tier.cantidad_minima == 1
    assert db.query(MlPxqTier).filter_by(publicacion_ml_id=publicacion.id, cantidad_minima=1).count() == 1


def test_cantidad_minima_of_zero_is_still_rejected_with_422(db, publicacion, pxq_user) -> None:
    """The floor moved from 2 to 1, it did not disappear. A tier for zero units
    is not a quantity MercadoLibre can express and not a price anyone can buy;
    it would reach the DB CheckConstraint as an IntegrityError surfacing as a
    500 where this service promises a 422."""
    with pytest.raises(HTTPException) as exc_info:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=0,
            precio_unitario=500.0,
            usuario_id=pxq_user.id,
        )
    assert exc_info.value.status_code == 422


def test_sixth_tier_for_same_publication_rejected_with_422(db, publicacion, pxq_user) -> None:
    for cantidad in range(2, 2 + MAX_TIERS_PER_PUBLICATION):
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=cantidad,
            precio_unitario=500.0,
            usuario_id=pxq_user.id,
        )

    assert db.query(MlPxqTier).filter_by(publicacion_ml_id=publicacion.id).count() == MAX_TIERS_PER_PUBLICATION

    with pytest.raises(HTTPException) as exc_info:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=2 + MAX_TIERS_PER_PUBLICATION,
            precio_unitario=500.0,
            usuario_id=pxq_user.id,
        )
    assert exc_info.value.status_code == 422
    # The 6th tier must never have been persisted.
    assert db.query(MlPxqTier).filter_by(publicacion_ml_id=publicacion.id).count() == MAX_TIERS_PER_PUBLICATION


def test_unknown_publicacion_is_a_clean_422_not_an_integrity_error(db, pxq_user) -> None:
    """`with_for_update().first()` takes no lock when the row does not exist,
    so the TOCTOU window this service claims to close stayed open for exactly
    the case nobody checked. Verifying the lookup succeeded closes it and, in
    the same move, turns an FK IntegrityError at flush into the clean 422 this
    service says it produces."""
    with pytest.raises(HTTPException) as exc:
        create_pxq_tier(
            db,
            publicacion_ml_id=987654,
            item_id="MLA_NOPE",
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )

    assert exc.value.status_code == 422
    assert "987654" in str(exc.value.detail)


def test_price_is_stored_as_decimal_not_binary_float(db, publicacion, pxq_user) -> None:
    """`precio_unitario` is Numeric(14, 2). Money entering as a binary float
    means 500.10 is not 500.10, and nobody notices until a sum of tiers fails
    to reconcile."""
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=500.10,
        usuario_id=pxq_user.id,
        costo_envio_total=3200.45,
    )
    db.flush()

    assert isinstance(tier.precio_unitario, Decimal)
    assert tier.precio_unitario == Decimal("500.10")
    assert isinstance(tier.costo_envio_total, Decimal)
    assert tier.costo_envio_total == Decimal("3200.45")


def test_duplicate_cantidad_minima_through_the_service_is_a_clean_422(db, publicacion, pxq_user) -> None:
    """The unique constraint was only ever exercised by writing rows directly,
    so the service path — the one an endpoint actually calls — reached flush
    and raised IntegrityError, i.e. a 500 where this module promises a 422.

    The check sits inside the window already serialized by the publication
    lock, so it is not a new race of its own."""
    create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    with pytest.raises(HTTPException) as exc:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("900.00"),
            usuario_id=pxq_user.id,
        )

    assert exc.value.status_code == 422
    assert "5" in str(exc.value.detail)


def test_item_id_must_match_its_publication(db, publicacion, pxq_user) -> None:
    """`item_id` is the MLA denormalized off the publication, and PR 3 keys the
    live-vs-mirror diff on it. A row claiming a different MLA than its own
    publication would aim that diff at the wrong listing — so it is checked
    against the row the service already holds under lock."""
    with pytest.raises(HTTPException) as exc:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id="MLA_SOMETHING_ELSE",
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )

    assert exc.value.status_code == 422
    assert "MLA_SOMETHING_ELSE" in str(exc.value.detail)


def test_create_tier_without_snapshot_kwargs_leaves_both_columns_null(db, publicacion, pxq_user) -> None:
    """Existing-caller regression guard.

    The one production caller, `routers/pxq.py::crear_tier_pxq`, supplies
    neither snapshot kwarg and must keep producing byte-identically the row it
    produced before those kwargs existed. A manually created tier has never
    been confirmed by MercadoLibre, so NULL/NULL is the honest "never synced"
    answer that `pxq_diff.DesiredTier.has_snapshot` reads.
    """
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    assert tier.cantidad_sincronizada is None
    assert tier.precio_sincronizado is None


def test_create_tier_with_snapshot_kwargs_sets_both_columns(db, publicacion, pxq_user) -> None:
    """The import path (`adopt-live`) creates a row whose snapshot IS the value
    MercadoLibre just reported, in the same operation.

    `precio_sincronizado` must go through the same `Decimal(str(...))`
    discipline as `precio_unitario`: a direct `Decimal(float)` bakes in binary
    noise, and the snapshot is compared for EQUALITY against a live value on
    every later sync, so noise there produces a false "differs" verdict.
    """
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=500.10,
        usuario_id=pxq_user.id,
        cantidad_sincronizada=5,
        precio_sincronizado=500.10,
    )
    db.flush()

    assert tier.cantidad_sincronizada == 5
    assert isinstance(tier.precio_sincronizado, Decimal)
    assert tier.precio_sincronizado == Decimal("500.10")
    # `Decimal(500.10)` is 500.1000000000000227...; asserting the exact Decimal
    # above only proves the coercion happened if the float-built value is
    # distinguishable, so pin that it is.
    assert tier.precio_sincronizado != Decimal(500.10)


@pytest.mark.parametrize(
    ("snapshot_kwargs", "missing"),
    [
        ({"cantidad_sincronizada": 5}, "precio_sincronizado"),
        ({"precio_sincronizado": Decimal("500.00")}, "cantidad_sincronizada"),
    ],
    ids=["only-cantidad", "only-precio"],
)
def test_create_tier_with_half_a_snapshot_is_a_clean_422(db, publicacion, pxq_user, snapshot_kwargs, missing) -> None:
    """Both-or-neither: supplying exactly one of the pair is refused.

    `pxq_diff.DesiredTier.has_snapshot` is `synced_quantity is not None AND
    synced_amount is not None`, so a half-written snapshot reads as NO
    snapshot — and that is not merely inert. `local_changed` then returns True
    unconditionally and `live_changed` returns False unconditionally, so every
    later sync classifies the row as "we edited it, MercadoLibre did not" and
    pushes the local value over whatever ML holds. Permanently.

    That is the same silent-overwrite failure the three-way merge exists to
    prevent, so the half-written row is refused at the service boundary
    instead of being persisted for a later sync to act on.
    """
    with pytest.raises(HTTPException) as exc:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
            **snapshot_kwargs,
        )

    assert exc.value.status_code == 422
    # The message must name the column the caller forgot, not just complain.
    assert missing in str(exc.value.detail)
    # Nothing may survive the refusal.
    assert db.query(MlPxqTier).filter_by(publicacion_ml_id=publicacion.id).count() == 0


def test_update_tier_changes_price_and_quantity(db, publicacion, pxq_user) -> None:
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    updated = update_pxq_tier(
        db,
        tier_id=tier.id,
        cantidad_minima=8,
        precio_unitario=Decimal("650.00"),
    )

    assert updated.cantidad_minima == 8
    assert updated.precio_unitario == Decimal("650.00")


def test_update_tier_never_advances_the_synced_snapshot(db, publicacion, pxq_user) -> None:
    """`cantidad_sincronizada`/`precio_sincronizado` are what MercadoLibre last
    confirmed. Only a confirmed write (`pxq_confirm`) may advance them; an
    edit that touched them would make the next sync see local==synced and
    silently skip pushing the very change the user just made."""
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    tier.cantidad_sincronizada = 5
    tier.precio_sincronizado = Decimal("500.00")
    db.flush()

    updated = update_pxq_tier(
        db,
        tier_id=tier.id,
        cantidad_minima=9,
        precio_unitario=Decimal("999.00"),
    )

    assert updated.cantidad_sincronizada == 5
    assert updated.precio_sincronizado == Decimal("500.00")


def test_update_unknown_tier_is_a_clean_404(db) -> None:
    with pytest.raises(HTTPException) as exc:
        update_pxq_tier(db, tier_id=999999, cantidad_minima=5)

    assert exc.value.status_code == 404


def test_update_accepts_cantidad_minima_of_one_because_it_turns_on_venta_para_negocios(
    db, publicacion, pxq_user
) -> None:
    """INVERTED, and the asymmetry it removes was ours.

    A tier of ONE unit is what makes the publication appear as "Venta para
    negocios" on MercadoLibre -- the switch for the B2B shelf, which ML accepts
    and holds in production (MLA1563835240, price id 3396) despite its own
    documentation saying `min_purchase_unit` must be greater than 1.

    `create_pxq_tier` and the DB CheckConstraint already agreed on that. This
    path did not, and the gap only existed BECAUSE of that change: before it,
    neither create nor update took a one-unit tier, which was wrong but at
    least coherent. Leaving it half-moved would have shipped a state where the
    operator sees an imported one-unit tier in the panel, tries to fix its
    quantity by hand, and gets a 422 explaining nothing -- about a row the
    system itself had just written.
    """
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    updated = update_pxq_tier(db, tier_id=tier.id, cantidad_minima=1)

    assert updated.cantidad_minima == 1
    assert db.query(MlPxqTier).filter_by(id=tier.id).one().cantidad_minima == 1


def test_update_still_rejects_cantidad_minima_of_zero(db, publicacion, pxq_user) -> None:
    """The floor moved from 2 to 1 on this path too; it did not disappear.
    Zero is not a quantity MercadoLibre can express, and reaching the DB
    CheckConstraint with it would surface an IntegrityError as a 500 where this
    service promises a 422."""
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    with pytest.raises(HTTPException) as exc:
        update_pxq_tier(db, tier_id=tier.id, cantidad_minima=0)

    assert exc.value.status_code == 422
    assert db.query(MlPxqTier).filter_by(id=tier.id).one().cantidad_minima == 5


def test_update_rejects_duplicate_cantidad_minima_on_the_same_publication(db, publicacion, pxq_user) -> None:
    create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    other = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=6,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    with pytest.raises(HTTPException) as exc:
        update_pxq_tier(db, tier_id=other.id, cantidad_minima=5)

    assert exc.value.status_code == 422


def test_update_price_is_stored_as_decimal_not_binary_float(db, publicacion, pxq_user) -> None:
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    updated = update_pxq_tier(db, tier_id=tier.id, precio_unitario=650.10)

    assert isinstance(updated.precio_unitario, Decimal)
    assert updated.precio_unitario == Decimal("650.10")


def test_delete_tier_removes_the_local_row(db, publicacion, pxq_user) -> None:
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()
    tier_id = tier.id

    delete_pxq_tier(db, tier_id=tier_id)
    db.flush()

    assert db.query(MlPxqTier).filter_by(id=tier_id).first() is None


def test_delete_unknown_tier_is_a_clean_404(db) -> None:
    with pytest.raises(HTTPException) as exc:
        delete_pxq_tier(db, tier_id=999999)
    assert exc.value.status_code == 404


class TestCostoEnvioFetchedAtD3:
    """D3 (slice B, task 4.5/4.6): `costo_envio_fetched_at` tracks freshness
    of the VALUE, not authorship. This CORRECTS the spec — see the design
    doc's precedence note.

      - manual write to `costo_envio_total`            -> stamp now() (NEVER NULL)
      - write to `precio_unitario`/`cantidad_minima`    -> NULL (invalidate)
      - a failed auto-fetch touches NEITHER column (covered in
        `test_pxq_markup_service.py`/`test_pxq_shipping_refresh.py`, not here
        — this class only covers the `update_pxq_tier` write path)
      - PATCH with BOTH an invalidating field AND `costo_envio_total`:
        invalidate first, stamp after — deterministic, manual value wins.
    """

    def test_manual_write_to_costo_envio_total_stamps_now(self, db, publicacion, pxq_user) -> None:
        tier = create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )
        db.flush()
        assert tier.costo_envio_fetched_at is None

        before = datetime.now(timezone.utc)
        updated = update_pxq_tier(db, tier_id=tier.id, costo_envio_total=Decimal("120.00"))
        after = datetime.now(timezone.utc)

        assert updated.costo_envio_total == Decimal("120.00")
        assert updated.costo_envio_fetched_at is not None
        stamp = updated.costo_envio_fetched_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        assert before <= stamp <= after

    def test_write_to_precio_unitario_nulls_the_stamp(self, db, publicacion, pxq_user) -> None:
        tier = create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )
        tier.costo_envio_total = Decimal("120.00")
        tier.costo_envio_fetched_at = datetime.now(timezone.utc)
        db.flush()

        updated = update_pxq_tier(db, tier_id=tier.id, precio_unitario=Decimal("650.00"))

        assert updated.costo_envio_fetched_at is None
        # The stale shipping value is left in place — only the freshness
        # marker is invalidated, forcing a re-fetch on the next open.
        assert updated.costo_envio_total == Decimal("120.00")

    def test_write_to_cantidad_minima_nulls_the_stamp(self, db, publicacion, pxq_user) -> None:
        tier = create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )
        tier.costo_envio_total = Decimal("120.00")
        tier.costo_envio_fetched_at = datetime.now(timezone.utc)
        db.flush()

        updated = update_pxq_tier(db, tier_id=tier.id, cantidad_minima=8)

        assert updated.costo_envio_fetched_at is None
        assert updated.costo_envio_total == Decimal("120.00")

    def test_patch_with_both_invalidating_field_and_costo_envio_total_stamps_deterministically(
        self, db, publicacion, pxq_user
    ) -> None:
        """Invalidate FIRST, stamp AFTER — manual value wins. A PATCH that
        changes `precio_unitario` (which normally NULLs the stamp) AND
        supplies `costo_envio_total` in the same call must end up STAMPED,
        not NULL, because the operator is asserting a fresh shipping value
        for the new price/quantity in the same request."""
        tier = create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )
        tier.costo_envio_total = Decimal("120.00")
        tier.costo_envio_fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.flush()

        updated = update_pxq_tier(
            db,
            tier_id=tier.id,
            precio_unitario=Decimal("700.00"),
            costo_envio_total=Decimal("150.00"),
        )

        assert updated.precio_unitario == Decimal("700.00")
        assert updated.costo_envio_total == Decimal("150.00")
        assert updated.costo_envio_fetched_at is not None

    def test_patch_with_cantidad_minima_and_costo_envio_total_stamps_deterministically(
        self, db, publicacion, pxq_user
    ) -> None:
        tier = create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )
        db.flush()

        updated = update_pxq_tier(
            db,
            tier_id=tier.id,
            cantidad_minima=9,
            costo_envio_total=Decimal("99.00"),
        )

        assert updated.cantidad_minima == 9
        assert updated.costo_envio_total == Decimal("99.00")
        assert updated.costo_envio_fetched_at is not None

    def test_update_omitting_both_fields_leaves_the_stamp_untouched(self, db, publicacion, pxq_user) -> None:
        """`is not None` ("field supplied") semantics stay intact: a field
        genuinely omitted from the call must not trigger either D3 branch."""
        tier = create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )
        stamp = datetime.now(timezone.utc) - timedelta(hours=2)
        tier.costo_envio_total = Decimal("120.00")
        tier.costo_envio_fetched_at = stamp
        db.flush()

        # No cantidad_minima, no precio_unitario, no costo_envio_total.
        updated = update_pxq_tier(db, tier_id=tier.id)

        assert updated.costo_envio_total == Decimal("120.00")
        got = updated.costo_envio_fetched_at
        if got.tzinfo is None:
            got = got.replace(tzinfo=timezone.utc)
        expected = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)
        assert got == expected
