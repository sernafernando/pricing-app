"""Strict extraction from a GBP report-78 row (PC1/S1, design.md Decision 1).

`parse_soap_response` (`app/api/endpoints/gbp_parser.py:300`) is
schema-less: it returns whatever key/value pairs the SOAP response happens
to contain for a row. A live ERP column rename (`higth` -> `height`,
observed mid-investigation on 2026-08-14 — see engram
`discovery/gbp-report-78-columns`) silently produces rows missing the
renamed key. Any consumer that does `row.get("height", 0)` would then
publish garbage dimensions without ever knowing the source column
disappeared.

This module refuses that failure mode: `extract_report_row` raises
`MissingReportFieldError`, naming the missing key, for every REQUIRED
field this publisher depends on (`REQUIRED_REPORT_FIELDS`). It never
defaults a missing required KEY to 0/None/"". A separate, smaller set of
fields (`OPTIONAL_REPORT_FIELDS`) may have their KEY entirely absent
without raising — see that tuple's definition for why.

Separately, some fields are legitimately ABSENT at the VALUE level even
when the KEY is present — e.g. `weight = "0.000000000"` means "GBP has no
weight for this item", not "this item weighs zero grams". That is
represented by the `Absent` sentinel, which is neither `None` (never
assigned) nor `0`/`""` (a real reported value), so "GBP is silent" and "GBP
says zero" can never collapse into the same falsy value.
"""

from dataclasses import dataclass
from typing import Any, Optional


class ReportFieldError(Exception):
    """Common base for report-78 row extraction/conversion failures.

    Lets callers like `build_publish_fields` catch ONE type instead of a
    growing tuple, while still distinguishing the two failure classes via
    the concrete subclass: `MissingReportFieldError` (a required KEY is
    absent from the row entirely) vs `InvalidReportValueError`
    (`resolve.py` — the KEY is present but its VALUE cannot be coerced to
    the expected type, e.g. non-numeric junk like `"N/A"` in a measurement
    field). Both subclasses expose `field_name`."""


class MissingReportFieldError(ReportFieldError, KeyError):
    """Raised when a report-78 row is missing a key this publisher depends
    on. A `KeyError` subclass so existing `except KeyError` handling (if
    any) still catches it, but `str(...)` names the exact missing column
    instead of a bare key repr."""

    def __init__(self, field_name: str):
        super().__init__(f"Report 78 row is missing required field {field_name!r}")
        self.field_name = field_name


class _AbsentType:
    """Sentinel for "GBP reports no value for this field" — distinct from
    both `None` (never assigned by this module) and `0`/`""` (a real
    reported value). A single shared instance (`Absent`, below) is used
    everywhere; always compare with `is`, never `==`."""

    _instance: "Optional[_AbsentType]" = None

    def __new__(cls) -> "_AbsentType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "Absent"

    def __bool__(self) -> bool:
        return False


Absent = _AbsentType()

# Keys this publisher reads from a report-78 row. A row missing ANY of
# these entirely (not just carrying a blank value) raises — see the module
# docstring. Order matches the inventory in engram
# discovery/gbp-report-78-columns (#1515) / the tn-publish-core spec.
REQUIRED_REPORT_FIELDS: tuple[str, ...] = (
    "weight",
    "wide",
    "large",
    "height",
    "Marca",
    "Stock_Disponible",
    "coslis_price",
    "iclh_price",
    "Moneda_Costo",
    "Código",
)

# Keys that may be entirely absent from a report-78 row WITHOUT raising —
# unlike REQUIRED_REPORT_FIELDS, a missing key here is meaningful data, not
# a schema break, and degrades to `Absent` exactly like a present-but-blank
# value.
#
# `tnr_lastPromotionalPrice` is a Tienda Nube field, not a GBP/ERP field:
# GBP only emits the tag once an item has been published on TN at least
# once, and omits it entirely (not blank — absent) otherwise. A live probe
# of the real report-78 (2026-08-18, 1131 rows, 74 distinct key-sets)
# measured this key present on only 70.4% of rows overall — and on the 335
# rows that are actual publish candidates (no `tnr_id`, i.e. never
# published on TN), it was present on 0 of 335 (0.0%). Treating it as
# required would flag 100% of publish candidates as
# `publish_fields_error`, making the publish flow dead on arrival for
# every item it is meant to serve. See engram
# sdd/tn-publisher-module/apply-progress for the measured evidence.
OPTIONAL_REPORT_FIELDS: tuple[str, ...] = ("tnr_lastPromotionalPrice",)

# Measurement-class + promotional_price fields: GBP reports "0.000000000"
# (or blank) for "no data", never a real zero-sized product / zero-priced
# promo (design.md Decision 1, "Absent vs zero" table).
_ABSENT_CLASS_FIELDS = frozenset({"weight", "wide", "large", "height", "tnr_lastPromotionalPrice"})


def _is_absent_value(raw: Any) -> bool:
    """True when a present KEY still carries GBP's "no data" convention:
    blank, or a numeric zero. Non-numeric non-blank values (unexpected, but
    not this function's job to validate further) are treated as present."""
    if raw is None:
        return True
    text = str(raw).strip()
    if text == "":
        return True
    try:
        return float(text) == 0.0
    except ValueError:
        return False


@dataclass(frozen=True)
class ExtractedReportRow:
    """Strict, typed projection of one report-78 row. Every attribute here
    is guaranteed to have been read from a KEY that was actually present in
    the source row — see `extract_report_row`. Measurement fields and
    `promotional_price` are `Absent` (never `0`/`""`) when GBP reports no
    data for them; every other field is the raw string GBP sent."""

    marca: str
    stock_disponible: str
    coslis_price: str
    iclh_price: str
    moneda_costo: str
    codigo: str
    promotional_price: Any  # str, or Absent
    weight_grams: Any  # str, or Absent
    wide_cm: Any  # str, or Absent
    large_cm: Any  # str, or Absent
    height_cm: Any  # str, or Absent


def extract_report_row(gbp_row: dict) -> ExtractedReportRow:
    """Strictly project the fields this publisher needs from one report-78
    row.

    Raises `MissingReportFieldError`, naming the missing key, if ANY
    required key (`REQUIRED_REPORT_FIELDS`) is absent from `gbp_row` —
    never defaults to 0/None/"" (PC1/S1). A key listed in
    `OPTIONAL_REPORT_FIELDS` (currently `tnr_lastPromotionalPrice`) may be
    entirely absent without raising; like a present-but-blank measurement
    or promo-price value, it becomes `Absent` (see the module docstring).
    """
    for key in REQUIRED_REPORT_FIELDS:
        if key not in gbp_row:
            raise MissingReportFieldError(key)

    def _value(key: str) -> Any:
        if key not in gbp_row:
            # Only reachable for OPTIONAL_REPORT_FIELDS — required keys
            # already raised above.
            return Absent
        raw = gbp_row[key]
        if key in _ABSENT_CLASS_FIELDS and _is_absent_value(raw):
            return Absent
        return raw

    return ExtractedReportRow(
        marca=gbp_row["Marca"],
        stock_disponible=gbp_row["Stock_Disponible"],
        coslis_price=gbp_row["coslis_price"],
        iclh_price=gbp_row["iclh_price"],
        moneda_costo=gbp_row["Moneda_Costo"],
        codigo=gbp_row["Código"],
        promotional_price=_value("tnr_lastPromotionalPrice"),
        weight_grams=_value("weight"),
        wide_cm=_value("wide"),
        large_cm=_value("large"),
        height_cm=_value("height"),
    )
