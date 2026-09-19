"""OC-match package. Phase 2: MIME + enqueue/reclaim. Gemini stays unwired."""

from app.services.oc_match.enqueue import (
    EnqueueResult,
    claim_queued_job,
    delete_jobs_for_attachment,
    enqueue_oc_match,
    process_oc_match_job,
    queue_retry,
    reclaim_stale_running,
)
from app.services.oc_match.mime import KIND_GEMINI, KIND_OFFICE, KIND_UNKNOWN, classify

__all__ = [
    "KIND_GEMINI",
    "KIND_OFFICE",
    "KIND_UNKNOWN",
    "EnqueueResult",
    "claim_queued_job",
    "classify",
    "delete_jobs_for_attachment",
    "enqueue_oc_match",
    "process_oc_match_job",
    "queue_retry",
    "reclaim_stale_running",
]
