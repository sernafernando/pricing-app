"""D3 measurement gate + MP4 profile co-shipping proof (PC6).

`validate_measurements` blocks a publish, NAMING every missing measurement
field (not just the first), whenever weight or any dimension resolves
`empty` with no override/GBP/profile value to fall back to. The same item
unblocks the moment a measurement profile supplies all four fields — this
is a structural property of `resolve_field`'s precedence, not special-cased
here: `validate.py` only ever looks at the already-`Resolved` values.
"""

from dataclasses import dataclass
from typing import Dict, List

from app.services.tn_publish_core.resolve import Resolved

# The four fields `tn_publish_core.assemble` writes onto the TN variant —
# see design.md's "Absent vs zero" table: a zero-dimension physical product
# does not exist, so these can never legitimately resolve to `None`.
MEASUREMENT_FIELDS: tuple = ("weight", "width", "depth", "height")

# The operator-overridable field names accepted by `PublicarRequest.overrides`
# and persisted by `tn_publish_service._upsert_publish_overrides`. Today this
# is exactly the measurement set — `cost` is computed (D6), never overridden.
# Both the request validator (422 on unknown keys) and the persistence layer
# (defense-in-depth filter) validate against THIS tuple; grow it here, in one
# place, when a new field becomes editable.
OVERRIDABLE_FIELDS: tuple = MEASUREMENT_FIELDS

_FIELD_LABELS = {
    "weight": "peso",
    "width": "ancho",
    "depth": "profundidad",
    "height": "alto",
}


@dataclass(frozen=True)
class ValidationResult:
    blocked: bool
    blocked_reasons: List[str]


def validate_measurements(resolved_fields: Dict[str, Resolved]) -> ValidationResult:
    """`resolved_fields` must carry a `Resolved` for each of
    `MEASUREMENT_FIELDS` (a missing key is treated the same as an `empty`
    resolution, never defaulted to "present")."""
    missing = [
        field_name
        for field_name in MEASUREMENT_FIELDS
        if resolved_fields.get(field_name, Resolved(None, "empty")).value is None
    ]
    if not missing:
        return ValidationResult(blocked=False, blocked_reasons=[])
    reasons = [f"Falta {_FIELD_LABELS[field_name]} ({field_name})" for field_name in missing]
    return ValidationResult(blocked=True, blocked_reasons=reasons)
