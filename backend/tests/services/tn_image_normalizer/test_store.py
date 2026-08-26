"""Tests for tn_image_normalizer.store: dedup, disk layout, and retention.

Runs against a real in-memory SQLite session carrying every table
reachable by foreign key from the normalizer's own, with
`PRAGMA foreign_keys=ON`. Both halves matter: the dedup unique constraint
and the item -> artifact foreign key are genuinely enforced, so the race
test exercises a real database error and the retention sweep is judged
against the same constraints Postgres applies.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.tn_image_normalizer.store as store_module
from app.core.database import Base
from app.models.usuario import Usuario
from app.models.tn_image_normalizer import (
    TnImageArtifact,
    TnImageNormalizationItem,
    TnImageNormalizationRun,
)
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


def _reachable_tables(*roots) -> list:
    """Every table the given tables depend on, transitively, via foreign keys."""
    seen: set = set()
    stack = list(roots)
    while stack:
        table = stack.pop()
        if table in seen:
            continue
        seen.add(table)
        for foreign_key in table.foreign_keys:
            stack.append(foreign_key.column.table)
    return list(seen)


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(type_, compiler, **kw) -> str:
    """Let the run table build on SQLite so the item FK can exist in tests.

    The run header stores its totals in JSONB, which SQLite cannot compile.
    That is why the fixture used to create the artifact table alone — and
    creating it alone is what hid the FK bug this file now covers.
    """
    return "JSON"


@pytest.fixture()
def db():
    """A session whose schema carries the REAL constraints.

    Creating only `tn_image_artifact` used to hide the FK from
    `tn_image_normalization_item.artifact_id`, so a sweep that deletes a
    referenced artifact passed here and would have raised
    ForeignKeyViolation against Postgres. SQLite also ignores foreign keys
    unless the pragma is on, so both halves are needed for the test to run
    in the same universe as production.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Every table reachable by FK from ours, computed rather than hand-listed:
    # a hand-picked subset is exactly how the item -> artifact FK went missing
    # here in the first place, and it would silently go missing again the next
    # time a column is added.
    Base.metadata.create_all(
        engine,
        tables=_reachable_tables(
            TnImageArtifact.__table__,
            TnImageNormalizationRun.__table__,
            TnImageNormalizationItem.__table__,
        ),
    )
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


def _stored_artifact(db, created_at: datetime, base_dir: Path, run_id: int, artifact_id: int) -> Path:
    """Persist one artifact row with its file already on disk. Returns the path."""
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


class TestRetentionSweep:
    def test_deletes_only_artifacts_older_than_retention_days(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        old_path = _stored_artifact(db, now - timedelta(days=31), tmp_path, run_id=1, artifact_id=1)
        fresh_path = _stored_artifact(db, now - timedelta(days=29), tmp_path, run_id=2, artifact_id=2)

        deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert deleted == 1
        assert not old_path.exists()
        assert fresh_path.exists()
        remaining = [row.id for row in db.query(TnImageArtifact).all()]
        assert remaining == [2]

    def test_now_is_injected_not_read_from_the_clock(self, db, tmp_path: Path) -> None:
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        path = _stored_artifact(db, created, tmp_path, run_id=1, artifact_id=1)

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
        _stored_artifact(db, now - timedelta(days=90), tmp_path, run_id=1, artifact_id=1)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert not (tmp_path / "1").exists()

    def test_missing_file_still_removes_the_row(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        path = _stored_artifact(db, now - timedelta(days=90), tmp_path, run_id=1, artifact_id=1)
        path.unlink()

        deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert deleted == 1
        assert db.query(TnImageArtifact).count() == 0


class TestCallerTransactionIsolation:
    """The store owns its own work only — never the caller's transaction."""

    def _caller_pending_row(self, db) -> TnImageArtifact:
        """Stand-in for the item-state update a caller has in flight."""
        pending = TnImageArtifact(
            source_hash="d" * 64,
            normalization_params=PARAMS_FP,
            output_path="caller/pending.jpg",
            output_hash=OUTPUT_HASH,
            created_at=datetime.now(timezone.utc),
        )
        db.add(pending)
        return pending

    def test_write_failure_does_not_discard_the_callers_pending_work(self, db, tmp_path: Path) -> None:
        self._caller_pending_row(db)

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
        # The artifact row is gone, the caller's row survived.
        assert db.query(TnImageArtifact).filter_by(source_hash=SOURCE_HASH).count() == 0
        assert db.query(TnImageArtifact).filter_by(source_hash="d" * 64).count() == 1

    def test_dedup_race_does_not_discard_the_callers_pending_work(self, db, tmp_path: Path) -> None:
        winner = TnImageArtifact(
            source_hash=SOURCE_HASH,
            normalization_params=PARAMS_FP,
            output_path="9/5_aaaaaaaaaaaa.jpg",
            output_hash=OUTPUT_HASH,
            created_at=datetime.now(timezone.utc),
        )
        db.add(winner)
        db.commit()

        self._caller_pending_row(db)

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
        assert db.query(TnImageArtifact).filter_by(source_hash="d" * 64).count() == 1

    def test_store_never_commits_the_callers_session(self, db, tmp_path: Path) -> None:
        with patch.object(db, "commit", side_effect=AssertionError("store must not commit")):
            result = store_normalized_artifact(
                db,
                run_id=3,
                source_hash=SOURCE_HASH,
                normalization_params=PARAMS_FP,
                produce_output=_producer(),
                base_dir=tmp_path,
            )

        assert result.state == ITEM_NORMALIZED


class TestSweepDeletesFilesOnlyAfterCommit:
    """The row is the record; the file is the payload.

    An orphan file costs disk. A row pointing at a file that no longer
    exists is the exact dangling state this module's docstring says it
    prevents, so the irreversible unlink must never run before the commit
    that makes the deletion durable.
    """

    def test_files_survive_when_the_commit_fails(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        old_path = _stored_artifact(db, now - timedelta(days=31), tmp_path, run_id=1, artifact_id=1)
        assert old_path.exists()

        with patch.object(db, "commit", side_effect=SQLAlchemyError("commit blew up")):
            with pytest.raises(SQLAlchemyError):
                sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        # The deletion never became durable, so the payload must still be there.
        assert old_path.exists()


class TestPartialWriteLeavesNoOrphan:
    """A failed write must not leave a truncated file behind.

    The retry gets a fresh artifact id, so it writes to a DIFFERENT path and
    never overwrites the truncated one — it would sit there forever, sized
    like a real artifact and referenced by nothing.
    """

    def test_truncated_file_is_removed_when_the_write_fails(self, db, tmp_path: Path) -> None:
        real_open = open

        def _fail_midway(path, mode="r", *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            if "w" in mode:
                handle.write(b"partial")
                handle.close()
                raise OSError("No space left on device")
            return handle

        with patch("app.services.tn_image_normalizer.store.open", _fail_midway, create=True):
            result = store_normalized_artifact(
                db,
                run_id=1,
                source_hash="a" * 64,
                normalization_params=PARAMS_FP,
                produce_output=_producer(),
                base_dir=tmp_path,
            )

        assert result is None
        leftovers = [p for p in tmp_path.rglob("*.jpg")]
        assert leftovers == [], f"truncated file left behind: {leftovers}"


class TestSweepNeverBreaksReferencedArtifacts:
    """An artifact an item still points at is NOT expendable.

    Deleting one raises ForeignKeyViolation on Postgres and takes the whole
    sweep down with it — including the genuinely orphaned artifacts it was
    supposed to reclaim. And because dedup means one artifact serves many
    runs, being referenced is the NORMAL case, not an edge case.
    """

    def _run_with_item(self, db, artifact_id: int, run_id: int) -> None:
        if db.query(Usuario).filter_by(id=1).first() is None:
            db.add(Usuario(id=1, nombre="sweep-test"))
            db.flush()
        db.add(
            TnImageNormalizationRun(
                id=run_id,
                state="planned",
                params_fingerprint=PARAMS_FP,
                created_by_user_id=1,
                preset=1080,
                fill_color="#ffffff",
                output_format="jpeg",
                quality=85,
                max_output_bytes=3145728,
            )
        )
        db.flush()
        db.add(
            TnImageNormalizationItem(
                run_id=run_id,
                ean="7790001234567",
                source_slot=1,
                source_url="https://example.com/a.jpg",
                artifact_id=artifact_id,
                state=ITEM_NORMALIZED,
            )
        )
        db.commit()

    def test_referenced_artifact_survives_the_sweep(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        path = _stored_artifact(db, now - timedelta(days=31), tmp_path, run_id=1, artifact_id=1)
        self._run_with_item(db, artifact_id=1, run_id=1)

        deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert deleted == 0
        assert path.exists()
        assert db.query(TnImageArtifact).filter_by(id=1).first() is not None

    def test_orphans_are_still_reclaimed_alongside_a_referenced_one(self, db, tmp_path: Path) -> None:
        # The failure mode this guards: one referenced artifact used to abort
        # the whole sweep, so the genuine orphans were never reclaimed either.
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        kept = _stored_artifact(db, now - timedelta(days=31), tmp_path, run_id=1, artifact_id=1)
        orphan = _stored_artifact(db, now - timedelta(days=31), tmp_path, run_id=2, artifact_id=2)
        self._run_with_item(db, artifact_id=1, run_id=1)

        deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert deleted == 1
        assert kept.exists()
        assert not orphan.exists()


class TestSweepLeavesNoDirtySession:
    """Owning a transaction includes undoing it.

    Without a rollback, a failed commit hands the caller a session with the
    deletes still pending — it will only fail again, and the caller has no
    way to know why.
    """

    def test_failed_commit_rolls_the_session_back(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        _stored_artifact(db, now - timedelta(days=31), tmp_path, run_id=1, artifact_id=1)

        with patch.object(db, "commit", side_effect=SQLAlchemyError("commit blew up")):
            with pytest.raises(SQLAlchemyError):
                sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert not db.deleted, "pending deletes survived a failed commit"
        assert db.query(TnImageArtifact).filter_by(id=1).first() is not None


def _age_file(path: Path, now: datetime, seconds: int) -> None:
    """Backdate `path`'s mtime to `seconds` before `now`."""
    stamp = now.timestamp() - seconds
    os.utime(path, (stamp, stamp))


class TestOrphanFileReclaim:
    """A file no row points at is reclaimed — nothing else ever would.

    `store_normalized_artifact` writes the file and commits only its own
    SAVEPOINT; if the caller then rolls its outer transaction back, the row
    vanishes and the file stays. A sweep that only unlinks files it found a
    row for can never reclaim that file, so it accumulates forever.
    """

    def test_unreferenced_file_older_than_the_grace_period_is_deleted(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        orphan = tmp_path / "7" / f"99_{OUTPUT_HASH[:12]}.jpg"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(OUTPUT_BYTES)
        _age_file(orphan, now, seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert not orphan.exists()

    def test_file_written_seconds_ago_is_not_an_orphan(self, db, tmp_path: Path) -> None:
        # A run whose transaction is still in flight has already written its
        # file; its row simply has not committed yet. Deleting it would
        # destroy live work.
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        in_flight = tmp_path / "8" / f"100_{OUTPUT_HASH[:12]}.jpg"
        in_flight.parent.mkdir(parents=True, exist_ok=True)
        in_flight.write_bytes(OUTPUT_BYTES)
        _age_file(in_flight, now, seconds=5)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert in_flight.exists()

    def test_referenced_file_within_retention_is_never_touched(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        kept = _stored_artifact(db, now - timedelta(days=1), tmp_path, run_id=1, artifact_id=1)
        _age_file(kept, now, seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60)

        deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert deleted == 0
        assert kept.exists()

    def test_orphan_removal_empties_and_removes_its_directory(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        orphan = tmp_path / "9" / f"101_{OUTPUT_HASH[:12]}.jpg"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(OUTPUT_BYTES)
        _age_file(orphan, now, seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert not (tmp_path / "9").exists()

    def test_scan_does_not_issue_one_query_per_file(self, db, tmp_path: Path) -> None:
        # The known-path set must be read ONCE. A query per file turns a
        # routine sweep over a few thousand images into a few thousand
        # round-trips.
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

        def _sweep_with(file_count: int, run_id: int) -> int:
            for index in range(file_count):
                orphan = tmp_path / str(run_id) / f"{index}_{OUTPUT_HASH[:12]}.jpg"
                orphan.parent.mkdir(parents=True, exist_ok=True)
                orphan.write_bytes(OUTPUT_BYTES)
                _age_file(orphan, now, seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60)
            statements: list[str] = []

            @event.listens_for(db.get_bind(), "before_cursor_execute")
            def _record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            try:
                sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)
            finally:
                event.remove(db.get_bind(), "before_cursor_execute", _record)
            return len(statements)

        assert _sweep_with(2, run_id=20) == _sweep_with(40, run_id=21)


class TestSweepDeletesInBatches:
    """Thousands of expired rows must not cost thousands of round-trips."""

    def test_rows_are_deleted_in_batches_not_one_by_one(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        for artifact_id in range(1, 6):
            _stored_artifact(db, now - timedelta(days=31), tmp_path, run_id=artifact_id, artifact_id=artifact_id)

        deletes: list[str] = []

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def _record(conn, cursor, statement, parameters, context, executemany):
            if statement.strip().upper().startswith("DELETE"):
                deletes.append(statement)

        try:
            with patch.object(store_module, "DELETE_BATCH_SIZE", 2):
                deleted = sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _record)

        assert deleted == 5
        # 5 rows at a batch size of 2 is three statements, not five.
        assert len(deletes) == 3
        assert db.query(TnImageArtifact).count() == 0


def _run_row(db, run_id: int, finished_at: datetime | None) -> None:
    """Persist one run header, finished or still in flight."""
    if db.query(Usuario).filter_by(id=1).first() is None:
        db.add(Usuario(id=1, nombre="sweep-test"))
        db.flush()
    db.add(
        TnImageNormalizationRun(
            id=run_id,
            state="planned",
            params_fingerprint=PARAMS_FP,
            created_by_user_id=1,
            preset=1080,
            fill_color="#ffffff",
            output_format="jpeg",
            quality=85,
            max_output_bytes=3145728,
            finished_at=finished_at,
        )
    )
    db.commit()


def _loose_file(base_dir: Path, run_id: int, artifact_id: int, now: datetime, age_seconds: int) -> Path:
    """Write a file with no artifact row behind it, backdated by `age_seconds`."""
    path = base_dir / str(run_id) / f"{artifact_id}_{OUTPUT_HASH[:12]}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(OUTPUT_BYTES)
    _age_file(path, now, seconds=age_seconds)
    return path


class TestOrphanDetectionComparesResolvedPaths:
    """A cosmetic path difference must never turn the whole store into orphans.

    The row's path was written with the `base_dir` of the WRITE; the sweep
    walks the `base_dir` of the SWEEP. A symlink, a relative path or a
    trailing slash between the two used to make every single file miss the
    known set — so the sweep deleted the entire store and left every row
    pointing at nothing.
    """

    def test_path_written_through_a_symlinked_base_dir_is_not_an_orphan(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        old_enough = int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60
        # Companions written through the plain base_dir, so the run's paths do
        # NOT all mismatch at once: this test must fail on the raw-string
        # comparison alone, not be rescued by the fraction circuit breaker.
        for artifact_id in range(2, 12):
            companion = _stored_artifact(db, now - timedelta(days=1), real, run_id=1, artifact_id=artifact_id)
            _age_file(companion, now, seconds=old_enough)
        path = _stored_artifact(db, now - timedelta(days=1), link, run_id=1, artifact_id=1)
        _age_file(path, now, seconds=old_enough)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=real)

        assert path.exists(), "a symlinked base_dir made a live artifact look orphaned"

    def test_relative_output_path_is_not_an_orphan(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        path = _stored_artifact(db, now - timedelta(days=1), tmp_path, run_id=1, artifact_id=1)
        _age_file(path, now, seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60)
        artifact = db.query(TnImageArtifact).filter_by(id=1).one()
        artifact.output_path = str(path.relative_to(tmp_path))
        db.commit()

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert path.exists(), "a relative row path made a live artifact look orphaned"

    def test_trailing_slash_on_the_sweep_base_dir_is_not_an_orphan(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        path = _stored_artifact(db, now - timedelta(days=1), tmp_path, run_id=1, artifact_id=1)
        _age_file(path, now, seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=f"{tmp_path}{os.sep}")

        assert path.exists(), "a trailing slash made a live artifact look orphaned"


class TestOrphanSweepRefusesImplausibleReclaims:
    """A sweep that believes almost everything is an orphan is broken, not busy.

    The deletion is irreversible, so the fraction is a circuit breaker: when
    rows DO exist and almost nothing on disk matches them, the comparison is
    what failed, and deleting nothing costs one sweep.
    """

    def test_nothing_is_deleted_when_almost_every_file_looks_orphaned(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        old = int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60
        known = _stored_artifact(db, now - timedelta(days=1), tmp_path, run_id=1, artifact_id=1)
        _age_file(known, now, seconds=old)
        loose = [_loose_file(tmp_path, run_id=50, artifact_id=index, now=now, age_seconds=old) for index in range(20)]

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert known.exists()
        assert all(path.exists() for path in loose), "an implausible orphan fraction was acted on"


class TestOrphanSweepNeverTouchesLiveRuns:
    """The grace period is a clock heuristic; the run state is the real signal.

    `store_normalized_artifact` writes its file inside a savepoint and leaves
    the COMMIT to the caller, which commits once the whole run is done. A run
    over thousands of images therefore has hour-old files whose rows have not
    committed yet — and the gap only grows with the run.
    """

    def test_file_of_an_unfinished_run_survives_however_old_it_is(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        _run_row(db, run_id=31, finished_at=None)
        in_flight = _loose_file(tmp_path, run_id=31, artifact_id=1, now=now, age_seconds=90 * 86400)

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert in_flight.exists(), "the sweep destroyed live work from a run still in flight"

    def test_file_of_a_finished_run_is_reclaimed(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        _run_row(db, run_id=32, finished_at=now - timedelta(days=2))
        stale = _loose_file(
            tmp_path,
            run_id=32,
            artifact_id=1,
            now=now,
            age_seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60,
        )

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert not stale.exists()

    def test_directory_of_no_known_run_falls_back_to_the_grace_period(self, db, tmp_path: Path) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        fresh = _loose_file(tmp_path, run_id=33, artifact_id=1, now=now, age_seconds=5)
        old = _loose_file(
            tmp_path,
            run_id=34,
            artifact_id=1,
            now=now,
            age_seconds=int(store_module.ORPHAN_GRACE_PERIOD.total_seconds()) + 60,
        )

        sweep_expired_artifacts(db, now=now, retention_days=30, base_dir=tmp_path)

        assert fresh.exists()
        assert not old.exists()
