"""Envio repair policy (read vs write).

Persisted on snapshots for observability; only a subset is written back to ML.
Sample MLA905437269 informed the original brief but is NOT fetched at runtime.
"""

from __future__ import annotations

from typing import Any, Final

# Read-only signals (persist/log only — never PUT these in envio repair).
FLEX_TAG: Final[str] = "self_service_in"
MANDATORY_FREE_SHIPPING_TAG: Final[str] = "mandatory_free_shipping"

LOGISTIC_FULL: Final[str] = "fulfillment"
LOGISTIC_COLECTA: Final[str] = "cross_docking"
LOGISTIC_FLEX: Final[str] = "self_service"
LOGISTIC_PLACES: Final[str] = "xd_drop_off"

# Do not replace these logistic_type values with cross_docking.
LOGISTIC_LEAVE_ALONE: Final[frozenset[str]] = frozenset(
    {
        LOGISTIC_FULL,
        LOGISTIC_COLECTA,
        LOGISTIC_FLEX,
        LOGISTIC_PLACES,
    }
)

MODE_ME2: Final[str] = "me2"

# Snapshot fields we may persist from ML (documentation / drift visibility).
ENVIO_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "mode",
    "logistic_type",
    "local_pick_up",
    "free_shipping",
    "store_pick_up",
    "tags",
)

# Legacy name kept for imports; NOT the write payload.
ENVIO_TARGET: dict[str, Any] = {
    "mode": MODE_ME2,
    "logistic_type": LOGISTIC_COLECTA,
    "local_pick_up": True,
    "free_shipping": True,
    "store_pick_up": False,
    "tags": [FLEX_TAG, MANDATORY_FREE_SHIPPING_TAG],
}

ENVIO_TARGET_TAGS: tuple[str, ...] = (FLEX_TAG, MANDATORY_FREE_SHIPPING_TAG)
