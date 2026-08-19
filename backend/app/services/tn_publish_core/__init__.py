"""Framework-agnostic publish pipeline: extract -> resolve -> validate -> assemble -> batch.

See `openspec/changes/tn-publisher-module/design.md` Decision 1. PR-3
shipped `extract`/`resolve` (GBP-layer unit/dimension conversion, PC2/PC3).
PR-5 adds precedence resolution (`resolve_field`, `resolve_cost`), the D3
measurement gate (`validate`), v1 payload assembly (`assemble`), and the
429-aware batch executor (`batch`) — no FastAPI/React object appears
anywhere on this call path (PC11/D7).
"""

from app.services.tn_publish_core.assemble import assemble_payload
from app.services.tn_publish_core.batch import ItemOutcome, execute_batch
from app.services.tn_publish_core.extract import Absent, ExtractedReportRow, extract_report_row
from app.services.tn_publish_core.resolve import (
    Resolved,
    ResolvedGbpFields,
    latest_usd_rate,
    resolve_cost,
    resolve_field,
    resolve_gbp_fields,
)
from app.services.tn_publish_core.validate import (
    OVERRIDABLE_FIELDS,
    ValidationResult,
    validate_measurements,
)

__all__ = [
    "Absent",
    "ExtractedReportRow",
    "extract_report_row",
    "Resolved",
    "ResolvedGbpFields",
    "latest_usd_rate",
    "resolve_cost",
    "resolve_field",
    "resolve_gbp_fields",
    "OVERRIDABLE_FIELDS",
    "ValidationResult",
    "validate_measurements",
    "assemble_payload",
    "ItemOutcome",
    "execute_batch",
]
