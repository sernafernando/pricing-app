"""The single vocabulary of pipeline states.

Every stage module imports from here. It exists because the alternative —
each stage defining its own string constants — produces a failure that no
test catches: two modules that must agree on `"upload_inconclusive"` drift
apart, and the mismatch surfaces as a row that silently never advances,
not as a red test.

Two distinct state machines live here and must not be mixed:

- ITEM_* : one (EAN, image slot) row in `tn_image_normalization_item`.
- TXN_*  : one product's push transaction, which is NOT persisted per-row
  and governs the delete gate.

THE DELETE GATE
---------------
Exactly ONE transition may ever issue a DELETE against Tienda Nube:
`TXN_ALL_CONFIRMED -> TXN_DELETING`. Everything else — partial
confirmation, inconclusive verification, a failed baseline read — writes
nothing and leaves the product holding its original images.

`ITEM_UPLOAD_ABSENT` deliberately funnels into `TXN_PARTIAL`, not into a
delete-eligible state: proving an upload is absent proves the upload
failed, not that the old images are expendable.

`*_INCONCLUSIVE` is a first-class state, never a flavour of "failed" and
never a flavour of "passed". A timeout, an ambiguous write, a 429, or a
list call that never stabilised all land here, and none of them authorise
a delete. Collapsing inconclusive into either neighbour is how a product
ends up with zero images.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Item states — one (EAN, image slot) row.
# --------------------------------------------------------------------------

ITEM_PENDING = "pending"
ITEM_DOWNLOADING = "downloading"
ITEM_DOWNLOADED = "downloaded"
ITEM_DOWNLOAD_FAILED = "download_failed"
ITEM_DEDUP_HIT = "dedup_hit"
ITEM_NORMALIZING = "normalizing"
ITEM_NORMALIZED = "normalized"
ITEM_NORMALIZE_FAILED = "normalize_failed"
ITEM_TOO_LARGE = "too_large"
ITEM_PUSH_QUEUED = "push_queued"
ITEM_UPLOADING = "uploading"

# Definitive 4xx from TN: nothing was created.
ITEM_UPLOAD_REJECTED = "upload_rejected"
# 2xx and the claimed id was observed in a stable listing.
ITEM_UPLOAD_CONFIRMED = "upload_confirmed"
# 2xx with a definitive claimed id, listing provably stable, id still
# missing. Proves the upload failed — never that a delete is safe.
ITEM_UPLOAD_ABSENT = "upload_absent"
# Ambiguous create, 2xx without a parseable id, exhausted rate-limit
# budget, or a listing that never stabilised. Carries its own
# `inconclusive_reason` column; never authorises a delete.
ITEM_UPLOAD_INCONCLUSIVE = "upload_inconclusive"

# A matched product whose report row carried no usable image slot. A
# reviewable outcome, deliberately not a silent drop.
ITEM_NO_SOURCE_IMAGES = "no_source_images"

# States from which an item still has work to do.
ITEM_STATES_OPEN = frozenset(
    {
        ITEM_PENDING,
        ITEM_DOWNLOADING,
        ITEM_DOWNLOADED,
        ITEM_DEDUP_HIT,
        ITEM_NORMALIZING,
        ITEM_NORMALIZED,
        ITEM_PUSH_QUEUED,
        ITEM_UPLOADING,
    }
)

# States an operator must look at: a failure, or an outcome the pipeline
# refuses to decide on its own.
ITEM_STATES_REVIEWABLE = frozenset(
    {
        ITEM_DOWNLOAD_FAILED,
        ITEM_NORMALIZE_FAILED,
        ITEM_TOO_LARGE,
        ITEM_UPLOAD_REJECTED,
        ITEM_UPLOAD_ABSENT,
        ITEM_UPLOAD_INCONCLUSIVE,
        ITEM_NO_SOURCE_IMAGES,
    }
)

# --------------------------------------------------------------------------
# Product transaction states — one product's push.
# --------------------------------------------------------------------------

TXN_PLANNED = "planned"
# The pre-existing TN image id set was read successfully. Without it no
# delete could ever be scoped, so uploading before this is forbidden.
TXN_BASELINE_CAPTURED = "baseline_captured"
TXN_UPLOADING = "uploading"
TXN_VERIFYING = "verifying"

# All N uploads mapped to confirmed new ids. The ONLY delete-eligible state.
TXN_ALL_CONFIRMED = "all_confirmed"
# k < N confirmed. Product keeps old + new: redundant, never empty.
TXN_PARTIAL = "partial"
# At least one inconclusive item, or a listing that never stabilised.
TXN_INCONCLUSIVE = "inconclusive"

TXN_DELETING = "deleting"
TXN_COMPLETED = "completed"
# Some deletes did not confirm: the product keeps extra images. Never zero.
TXN_DELETE_PARTIAL = "delete_partial"

TXN_ABANDONED_PARTIAL = "abandoned_partial"
TXN_ABANDONED_INCONCLUSIVE = "abandoned_inconclusive"
# The pre-upload listing failed. Nothing was uploaded; we never upload blind.
TXN_ABORTED_NO_BASELINE = "aborted_no_baseline"

# The delete gate, expressed as data so it cannot be re-derived by hand at
# a call site. Membership in this set is the ONLY thing that authorises a
# delete, and it has exactly one member on purpose.
TXN_STATES_DELETE_ELIGIBLE = frozenset({TXN_ALL_CONFIRMED})

# Terminal states that wrote nothing to Tienda Nube.
TXN_STATES_WROTE_NOTHING = frozenset(
    {
        TXN_ABANDONED_PARTIAL,
        TXN_ABANDONED_INCONCLUSIVE,
        TXN_ABORTED_NO_BASELINE,
    }
)
