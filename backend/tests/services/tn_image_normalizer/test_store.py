"""Tests for tn_image_normalizer.store: dedup, disk layout, and retention.

Runs against a real in-memory SQLite session holding only
`tn_image_artifact`, so the dedup unique constraint is genuinely enforced
(the `IntegrityError` race test exercises the real database error, not a
mocked one).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.tn_image_normalizer.store as store_module
from app.models.tn_image_normalizer import TnImageArtifact
from app.services.tn_image_normalizer.states import ITEM_DEDUP_HIT, ITEM_NORMALIZED
from app.services.tn_image_normalizer.store import (
    NormalizedOutput,
    StoredArtifact,
    artifact_output_path,
    store_normalized_artifact,
    sweep_expired_artifacts,
)

PARAMS_FP = "a" * 32
SOURCE_HASH = "b" * 64
OUTPUT_BYTES = b"normalized-jpeg-bytes"
OUTPUT_HASH = hashlib.sha256(OUTPUT_BYTES).hexdigest()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TnImageArtifact.__table__.create(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def _output() -> NormalizedOutput:
    return NormalizedOutput(content=OUTPUT_BYTES, width=800, height=800)


def _producer() -> MagicMock:
    return MagicMock(return_value=_output())


class TestPathLayout:
    def test_path_is_run_dir_plus_artifact_id_and_hash_prefix(self, tmp_path: Path) -> None:
        path = artifact_output_path(
            run_id=7,
            artifact_id=42,
            output_hash=OUTPUT_HASH,
            base_dir=tmp_path,
        )
        assert path == tmp_path / "7" / f"42_{OUTPUT_HASH[:12]}.jpg"

    def test_hash_prefix_is_exactly_twelve_characters(self, tmp_path: Path) -> None:
        path = artifact_output_path(run_id=1, artifact_id=2, output_hash=OUTPUT_HASH, base_dir=tmp_path)
        stem_hash = path.stem.split("_", 1)[1]
        assert len(stem_hash) == 12


class TestStoreHappyPath:
    def test_creates_run_directory_and_writes_bytes(self, db, tmp_path: Path) -> None:
        result = store_normalized_artifact(
            db,
            run_id=3,
            source_hash=SOURCE_HASH,
            normalization_params=PARAMS_FP,
            produce_output=_producer(),
            base_dir=tmp_path,
        )

        assert isinstance(result, StoredArtifact)
        assert result.state == ITEM_NORMALIZED
        assert result.dedup_hit is False
        written = Path(result.output_path)
        assert written.parent == tmp_path / "3"
        assert written.read_bytes() == OUTPUT_BYTES

    def test_persists_artifact_row_with_hash_and_dimensions(self, db, tmp_path: Path) -> None:
        result = store_normalized_artifact(
            db,
            run_id=3,
            source_hash=SOURCE_HASH,
            normalization_params=PARAMS_FP,
            produce_output=_producer(),
            base_dir=tmp_path,
        )

        row = db.query(TnImageArtifact).filter_by(id=result.artifact_id).one()
        assert row.source_hash == SOURCE_HASH
        assert row.normalization_params == PARAMS_FP
        assert row.output_hash == OUTPUT_HASH
        assert row.output_bytes == len(OUTPUT_BYTES)
        assert (row.width, row.height) == (800, 800)

    def test_oserror_on_write_is_handled_and_leaves_no_artifact_row(self, db, tmp_path: Path) -> None:
        with patch(
            "app.services.tn_image_normalizer.store.open",
            side_effect=OSError("disk full"),
            create=True,
        ):
            result = store_normalized_artifact(
                db,
                run_id=3,
                source_hash=SOURCE_HASH,
                normalization_params=PARAMS_FP,
                produce_output=_producer(),
                base_dir=tmp_path,
            )

        assert result is None
        assert db.query(TnImageArtifact).count() == 0


class TestDedup:
    def test_existing_artifact_short_circuits_without_normalizing_or_writing(self, db, tmp_path: Path) -> None:
        existing = TnImageArtifact(
            source_hash=SOURCE_HASH,
            normalization_params=PARAMS_FP,
            output_path="9/1_deadbeefcafe.jpg",
            output_hash=OUTPUT_HASH,
            output_bytes=len(OUTPUT_BYTES),
            width=800,
            height=800,
            created_at=datetime.now(timezone.utc),
        )
        db.add(existing)
        db.commit()

        producer = _producer()
        result = store_normalized_artifact(
            db,
            run_id=3,
            source_hash=SOURCE_HASH,
            normalization_params=PARAMS_FP,
            produce_output=producer,
            base_dir=tmp_path,
        )

        assert result.state == ITEM_DEDUP_HIT
        assert result.dedup_hit is True
        assert result.artifact_id == existing.id
        assert result.output_path == existing.output_path
        producer.assert_not_called()
        assert not (tmp_path / "3").exists()

    def test_different_params_are_not_deduped(self, db, tmp_path: Path) -> None:
        store_normalized_artifact(
            db,
            run_id=3,
            source_hash=SOURCE_HASH,
            normalization_params=PARAMS_FP,
            produce_output=_producer(),
            base_dir=tmp_path,
        )
        second = store_normalized_artifact(
            db,
            run_id=3,
            source_hash=SOURCE_HASH,
            normalization_params="c" * 32,
            produce_output=_producer(),
            base_dir=tmp_path,
        )

        assert second.dedup_hit is False
        assert db.query(TnImageArtifact).count() == 2

    def test_integrity_error_race_resolves_to_dedup_hit(self, db, tmp_path: Path) -> None:
        winner = TnImageArtifact(
            source_hash=SOURCE_HASH,
            normalization_params=PARAMS_FP,
            output_path="9/5_aaaaaaaaaaaa.jpg",
            output_hash=OUTPUT_HASH,
            created_at=datetime.now(timezone.utc),
        )
        db.add(winner)
        db.commit()

        # Simulate the lost race: the pre-insert lookup misses, so this
        # caller proceeds to INSERT and hits the unique constraint.
        real_find = store_module._find_artifact
        calls = {"n": 0}

        def flaky_find(session, source_hash, normalization_params):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return real_find(session, source_hash, normalization_params)

        with patch("app.services.tn_image_normalizer.store._find_artifact", flaky_find):
            result = store_normalized_artifact(
                db,
                run_id=3,
                source_hash=SOURCE_HASH,
                normalization_params=PARAMS_FP,
                produce_output=_producer(),
                base_dir=tmp_path,
            )

        assert result.state == ITEM_DEDUP_HIT
        assert result.artifact_id == winner.id
        assert db.query(TnImageArtifact).count() == 1


class TestRetentionSweep:
    def _artifact(self, db, created_at: datetime, base_dir: Path, run_id: int, artifact_id: int) -> Path:
        path = base_dir / str(run_id) / f"{artifact_id}_{OUTPUT_HASH[:12]}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(OUTPUT_BYTES)
        db.add(
            TnImageArtifact(
                id=artifact_id,
                source_hash=f"{artifact_id:064d}",
                normalization_params=PARAMS_FP,
                output_path=str(path),
                output_hash=OUTPUT_HASH,
                created_at=created_at,
            )
        )
        db.commit()
        return path

    def test_deletes_only_artifacts_older_than_retention_days(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        old_path = self._artifact(db, now - timedelta(days=31), tmp_path, run_id=1, artifact_id=1)
        fresh_path = self._artifact(db, now - timedelta(days=29), tmp_path, run_id=2, artifact_id=2)

        deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert deleted == 1
        assert not old_path.exists()
        assert fresh_path.exists()
        remaining = [row.id for row in db.query(TnImageArtifact).all()]
        assert remaining == [2]

    def test_now_is_injected_not_read_from_the_clock(self, db, tmp_path: Path) -> None:
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        path = self._artifact(db, created, tmp_path, run_id=1, artifact_id=1)

        # A `now` far in the past must delete nothing, which is only true
        # if the sweep never falls back to the real clock.
        deleted = sweep_expired_artifacts(
            db,
            now=created + timedelta(days=1),
            retention_days=30,
            base_dir=tmp_path,
        )

        assert deleted == 0
        assert path.exists()

    def test_removes_the_emptied_run_directory(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        self._artifact(db, now - timedelta(days=90), tmp_path, run_id=1, artifact_id=1)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert not (tmp_path / "1").exists()

    def test_missing_file_still_removes_the_row(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        path = self._artifact(db, now - timedelta(days=90), tmp_path, run_id=1, artifact_id=1)
        path.unlink()

        deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert deleted == 1
        assert db.query(TnImageArtifact).count() == 0
