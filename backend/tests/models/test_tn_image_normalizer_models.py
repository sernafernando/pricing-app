"""Model tests for the Tienda Nube image normalizer tables (slice 3).

These tables have NO readers or writers yet — that is intentional. Slice 3
only proves the schema itself: the dedup unique constraint on the artifact
table, NOT NULL enforcement on the columns that anchor state machines, and
the `dry_run` safe default (no stage may write to Tienda Nube without a
human having seen a dry-run first).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.models.tn_image_normalizer import (
    TnImageArtifact,
    TnImageNormalizationItem,
    TnImageNormalizationRun,
)
from app.models.usuario import AuthProvider, RolUsuario, Usuario


@pytest.fixture()
def tn_img_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="tn_img_user",
        email="tn_img_user@example.com",
        nombre="TN Image User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_run(user, **overrides) -> TnImageNormalizationRun:
    defaults = dict(
        created_by_user_id=user.id,
        preset=1080,
        output_format="jpeg",
        quality=85,
        max_output_bytes=3145728,
        params_fingerprint="a" * 32,
        state="pending",
    )
    defaults.update(overrides)
    return TnImageNormalizationRun(**defaults)


def _make_artifact(**overrides) -> TnImageArtifact:
    defaults = dict(
        source_hash="b" * 64,
        normalization_params="a" * 32,
        output_path="uploads/tn_images/ab/abcd.jpg",
    )
    defaults.update(overrides)
    return TnImageArtifact(**defaults)


class TestTnImageNormalizationRun:
    def test_create_run_row(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user)
        db.add(run)
        db.flush()

        assert run.id is not None
        assert run.created_at is not None
        assert run.finished_at is None

    def test_dry_run_defaults_to_true(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user)
        db.add(run)
        db.flush()
        db.refresh(run)

        assert run.dry_run is True

    def test_dry_run_can_be_explicitly_set_false(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user, dry_run=False)
        db.add(run)
        db.flush()
        db.refresh(run)

        assert run.dry_run is False

    def test_fill_color_defaults_to_white(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user)
        db.add(run)
        db.flush()
        db.refresh(run)

        assert run.fill_color == "#ffffff"

    def test_totals_accepts_json(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user, totals={"total": 10, "done": 3})
        db.add(run)
        db.flush()
        db.refresh(run)

        assert run.totals == {"total": 10, "done": 3}


class TestTnImageArtifact:
    def test_create_artifact_row(self, db) -> None:
        artifact = _make_artifact()
        db.add(artifact)
        db.flush()

        assert artifact.id is not None

    def test_duplicate_source_hash_and_params_violates_unique_constraint(self, db) -> None:
        db.add(_make_artifact())
        db.flush()

        db.add(_make_artifact())
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_same_source_hash_different_params_allowed(self, db) -> None:
        db.add(_make_artifact())
        db.flush()

        db.add(_make_artifact(normalization_params="c" * 32))
        db.flush()

        rows = db.query(TnImageArtifact).filter_by(source_hash="b" * 64).all()
        assert len(rows) == 2

    def test_source_hash_is_not_nullable(self, db) -> None:
        artifact = _make_artifact(source_hash=None)
        db.add(artifact)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_normalization_params_is_not_nullable(self, db) -> None:
        artifact = _make_artifact(normalization_params=None)
        db.add(artifact)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestTnImageNormalizationItem:
    def test_create_item_row(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user)
        db.add(run)
        db.flush()

        item = TnImageNormalizationItem(
            run_id=run.id,
            ean="7791234567890",
            source_slot=0,
            source_url="https://example.com/img.jpg",
            state="pending",
            attempts=0,
        )
        db.add(item)
        db.flush()

        assert item.id is not None
        assert item.inconclusive_reason is None
        assert item.artifact_id is None

    def test_state_is_not_nullable(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user)
        db.add(run)
        db.flush()

        item = TnImageNormalizationItem(
            run_id=run.id,
            ean="7791234567890",
            source_slot=0,
            source_url="https://example.com/img.jpg",
            state=None,
            attempts=0,
        )
        db.add(item)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_inconclusive_reason_is_its_own_column_distinct_from_failed(self, db, tn_img_user) -> None:
        """`inconclusive` must be reachable as a first-class state with its own
        reason text — never collapsed into a generic error/detail blob — so a
        timed-out verification can never be confused with an authorized delete."""
        run = _make_run(tn_img_user)
        db.add(run)
        db.flush()

        item = TnImageNormalizationItem(
            run_id=run.id,
            ean="7791234567890",
            source_slot=0,
            source_url="https://example.com/img.jpg",
            state="inconclusive",
            inconclusive_reason="verification timed out after 3 attempts",
            attempts=3,
        )
        db.add(item)
        db.flush()
        db.refresh(item)

        assert item.state == "inconclusive"
        assert item.inconclusive_reason == "verification timed out after 3 attempts"

    def test_composite_run_id_state_index_exists(self) -> None:
        index_names = {ix.name for ix in TnImageNormalizationItem.__table__.indexes}
        assert "ix_tn_image_normalization_item_run_id_state" in index_names

        composite = next(
            ix
            for ix in TnImageNormalizationItem.__table__.indexes
            if ix.name == "ix_tn_image_normalization_item_run_id_state"
        )
        assert [c.name for c in composite.columns] == ["run_id", "state"]

    def test_ean_and_tn_product_id_are_indexed(self) -> None:
        indexed_columns = set()
        for ix in TnImageNormalizationItem.__table__.indexes:
            for col in ix.columns:
                indexed_columns.add(col.name)

        assert "ean" in indexed_columns
        assert "tn_product_id" in indexed_columns

    def test_artifact_link_is_optional(self, db, tn_img_user) -> None:
        run = _make_run(tn_img_user)
        db.add(run)
        db.flush()

        artifact = _make_artifact()
        db.add(artifact)
        db.flush()

        item = TnImageNormalizationItem(
            run_id=run.id,
            ean="7791234567890",
            source_slot=0,
            source_url="https://example.com/img.jpg",
            artifact_id=artifact.id,
            state="done",
            attempts=1,
        )
        db.add(item)
        db.flush()
        db.refresh(item)

        assert item.artifact_id == artifact.id
