"""Target shipping constants for envio repair.

Captured once from MLA905437269; that MLA is NOT queried at runtime.
"""

from __future__ import annotations

from typing import Any

# Ordered tags for stable JSON "after" payloads; compare as a set.
ENVIO_TARGET_TAGS: tuple[str, ...] = ("self_service_in", "mandatory_free_shipping")

ENVIO_TARGET: dict[str, Any] = {
    "mode": "me2",
    "logistic_type": "cross_docking",
    "local_pick_up": True,
    "free_shipping": True,
    "store_pick_up": False,
    "tags": list(ENVIO_TARGET_TAGS),
}
