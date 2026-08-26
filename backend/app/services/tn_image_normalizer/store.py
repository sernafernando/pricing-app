"""Tienda Nube image normalizer — artifact store (slice 5).

Owns the two things the pure stages deliberately cannot do: putting a
normalized image on disk, and deciding whether it had to be produced at
all.

DEDUP IS THE POINT
------------------
The lookup key is `(source_hash, normalization_params)`, backed by
`uq_tn_img_artifact_dedup`. A hit short-circuits BEFORE the producer
callable runs, so a repeated image is never re-decoded, never re-encoded,
and never re-written — the expensive work is passed in lazily precisely
so it can be skipped. Two concurrent workers can still both miss the
lookup; the loser catches `IntegrityError`, rolls back, re-reads the row
the winner committed, and reports a `dedup_hit` like everyone else. The
constraint is the arbiter, never a check-then-insert in Python.

DISK LAYOUT
-----------
`{TN_IMG_NORMALIZER_DIR}/{run_id}/{artifact_id}_{output_hash[:12]}.jpg`

The artifact id makes the name unique; the hash prefix makes a wrong or
stale file visible by inspection. Writes mirror
`compras_adjuntos_service`: `mkdir(parents=True, exist_ok=True)` then
`open(..., "wb")` inside `try/except OSError`.

TRANSACTION BOUNDARY
--------------------
`store_normalized_artifact` never commits or rolls back the caller's
session; it isolates its own insert in a SAVEPOINT and lets the caller
commit the whole unit of work. See that function's docstring.

RETENTION
---------
`now` is a required parameter, never `datetime.utcnow()` read inside. A
sweep that reads the clock itself cannot be tested without freezing time,
and a retention bug is only ever noticed once the files are already gone.

ORPHAN FILES
------------
Because the write is committed by a SAVEPOINT while the row is committed by
the caller, a caller that rolls its outer transaction back leaves the file
on disk with no row pointing at it. Nothing that walks the rows can ever
reclaim it, so the sweep also walks the DISK and deletes any `.jpg` no row
references.

Deleting a file is irreversible, so the sweep is deliberately timid about
it. A file whose directory belongs to a run that has not finished is never
touched — that run's transaction is still open and its rows have not
committed, so the file is live work, however old its mtime is.
`ORPHAN_GRACE_PERIOD` remains only as a fallback for a directory that maps
to no known run. And if more than `MAX_ORPHAN_FRACTION` of the scanned files
match no row, the sweep reclaims nothing at all: at that point the path
comparison is what is broken, and acting on it would wipe the store. The
degenerate case of that reading — files on disk and NO row carrying an
`output_path` at all — is treated the same way and logged as an error,
because a half-restored database is indistinguishable from a fresh install
from here, and only one of the two can be harmed by guessing wrong.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tn_image_normalizer import (
    TnImageArtifact,
    TnImageNormalizationItem,
    TnImageNormalizationRun,
)
from app.services.tn_image_normalizer.states import ITEM_DEDUP_HIT, ITEM_NORMALIZED

logger = logging.getLogger(__name__)

HASH_PREFIX_LENGTH = 12
OUTPUT_SUFFIX = ".jpg"

# Rows are removed with `DELETE ... WHERE id IN (...)` in chunks this size.
# 500 keeps the parameter list far below the drivers' bind-parameter ceiling
# (psycopg tops out at 65535) and the statement small enough to plan cheaply,
# while turning a 30-day backlog of several thousand artifacts into a handful
# of round-trips instead of one per row.
DELETE_BATCH_SIZE = 500

# Fallback only, for a file whose directory maps to no known run (a leftover
# from a deleted run header, or something a human dropped there). The primary
# in-flight signal is the run's own state, NOT this clock: a run over
# thousands of images keeps its transaction open for hours, so any fixed
# grace period is guaranteed to be too short for a big enough run.
ORPHAN_GRACE_PERIOD = timedelta(hours=1)

# Circuit breaker for the orphan sweep. If artifact rows with paths DO exist
# and yet more than this fraction of the files on disk matches none of them,
# the comparison is what is broken — a real sweep reclaims a small minority.
# Deleting is irreversible and would leave every row pointing at nothing, so
# above this fraction the sweep reclaims NOTHING and shouts instead. 0.9 sits
# far above any plausible real backlog and far below the ~1.0 a broken
# comparison produces.
MAX_ORPHAN_FRACTION = 0.9


@dataclass(frozen=True)
class NormalizedOutput:
    """The engine's product: encoded bytes plus their final dimensions."""

    content: bytes
    width: int
    height: int


@dataclass(frozen=True)
class StoredArtifact:
    """Where an artifact lives, and whether this call had to create it."""

    artifact_id: int
    output_path: str
    state: str
    dedup_hit: bool


def _base_dir(base_dir: Path | str | None) -> Path:
    return Path(base_dir) if base_dir is not None else Path(settings.TN_IMG_NORMALIZER_DIR)


def artifact_output_path(
    run_id: int,
    artifact_id: int,
    output_hash: str,
    base_dir: Path | str | None = None,
) -> Path:
    """Build the canonical on-disk path for one artifact."""
    return _base_dir(base_dir) / str(run_id) / f"{artifact_id}_{output_hash[:HASH_PREFIX_LENGTH]}{OUTPUT_SUFFIX}"


def _find_artifact(db: Session, source_hash: str, normalization_params: str) -> TnImageArtifact | None:
    return (
        db.query(TnImageArtifact)
        .filter(
            TnImageArtifact.source_hash == source_hash,
            TnImageArtifact.normalization_params == normalization_params,
        )
        .first()
    )


def _as_dedup_hit(artifact: TnImageArtifact) -> StoredArtifact:
    return StoredArtifact(
        artifact_id=artifact.id,
        output_path=artifact.output_path or "",
        state=ITEM_DEDUP_HIT,
        dedup_hit=True,
    )


def _write_bytes(path: Path, content: bytes) -> bool:
    """Write `content` to `path`, creating parents. False on any OSError."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
    except OSError as exc:
        logger.exception("tn_image_normalizer.store: could not write %s: %s", path, exc)
        # A half-written file must not survive. The retry gets a fresh
        # artifact id and therefore a different path, so it would never
        # overwrite this one: it would sit there forever, the size of a real
        # artifact and referenced by nothing.
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("tn_image_normalizer.store: could not clean up partial write %s", path)
        return False
    return True


def store_normalized_artifact(
    db: Session,
    run_id: int,
    source_hash: str,
    normalization_params: str,
    produce_output: Callable[[], NormalizedOutput],
    base_dir: Path | str | None = None,
) -> StoredArtifact | None:
    """Return the artifact for `(source_hash, normalization_params)`.

    `produce_output` is called only on a genuine miss — a dedup hit never
    re-normalizes and never touches the disk. Returns `None` when the
    output could not be written, leaving no artifact row behind so a later
    run retries cleanly instead of inheriting a row that points at nothing.

    TRANSACTION OWNERSHIP
    ---------------------
    The session belongs to the caller, so this function neither commits nor
    rolls it back. Per ADR-4 every stage is "claim → work → record" inside
    the caller's own short transaction; committing here would publish
    whatever else the caller had in flight (typically the item state update
    that belongs with this artifact) at a moment the caller did not choose,
    and splitting the pair across two commits is precisely how an item ends
    up recorded as normalized with no artifact, or the reverse. The caller
    commits once, when the whole unit of work is done.

    The artifact insert is wrapped in a SAVEPOINT so that undoing it on an
    integrity conflict or a failed write undoes *only* it. Any work the
    caller already had pending is flushed before the savepoint opens, which
    keeps it outside the rollback's blast radius.
    """
    existing = _find_artifact(db, source_hash, normalization_params)
    if existing is not None:
        return _as_dedup_hit(existing)

    output = produce_output()
    output_hash = hashlib.sha256(output.content).hexdigest()

    artifact = TnImageArtifact(
        source_hash=source_hash,
        normalization_params=normalization_params,
        output_hash=output_hash,
        output_bytes=len(output.content),
        width=output.width,
        height=output.height,
    )
    # Flush the caller's pending work first: it must land outside the
    # savepoint, or rolling the savepoint back would silently take it too.
    db.flush()

    savepoint = db.begin_nested()
    db.add(artifact)
    try:
        db.flush()
    except IntegrityError:
        # Lost the race against a concurrent worker: the constraint, not a
        # prior SELECT, is what decides who owns this artifact.
        savepoint.rollback()
        winner = _find_artifact(db, source_hash, normalization_params)
        if winner is not None:
            return _as_dedup_hit(winner)
        logger.error(
            "tn_image_normalizer.store: dedup conflict with no winner row (source_hash=%s)",
            source_hash,
        )
        return None

    path = artifact_output_path(run_id, artifact.id, output_hash, base_dir=base_dir)
    if not _write_bytes(path, output.content):
        savepoint.rollback()
        return None

    artifact.output_path = str(path)
    db.flush()
    savepoint.commit()

    return StoredArtifact(
        artifact_id=artifact.id,
        output_path=str(path),
        state=ITEM_NORMALIZED,
        dedup_hit=False,
    )


def _absolute(output_path: str, root: Path) -> Path:
    path = Path(output_path)
    return path if path.is_absolute() else root / path


def _canonical(path: Path) -> str:
    """The path as a string both sides of the orphan comparison can agree on.

    The row's path was built from the `base_dir` of the WRITE; the sweep
    walks the `base_dir` of the SWEEP. A symlinked mount, a relative path or
    a trailing slash between the two makes the raw strings differ while the
    file is the very same one — and a raw-string comparison then declares the
    ENTIRE store orphaned. `resolve()` collapses all of that; if the file is
    gone or the path cannot be resolved, the absolute form is still stable
    enough to compare.
    """
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _unfinished_run_dirs(db: Session, root: Path) -> set[str]:
    """Canonical directories belonging to runs that have not finished.

    Read in ONE query, like the known-path set: a query per file would defeat
    the point of scanning in memory.

    `finished_at` is the terminality signal because the run-level state
    vocabulary does not exist yet — `states.py` deliberately carries only the
    ITEM_* and TXN_* machines and warns that they must not be mixed, so
    judging a run by either would be a category error, and inventing RUN_*
    strings here would prejudge a later slice. `finished_at IS NULL` means
    exactly "this run has not ended", which is the question being asked.
    """
    run_ids = (
        db.execute(select(TnImageNormalizationRun.id).where(TnImageNormalizationRun.finished_at.is_(None)))
        .scalars()
        .all()
    )
    return {_canonical(root / str(run_id)) for run_id in run_ids}


def _known_run_dirs(db: Session, root: Path) -> set[str]:
    """Canonical directories of every run we know about, finished or not."""
    run_ids = db.execute(select(TnImageNormalizationRun.id)).scalars().all()
    return {_canonical(root / str(run_id)) for run_id in run_ids}


def _orphan_files(db: Session, root: Path, now: datetime, already_doomed: set[str]) -> list[Path]:
    """Files under `root` that no artifact row references and are safe to drop.

    The set of known paths is read ONCE and compared in memory: a query per
    file would turn a routine sweep over a few thousand images into a few
    thousand round-trips, which is the cost this whole function exists to
    keep bounded.

    A file is spared when its directory belongs to a run that has not
    finished. The layout is `{base_dir}/{run_id}/...`, so the parent IS the
    run id, and an unfinished run is precisely the case where the file is
    already written but its row has not committed yet — deleting it destroys
    live work and leaves the run "successful" with rows pointing at nothing.

    `already_doomed` holds the canonical paths this very sweep has just
    decided to unlink. Their rows are gone (committed) while their files are
    not yet, so they would otherwise count as orphans and inflate the
    fraction against themselves: after a large backlog the breaker would trip
    on the sweep's own work and reclaim nothing at all. They are already
    accounted for, so they take part in neither side of the ratio.
    """
    if not root.is_dir():
        return []

    known = {
        _canonical(_absolute(output_path, root))
        for (output_path,) in db.execute(
            select(TnImageArtifact.output_path).where(TnImageArtifact.output_path.is_not(None))
        ).all()
        if output_path
    }
    unfinished_dirs = _unfinished_run_dirs(db, root)
    known_dirs = _known_run_dirs(db, root)
    # Compared as POSIX timestamps rather than datetimes: `st_mtime` has no
    # timezone, and `now` may arrive aware or naive.
    grace_cutoff = now.timestamp() - ORPHAN_GRACE_PERIOD.total_seconds()

    scanned = 0
    orphans: list[Path] = []
    for path in root.rglob(f"*{OUTPUT_SUFFIX}"):
        canonical = _canonical(path)
        if canonical in already_doomed:
            continue
        scanned += 1
        if canonical in known:
            continue
        parent = _canonical(path.parent)
        if parent in unfinished_dirs:
            # Its run is still going: the row simply has not committed yet.
            continue
        if parent not in known_dirs:
            try:
                if path.stat().st_mtime >= grace_cutoff:
                    # No run to ask, so fall back to the clock.
                    continue
            except OSError as exc:
                logger.warning("tn_image_normalizer.store: could not stat %s: %s", path, exc)
                continue
        orphans.append(path)

    if scanned and not known:
        # Not "nothing to compare against": something to compare against that
        # is MISSING. A half-restored database and a truncated table both look
        # exactly like this, and from here they are indistinguishable from a
        # fresh install — so the sweep takes the reading that cannot destroy
        # anything. A genuinely new install has nothing to reclaim anyway.
        logger.error(
            "tn_image_normalizer.store: refusing to reclaim any of %s scanned files as orphans; "
            "no artifact row carries an output_path, so the store looks emptied rather than swept",
            scanned,
        )
        return []

    if known and scanned and len(orphans) / scanned > MAX_ORPHAN_FRACTION:
        logger.error(
            "tn_image_normalizer.store: refusing to reclaim %s of %s scanned files as orphans "
            "(above %s); path comparison is almost certainly broken",
            len(orphans),
            scanned,
            MAX_ORPHAN_FRACTION,
        )
        return []

    for path in orphans:
        logger.info("tn_image_normalizer.store: reclaiming orphan file %s", path)
    return orphans


def _expired_at(now: datetime, retention_days: int) -> datetime:
    return now - timedelta(days=retention_days)


def sweep_expired_artifacts(
    db: Session,
    now: datetime,
    retention_days: int | None = None,
    base_dir: Path | str | None = None,
) -> int:
    """Delete artifacts (file + row) created before the retention cutoff.

    TRANSACTION OWNERSHIP: unlike `store_normalized_artifact`, which works
    inside a savepoint and leaves the commit to its caller, this function
    OWNS its transaction and commits. It is a standalone retention job, not
    a step inside someone else's unit of work — do not call it with pending
    changes on the session, because the commit here would publish them.

    `now` is injected on purpose — see this module's docstring. Returns the
    number of artifact rows removed. A file that is already gone still has
    its row removed: the row is the thing that would otherwise point at
    nothing forever.
    """
    days = retention_days if retention_days is not None else settings.TN_IMG_RETENTION_DAYS
    cutoff = _expired_at(now, days)
    root = _base_dir(base_dir)

    # An artifact some item still points at is NOT expendable. Deleting one
    # raises ForeignKeyViolation and takes the whole sweep down with it,
    # including the genuinely orphaned artifacts it was meant to reclaim.
    # Dedup also means one artifact serves many runs, so being referenced is
    # the NORMAL case: the busiest artifact is the oldest one, and filtering
    # on age alone would target it first.
    referenced = select(TnImageNormalizationItem.artifact_id).where(TnImageNormalizationItem.artifact_id.is_not(None))
    expired = db.execute(
        select(TnImageArtifact.id, TnImageArtifact.output_path)
        .where(TnImageArtifact.created_at < cutoff)
        .where(TnImageArtifact.id.not_in(referenced))
    ).all()

    # Resolve the paths first, delete the ROWS, commit, and only then unlink.
    # The unlink is irreversible: doing it before the commit means a failed
    # commit leaves rows pointing at files that are already gone — the exact
    # dangling state this function exists to prevent. An orphan file merely
    # costs disk until the next sweep.
    expired_ids = [row.id for row in expired]
    touched_paths = [_absolute(row.output_path, root) for row in expired if row.output_path]

    try:
        for offset in range(0, len(expired_ids), DELETE_BATCH_SIZE):
            batch = expired_ids[offset : offset + DELETE_BATCH_SIZE]
            db.query(TnImageArtifact).filter(TnImageArtifact.id.in_(batch)).delete(synchronize_session=False)
        db.commit()
    except SQLAlchemyError:
        # Owning the transaction includes undoing it: a failed commit must
        # not hand the caller a session with these deletes still pending.
        db.rollback()
        raise

    # The paths above are already doomed: their rows are committed away but
    # their files are still on disk, so the orphan scan must not count them.
    doomed = {_canonical(path) for path in touched_paths}
    touched_paths.extend(_orphan_files(db, root, now, doomed))

    touched_dirs: set[Path] = set()
    for path in touched_paths:
        touched_dirs.add(path.parent)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("tn_image_normalizer.store: could not delete %s: %s", path, exc)

    for directory in touched_dirs:
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError as exc:
            logger.warning("tn_image_normalizer.store: could not remove empty dir %s: %s", directory, exc)

    return len(expired_ids)
