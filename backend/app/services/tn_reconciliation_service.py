"""TN Reconciliation Service — stateless verdict computation (Slice 1, read-only).

Joins GBP export report 78 against the locally synced `tienda_nube_productos`
catalog and computes a live verdict per GBP row. No reconciliation fact is
persisted — only human decisions (ban list, mark-for-deletion, resolution)
survive across loads (see design.md "Technical Approach").

Join key: GBP `Código` (EAN) <-> `tienda_nube_productos.variant_sku`.
`tnr_id`/`tnr_variationID` (the ERP's cached TN product/variant ids) are used
ONLY to detect DUPLICADO groupings and to re-verify an already-claimed link
against `product_id`/`variant_id` — never as the primary join key.

Ban-list scope: banning an EAN means "we don't want to publish this", NOT
"hide a broken publication from me". A banned EAN is therefore hidden ONLY
from the publish-candidate verdicts (FALTA_VINCULAR, FALTA_PUBLICAR) and
REMAINS VISIBLE in every data-quality anomaly verdict (MAL_VINCULADO,
MAL_PUBLICADO, DUPLICADO) — banning is never a way to sweep an existing
mis-publication out of the review view.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from app.api.endpoints.gbp_parser import (
    OPERATION_CONFIG,
    authenticate_user,
    call_soap_service,
    parse_soap_response,
)
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.services.tn_publish_core.extract import Absent, ReportFieldError, extract_report_row
from app.services.tn_publish_core.resolve import (
    InvalidReportValueError,
    MissingExchangeRateError,
    resolve_cost,
    resolve_field,
    resolve_gbp_fields,
)
from app.services.tn_publish_core.validate import validate_measurements

logger = logging.getLogger(__name__)

GBP_REPORT_ID_TN_RECONCILE = 78

# Reason/cause taxonomy (Slice 1, additive only) — explains WHY a row landed
# on MAL_PUBLICADO or MAL_VINCULADO, without changing either verdict value.
# Closed set: any future code must be added here explicitly, never inferred.
REASON_DEAD_LINK = "DEAD_LINK"
REASON_SKU_MISMATCH = "SKU_MISMATCH"
REASON_NO_VARIANT_LINK = "NO_VARIANT_LINK"

# `call_soap_service` defaults to `timeout: float = 300.0`, and a "TOKEN
# Expired" retry can double that to ~600s. The `/reporte` endpoint holds a
# checked-out DB connection open for the duration of this await (see
# `tienda_nube_reconcile.py`'s pool-safety note) — inheriting that default
# would let a single slow request hold a connection for up to 10 minutes,
# exactly the pattern behind this repo's documented pool-exhaustion
# incident. This value is a deliberate, explicit bound, not a guess at the
# report's real size; tune it if report 78 legitimately needs longer.
GBP_FETCH_TIMEOUT_SECONDS = 60.0


class GBPFetchError(Exception):
    """Raised when GBP export report 78 cannot be fetched or parsed.

    The caller (endpoint layer) MUST surface this as a clear error to the
    operator and MUST NOT perform any partial write (Graceful Degradation).
    """


@dataclass
class ErpPriceInfo:
    """Bulk-loaded `productos_erp`/`productos_pricing` money-path fields for
    ONE `item_id` (Slice 2 — publish price). Built by the endpoint from a
    single outer-joined query (see `tienda_nube_reconcile.py`'s pool-safety
    note) and passed into `compute_verdicts` as `erp_by_item_id`; this
    function never queries the DB itself (purity constraint).

    Money-path gotcha (design Decision 0): `precio_lista_ml` is a SQL
    `Float` while `precio_web_transferencia` is `Numeric(15, 2)` — both are
    normalized to `Decimal` HERE, at the boundary where they enter this
    dataclass, via `Decimal(str(...))`, so no binary-float representation
    error can propagate further into the pipeline.
    """

    precio_web_transferencia: Optional[Decimal] = None
    participa_web_transferencia: Optional[bool] = None
    precio_lista_ml: Optional[Decimal] = None


@dataclass
class ReconcileRow:
    """One GBP row overlaid with its computed verdict and matched TN rows."""

    ean: str
    verdict: str
    gbp_row: dict
    tn_matches: list = field(default_factory=list)
    despublicar: bool = False
    # Orthogonal to `verdict` — see `_compute_presence`. Composes with any
    # verdict (e.g. DUPLICADO + not_in_tn).
    tn_presence: str = "not_in_tn"
    # Only ever populated for FALTA_VINCULAR rows whose normalized SKU
    # already resolves a TN product/variant via `tn_matches` — null/absent
    # otherwise (never guessed/invented for other verdicts).
    product_id: Optional[int] = None
    variant_id: Optional[int] = None
    # Reason/cause taxonomy (Slice 1) — additive, read-only annotation on
    # top of an already-computed verdict. Populated ONLY when
    # `verdict in {"MAL_PUBLICADO", "MAL_VINCULADO"}` (see
    # `_build_reason_detail`);
    # `None` for every other verdict, never guessed.
    reason: Optional[str] = None
    reason_detail: Optional[dict] = None
    # Slice 4: exposes the already-parsed `_as_optional_int` stock value
    # (previously consumed only internally for the DESPUBLICAR check, then
    # discarded). `None` means "not reported by GBP" and MUST stay `None` —
    # never coerced to `0`, since `0` is exactly the value that raises
    # `despublicar` on the other side of the same field (see
    # `_as_optional_int`'s docstring).
    stock: Optional[int] = None
    # Slice 2 (publish price, money path): additive, read-only annotation
    # sourced from the bulk-loaded `erp_by_item_id` index (see
    # `ErpPriceInfo`). `None` for every field when `erp_by_item_id` is not
    # supplied (default — every existing `compute_verdicts` call site stays
    # valid) or when this row's `Item_ID` doesn't resolve to an ERP/pricing
    # row — NEVER fabricated. `precio_web_transferencia`/`precio_lista_ml`
    # are `Decimal`, never a raw `float`.
    precio_web_transferencia: Optional[Decimal] = None
    participa_web_transferencia: Optional[bool] = None
    precio_lista_ml: Optional[Decimal] = None


# Only these verdicts have a Publicar action in the UI — `build_publish_fields`
# is scoped to them to control response payload growth across the other
# ~800 non-candidate rows in a typical report-78 fetch.
PUBLISH_CANDIDATE_VERDICTS = frozenset({"FALTA_PUBLICAR", "FALTA_VINCULAR"})


def build_publish_fields(row: "ReconcileRow") -> Dict[str, Any]:
    """Strictly extracts + GBP-layer-converts the publish field set for a
    publish-candidate row (PC1/PC2/PC3, `tn_publish_core.extract`/
    `.resolve`), returning endpoint-ready kwargs
    (`marca`/`cost`/`barcode`/`promotional_price`/`weight_kg`/`width_cm`/
    `depth_cm`/`height_cm`). Returns `{}` for any non-candidate verdict, so
    the caller's response model keeps those fields at their `None` default.

    A missing report-78 KEY (e.g. a live ERP column rename — see
    `extract_report_row`'s docstring) or an unparseable VALUE for a KEY
    that IS present (e.g. `weight = "N/A"` — see `resolve.py`'s
    `InvalidReportValueError`) makes extraction/conversion raise loudly
    (S1) at the unit level; both are caught HERE, via their shared
    `ReportFieldError` base, and logged with the offending field and EAN
    so the break stays visible in logs, and only THIS row's new fields
    degrade to `None` rather than a single bad row crashing the whole
    one-shot report for every other row. `Absent` (a value-level "GBP
    reports no data", e.g. a blank dimension) is a completely different,
    expected case already resolved to `None` below — it never reaches this
    `except` clause.

    D13: a `ReportFieldError` (schema break or unparseable value) is a
    DIFFERENT failure class than a genuinely absent measurement, and
    PR-5's D3 blocked-publication gate must be able to tell them apart
    from the API response alone — not only from this warning log. So on
    that path the returned dict also carries `publish_fields_error` (the
    exception message, naming the offending field) instead of a bare
    `{}`, and on the success path it's explicit `None` rather than an
    implicit response-model default, so both branches are equally
    assertable. Junk is NOT absence: an unparseable value must never be
    silently swallowed into the same `None` a real absence produces.
    """
    if row.verdict not in PUBLISH_CANDIDATE_VERDICTS:
        return {}

    try:
        resolved = resolve_gbp_fields(extract_report_row(row.gbp_row))
    except ReportFieldError as exc:
        logger.warning(
            "Report 78 row ean=%s failed publish-field extraction/conversion (field=%r): %s",
            row.ean,
            exc.field_name,
            exc,
        )
        return {"publish_fields_error": str(exc)}

    def _or_none(value: Any) -> Any:
        return None if value is Absent else value

    return {
        "marca": resolved.marca,
        "cost": resolved.coslis_price,
        "barcode": resolved.codigo,
        "promotional_price": _or_none(resolved.promotional_price),
        "weight_kg": _or_none(resolved.weight_kg),
        "width_cm": _or_none(resolved.width_cm),
        "depth_cm": _or_none(resolved.depth_cm),
        "height_cm": _or_none(resolved.height_cm),
        "publish_fields_error": None,
    }


def build_publish_draft(
    row: "ReconcileRow",
    overrides: Dict[str, str],
    usd_rate: Optional[float],
    usd_rate_date: Optional[date] = None,
    suggested_profile_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """PC11/D3 (design Decision 3, task 5.19): the resolved-draft envelope
    for ONE publish-candidate row — `{fields, blocked, blocked_reasons,
    suggested_profile_id, exchange_rate}`. `None` for any non-candidate
    verdict (mirrors `build_publish_fields`'s scoping) and also `None` when
    this row's report-78 extraction/conversion itself failed — that failure
    is already surfaced via `publish_fields_error` (D13); a draft over
    broken data would be misleading, not merely incomplete.

    Per-row containment (same pattern as `build_publish_fields`): this is
    called once per candidate row inside the `/reporte` response loop, and
    ANY failure here (a bad override value, a missing exchange rate) must
    degrade to a blocked/absent field rather than 500 the whole report —
    the caller is expected to wrap this in a broad `except Exception`.

    `overrides` is this row's `{campo: valor}` slice of a bulk
    `tn_publish_override` query (`WHERE ean IN (...)`, loaded ONCE per
    report by the caller — never per row). `usd_rate`/`usd_rate_date` are
    likewise the report-wide value from ONE `latest_usd_rate_with_date(db)`
    call before the row loop (design Decision 3: no per-row `TipoCambio`
    queries — with ~99% of report rows in USD, a per-row lookup multiplies
    into hundreds of queries per `/reporte` on a checked-out pooled
    connection).

    PR-7 gap fix (task B): `exchange_rate` used to be hardcoded `None` —
    "worse than not having it: it looks implemented" (the risk table wants
    the operator to SEE which rate is used and its date). Populated here as
    `{"value": ..., "fecha": ...}` from the SAME bulk-resolved rate, never a
    fresh per-row lookup.

    PR-7 gap fix (task C): `suggested_profile_id` used to be hardcoded
    `None` too. The caller resolves it via the SAME exact-match ->
    category-only -> none ladder as `GET /tn-measurement-profiles/suggestion`
    (`_select_hint_profile_id`), from a bulk-loaded hint map (design
    Decision 3 — never one hint query per row) and hands it in here.
    """
    if row.verdict not in PUBLISH_CANDIDATE_VERDICTS:
        return None

    try:
        extracted = extract_report_row(row.gbp_row)
        resolved_gbp = resolve_gbp_fields(extracted)
    except ReportFieldError:
        return None

    def _override_float(campo: str) -> Any:
        raw = overrides.get(campo)
        if raw is None:
            return Absent
        try:
            return float(raw)
        except (TypeError, ValueError):
            return Absent

    gbp_by_field = {
        "weight": resolved_gbp.weight_kg,
        "width": resolved_gbp.width_cm,
        "depth": resolved_gbp.depth_cm,
        "height": resolved_gbp.height_cm,
    }
    resolved_fields = {
        name: resolve_field(gbp_value=gbp_value, override_value=_override_float(name))
        for name, gbp_value in gbp_by_field.items()
    }
    validation = validate_measurements(resolved_fields)

    exchange_rate: Optional[Dict[str, Any]] = (
        {"value": usd_rate, "fecha": usd_rate_date.isoformat()} if usd_rate is not None and usd_rate_date else None
    )
    cost_block_reason: Optional[str] = None
    try:
        cost_resolved = resolve_cost(resolved_gbp.coslis_price, resolved_gbp.moneda_costo, usd_rate)
    except MissingExchangeRateError:
        # D6/D3: an unresolvable USD cost blocks the field, never
        # publishes an unconverted figure — surfaced here as a blocked
        # `cost` field, not a 500 or a swallowed exception.
        cost_resolved = None
        cost_block_reason = "Falta tipo de cambio para convertir el costo (USD)"
    except InvalidReportValueError as exc:
        # D13: junk is not absence. A non-numeric cost or an unknown
        # `Moneda_Costo` must block THIS field with a reason that names
        # the junk — silently dropping the whole draft (the broad per-row
        # containment upstream) would leave the row with no draft and no
        # signal of why.
        cost_resolved = None
        cost_block_reason = f"Valor de costo inválido en el reporte GBP: {exc}"

    fields: Dict[str, Any] = {
        name: {"value": resolved.value, "source": resolved.source, "editable": True}
        for name, resolved in resolved_fields.items()
    }
    if cost_resolved is not None:
        fields["cost"] = {"value": cost_resolved.value, "source": cost_resolved.source, "editable": True}
    else:
        fields["cost"] = {"value": None, "source": "empty", "editable": True}

    blocked_reasons = list(validation.blocked_reasons)
    if cost_block_reason is not None:
        blocked_reasons.append(cost_block_reason)

    return {
        "fields": fields,
        "blocked": validation.blocked or cost_block_reason is not None,
        "blocked_reasons": blocked_reasons,
        # PR-8 gap fix (defect 1): `blocked`/`blocked_reasons` merge two
        # DIFFERENT classes of block that a consumer must NOT confuse —
        # the D3 measurement gate (operator-fixable IN THIS MODAL, and
        # already live-recomputed client-side as the operator types) vs
        # the D6 cost gate (an unresolvable USD `TipoCambio`, which the
        # operator cannot resolve here at all). Exposing `cost_blocked`
        # as an explicit boolean — rather than making the frontend
        # string-match `blocked_reasons` for the Spanish cost sentence —
        # lets the modal keep enforcing ONLY the block the operator
        # cannot self-resolve, instead of pinning the whole publish
        # button to a snapshot that goes stale the moment a measurement
        # is filled in.
        "cost_blocked": cost_block_reason is not None,
        "cost_block_reason": cost_block_reason,
        "suggested_profile_id": suggested_profile_id,
        "exchange_rate": exchange_rate,
    }


def _select_hint_profile_id(
    hints_by_key: Dict[Any, int], categoria: Optional[str], subcategoria: Optional[str]
) -> Optional[int]:
    """D11/MP3 profile suggestion ladder — EXACTLY the same lookup order as
    `GET /tn-measurement-profiles/suggestion` (`sugerir_perfil`): exact
    `(categoria, subcategoria)` match first, else `(categoria, None)`, else
    no suggestion. `hints_by_key` is a bulk-loaded `{(categoria,
    subcategoria_or_None): profile_id}` map — already reduced to the
    highest-`uso_count` (ties broken by lowest id) winner per key by the
    caller's query ordering, so this function does no further ranking, only
    the ladder walk (pure, easy to test without a DB)."""
    if not categoria:
        return None
    if subcategoria:
        hit = hints_by_key.get((categoria, subcategoria))
        if hit is not None:
            return hit
    return hints_by_key.get((categoria, None))


def _build_reason_detail(
    ean: Optional[str],
    tn_sku_found: Optional[str],
    tnr_id: int,
    tnr_variation_id: int,
) -> dict:
    """Concrete operands for a populated `reason` (R1.3). `tnr_id`/
    `tnr_variationID` of `0` mean "not claimed at all" and are reported as
    `None` rather than the sentinel `0`, matching `_as_int`'s "0 == absent"
    convention used elsewhere in this module for these two fields."""
    return {
        "expected_ean": ean,
        "tn_sku_found": tn_sku_found,
        "claimed_tnr_id": tnr_id or None,
        "claimed_tnr_variation_id": tnr_variation_id or None,
    }


async def fetch_gbp_report_78() -> list[dict]:
    """Fetch GBP export report 78 via the existing `wsExportDataById` operation.

    Reuses `gbp_parser`'s module-level auth/call/parse helpers directly — this
    is the same `OPERATION_CONFIG["wsExportDataById"]` path the `/gbp-parser`
    endpoint already exposes for `intExpgr_id`, so it requires ZERO allow-list
    change (design.md "GBP fetch" decision).
    """
    conf = OPERATION_CONFIG["wsExportDataById"]
    soap_action = conf["soapAction"]
    soap_body = conf["template"].format(intExpgr_id=GBP_REPORT_ID_TN_RECONCILE)

    try:
        token = await authenticate_user()
        xml_content = await call_soap_service(soap_body, soap_action, token, timeout=GBP_FETCH_TIMEOUT_SECONDS)
        if "TOKEN Expired" in xml_content:
            token = await authenticate_user()
            xml_content = await call_soap_service(soap_body, soap_action, token, timeout=GBP_FETCH_TIMEOUT_SECONDS)
        data = parse_soap_response(xml_content)
    except Exception as exc:  # noqa: BLE001 — normalized into a single operator-facing error
        raise GBPFetchError(f"No se pudo obtener el reporte GBP {GBP_REPORT_ID_TN_RECONCILE}: {exc}") from exc

    if not isinstance(data, list):
        raise GBPFetchError(f"Respuesta inesperada del reporte GBP {GBP_REPORT_ID_TN_RECONCILE}")

    return data


def _normalize_sku(value: Optional[str]) -> Optional[str]:
    """Normalize a SKU/EAN for comparison. Empty/null never matches anything."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_gtin(value) -> object:
    """Normalize a GTIN-style value (EAN / TN `variant_sku`) for leading-
    zero-tolerant numeric comparison.

    Strips whitespace and leading zeros so `023942321477` and `23942321477`
    compare equal. The guard is deliberately strict: any value that isn't a
    string of digits after stripping — empty, `None`, all-zero, or
    non-numeric (e.g. `"ABC123"`) — normalizes to a fresh sentinel object
    that is NEVER equal to anything, including another sentinel from this
    same guard (two empty/None/all-zero/non-numeric inputs must never
    collide with each other). A plain `None` return would make
    `None == None` collapse two "no value" rows into a false match, which is
    exactly the failure mode this guards against — so every non-numeric
    input gets its own unique `object()` instead.

    Callers MUST NOT use `==` against a raw string literal without checking
    `isinstance(result, str)` first — the sentinel is intentionally opaque.
    """
    if value is None:
        return object()
    text = str(value).strip()
    if not text.isdigit():
        return object()
    digits = text.lstrip("0")
    if digits == "":
        return object()
    return digits


def _as_int(value, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_optional_int(value) -> Optional[int]:
    """Like `_as_int`, but returns `None` for missing/empty/unparseable
    values instead of collapsing them to a numeric default. Used for
    `stock`, where the DESPUBLICAR check treats `0` as the flag-triggering
    value — coercing "unknown" to `_as_int`'s generic default of `0` would
    silently mean "unknown stock" and "confirmed zero stock" become
    indistinguishable, exactly the failure mode already avoided for
    `published` (see `_is_visible`)."""
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _esta_vivo_en_tn(tn: TiendaNubeProducto) -> bool:
    """Whether this TN product still EXISTS in Tienda Nube.

    `activo` is the EXISTENCE axis, not the visibility one: the sync
    (`endpoints/tienda_nube.py`) sets every row inactive and reactivates
    only what TN's /products endpoint returns, so `activo is False` means
    "TN stopped returning it" — i.e. deleted. Rows are never removed, which
    keeps the audit trail but leaves tombstones in the table (849 of 1809
    rows in production on 2026-08-21).

    Deliberately NOT `published`: a product can be alive in TN and merely
    deactivated (`published=False`), which is a legitimate state that must
    keep matching normally. The two axes are independent — see
    `_is_visible`, which guards the other one.

    Fail-safe like `_is_visible`: only POSITIVE evidence of deletion
    excludes a row. `activo` is nullable, and a NULL means "not known yet"
    (never re-synced), never "deleted" — an unknown must not silently drop
    a real product out of the matching indexes.
    """
    return getattr(tn, "activo", None) is not False


def _is_visible(tn: TiendaNubeProducto) -> bool:
    """Fail-safe check for "actually published/visible in the storefront".

    MUST key off TN's real `published` field, never `activo` — `activo` only
    means "present in the last full sync" and is set true for every product
    the /products endpoint returns, including unpublished/draft ones.
    `published IS None` means the row hasn't been re-synced with the new
    field yet (unknown), and MUST NOT be treated as published — never
    over-claim DESPUBLICAR on unknown data. `stock` gets the same fail-safe
    treatment via `_as_optional_int` (unknown stock is `None`, never `0` —
    see `compute_verdicts`), since `0` is exactly the value that raises this
    flag on the other side of the same `and`.
    """
    return getattr(tn, "published", None) is True


def _compute_presence(tn: Optional[TiendaNubeProducto]) -> str:
    """`tn_presence` per the TN Presence Field requirement: orthogonal to
    `verdict`. `tn` is whichever TN product this row resolved to for
    presence purposes (the claimed link if one exists, else the first
    normalized-EAN match, else `None`) — see `compute_verdicts`."""
    if tn is None:
        return "not_in_tn"
    published = getattr(tn, "published", None)
    if published is True:
        return "published"
    if published is False:
        return "draft"
    return "unknown"


_EMPTY_ERP_PRICE_KWARGS = {
    "precio_web_transferencia": None,
    "participa_web_transferencia": None,
    "precio_lista_ml": None,
}


def _erp_price_fields(row: dict, erp_by_item_id: Optional[dict[int, ErpPriceInfo]]) -> dict:
    """Looks up this GBP row's bulk-loaded ERP/pricing info (Slice 2, keyed
    by `Item_ID`) and returns the three additive money-path fields as
    `ReconcileRow` kwargs. Degrades to all-`None` when `erp_by_item_id` is
    not supplied (keeps every existing `compute_verdicts` call site valid)
    or the row's `Item_ID` doesn't resolve to any loaded ERP row — this
    function never fabricates a price."""
    if not erp_by_item_id:
        return dict(_EMPTY_ERP_PRICE_KWARGS)
    item_id = _as_optional_int(row.get("Item_ID"))
    info = erp_by_item_id.get(item_id) if item_id is not None else None
    if info is None:
        return dict(_EMPTY_ERP_PRICE_KWARGS)
    return {
        "precio_web_transferencia": info.precio_web_transferencia,
        "participa_web_transferencia": info.participa_web_transferencia,
        "precio_lista_ml": info.precio_lista_ml,
    }


def _dedupe_matches(*groups: list[TiendaNubeProducto]) -> list[TiendaNubeProducto]:
    """Union multiple TN-match lists, deduping by `(product_id, variant_id)`
    while preserving first-seen order — used to combine the raw-string index
    with the new GTIN-normalized index without ever double-counting the same
    TN row (e.g. when a match hits both indices)."""
    seen: set[tuple] = set()
    result: list[TiendaNubeProducto] = []
    for group in groups:
        for tn in group:
            key = (tn.product_id, tn.variant_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(tn)
    return result


def compute_verdicts(
    gbp_rows: list[dict],
    tn_productos: list[TiendaNubeProducto],
    banned_eans: Optional[set[str]] = None,
    erp_by_item_id: Optional[dict[int, ErpPriceInfo]] = None,
) -> list[ReconcileRow]:
    """Compute the verdict taxonomy for each GBP row.

    Verdicts: FALTA_VINCULAR, FALTA_PUBLICAR, MAL_VINCULADO, DUPLICADO,
    MAL_PUBLICADO, POR_CORREGIR (linked, but the claimed TN SKU differs from
    the GBP EAN only by leading zeros/formatting — surfaced for a human to
    canonicalize, never auto-corrected), OK (fully matched — not an anomaly,
    not returned as an action item but kept so `despublicar` can still be
    surfaced).

    Each row also carries `tn_presence` (`published`/`draft`/`unknown`/
    `not_in_tn`), orthogonal to `verdict` — see `_compute_presence`.

    DUPLICADO is a human-review anomaly only — this function never picks a
    "correct" row/variant among duplicates. It reports every conflicting row
    with full context (`tn_matches`) for the operator to judge.

    `banned_eans` ONLY suppresses the publish-candidate verdicts
    (FALTA_VINCULAR, FALTA_PUBLICAR) — a banned EAN that resolves to
    MAL_VINCULADO, MAL_PUBLICADO, or DUPLICADO is still returned. Banning
    means "don't offer this as something to publish", not "hide a broken
    publication from review".
    """
    banned_eans = banned_eans or set()

    # Index TN products by normalized variant_sku (EAN-join). A null/empty
    # sku is never indexed, so it can never match any EAN (Verdict Edge Cases).
    #
    # Only products still ALIVE in TN are indexed here (`_esta_vivo_en_tn`):
    # these two indexes are what PROPOSES a link, and proposing a link to a
    # deleted product is exactly the FALTA_VINCULAR-against-nothing bug
    # operators kept hitting. Note this filters on deletion, never on
    # visibility — a deactivated-but-alive product is still a valid
    # candidate.
    tn_by_sku: dict[str, list[TiendaNubeProducto]] = {}
    for tn in tn_productos:
        if not _esta_vivo_en_tn(tn):
            continue
        sku = _normalize_sku(tn.variant_sku)
        if sku is None:
            continue
        tn_by_sku.setdefault(sku, []).append(tn)

    # Second index keyed by the leading-zero-tolerant numeric GTIN value
    # (SKU/EAN Matching Normalization requirement) — kept SEPARATE from
    # `tn_by_sku` above rather than replacing it: `tn_by_sku` still matches
    # non-numeric SKUs by raw string (preserving all existing exact-match
    # behavior), while this index additionally links GBP EANs to TN SKUs
    # that differ only by leading zeros. `normalize_gtin`'s sentinel guard
    # means non-numeric/empty/None/all-zero SKUs are simply never indexed
    # here (they'd never collide with another sentinel anyway).
    tn_by_gtin: dict[str, list[TiendaNubeProducto]] = {}
    for tn in tn_productos:
        # Same alive-only rule as `tn_by_sku` above — both indexes feed
        # `matches_by_ean`, so filtering only one would just move the bug.
        if not _esta_vivo_en_tn(tn):
            continue
        gtin = normalize_gtin(tn.variant_sku)
        if not isinstance(gtin, str):
            continue
        tn_by_gtin.setdefault(gtin, []).append(tn)

    # Index TN products by (product_id, variant_id) — used only to re-verify
    # an already-claimed link (tnr_id/tnr_variationID), never as the join key.
    #
    # DELIBERATELY UNFILTERED, unlike the two indexes above: a GBP row whose
    # claimed link points at a product TN deleted must still resolve here,
    # or the broken link would silently read as "never linked" instead of
    # surfacing for review. Proposing a dead product is the bug; recognising
    # one you are already linked to is the feature.
    tn_by_ids: dict[tuple, TiendaNubeProducto] = {}
    for tn in tn_productos:
        tn_by_ids[(tn.product_id, tn.variant_id)] = tn

    # Detect DUPLICADO groups: two or more GBP rows sharing the same
    # (tnr_id, tnr_variationID) pair. Requires BOTH ids resolved
    # (tnr_variationID > 0) — rows with an unresolved variant belong to
    # MAL_VINCULADO, not DUPLICADO. Without this guard, two MAL_VINCULADO
    # rows sharing one tnr_id would both key on (tnr_id, 0) and get masked
    # as a false DUPLICADO, hiding the real anomaly.
    dup_groups: dict[tuple, list[int]] = {}
    for idx, row in enumerate(gbp_rows):
        tnr_id = _as_int(row.get("tnr_id"))
        tnr_variation_id = _as_int(row.get("tnr_variationID"))
        if tnr_id > 0 and tnr_variation_id > 0:
            dup_groups.setdefault((tnr_id, tnr_variation_id), []).append(idx)

    duplicated_indices = {idx for indices in dup_groups.values() if len(indices) > 1 for idx in indices}

    results: list[ReconcileRow] = []
    for idx, row in enumerate(gbp_rows):
        ean = _normalize_sku(row.get("Código"))
        tnr_id = _as_int(row.get("tnr_id"))
        tnr_variation_id = _as_int(row.get("tnr_variationID"))
        # Unknown stock (missing/empty/unparseable) MUST be None, never 0 —
        # 0 is exactly the value that raises DESPUBLICAR (round 7, item 2).
        #
        # `Stock_Disponible` (not a plain `stock` key — verified against a
        # LIVE report-78 response on 2026-07-30) is Stock_Físico minus
        # Pendientes: what can actually be sold, which is the deliberate
        # choice here over Stock_Físico. Values arrive as decimal strings
        # (e.g. "9.0000"); `_as_optional_int` already handles that via
        # `int(float(...))`.
        stock = _as_optional_int(row.get("Stock_Disponible"))

        # Slice 2 (publish price): additive money-path fields looked up from
        # the bulk-loaded `erp_by_item_id` index, keyed by this row's
        # `Item_ID` — see `_erp_price_fields`'s docstring. All-`None` when
        # `erp_by_item_id` is absent or the id doesn't resolve.
        erp_price_kwargs = _erp_price_fields(row, erp_by_item_id)

        # Raw-string matches (unchanged, exact-match behavior — e.g. still
        # matches non-numeric SKUs) unioned with leading-zero-tolerant GTIN
        # matches (SKU/EAN Matching Normalization requirement). Union, not
        # replacement, so existing raw-match test scenarios keep behaving
        # identically while numeric leading-zero variants are additionally
        # linked.
        ean_gtin = normalize_gtin(row.get("Código"))
        matches_by_ean = _dedupe_matches(
            tn_by_sku.get(ean, []) if ean else [],
            tn_by_gtin.get(ean_gtin, []) if isinstance(ean_gtin, str) else [],
        )

        despublicar = any(_is_visible(tn) and stock == 0 for tn in matches_by_ean)

        if idx in duplicated_indices:
            # DUPLICADO grouping is keyed on the shared (tnr_id,
            # tnr_variationID) link, not this row's own EAN — a duplicated
            # row's EAN may legitimately not match (e.g. a per-color split
            # where each GBP row has its own EAN but shares one TN
            # variant). Fall back to the claimed link for presence so this
            # branch doesn't under-report existence.
            presence_tn = matches_by_ean[0] if matches_by_ean else tn_by_ids.get((tnr_id, tnr_variation_id))
            results.append(
                ReconcileRow(
                    ean=ean or "",
                    verdict="DUPLICADO",
                    gbp_row=row,
                    tn_matches=matches_by_ean,
                    despublicar=despublicar,
                    stock=stock,
                    **erp_price_kwargs,
                    tn_presence=_compute_presence(presence_tn),
                )
            )
            continue

        if len(matches_by_ean) > 1:
            # Multiple TN variants share the same EAN — never silently
            # resolved to one arbitrary variant (Verdict Edge Cases).
            results.append(
                ReconcileRow(
                    ean=ean or "",
                    verdict="DUPLICADO",
                    gbp_row=row,
                    tn_matches=matches_by_ean,
                    despublicar=despublicar,
                    stock=stock,
                    **erp_price_kwargs,
                    tn_presence=_compute_presence(matches_by_ean[0]),
                )
            )
            continue

        if tnr_id == 0:
            verdict = "FALTA_VINCULAR" if matches_by_ean else "FALTA_PUBLICAR"
            if ean and ean in banned_eans:
                # Banning only means "don't offer this as something to
                # publish" — it hides the publish-candidate verdicts
                # (FALTA_VINCULAR/FALTA_PUBLICAR) exclusively. It must NEVER
                # hide a data-quality anomaly (see the banned_eans docstring
                # below and the module-level ban-scope note).
                continue
            # FALTA_VINCULAR Exposes Matched TN IDs requirement: only
            # populated when this row's normalized SKU already resolved a
            # TN product/variant — null/absent for FALTA_PUBLICAR (nothing
            # resolved) and for any FALTA_VINCULAR row with no match.
            matched_tn = matches_by_ean[0] if (verdict == "FALTA_VINCULAR" and matches_by_ean) else None
            results.append(
                ReconcileRow(
                    ean=ean or "",
                    verdict=verdict,
                    gbp_row=row,
                    tn_matches=matches_by_ean,
                    despublicar=despublicar,
                    stock=stock,
                    **erp_price_kwargs,
                    tn_presence=_compute_presence(matches_by_ean[0] if matches_by_ean else None),
                    product_id=matched_tn.product_id if matched_tn else None,
                    variant_id=matched_tn.variant_id if matched_tn else None,
                )
            )
            continue

        if tnr_variation_id == 0:
            # NO_VARIANT_LINK: `tnr_id` resolved but no `tnr_variationID` at
            # all — there is no resolvable variant-level claim to verify.
            results.append(
                ReconcileRow(
                    ean=ean or "",
                    verdict="MAL_VINCULADO",
                    gbp_row=row,
                    tn_matches=matches_by_ean,
                    despublicar=despublicar,
                    stock=stock,
                    **erp_price_kwargs,
                    tn_presence=_compute_presence(matches_by_ean[0] if matches_by_ean else None),
                    reason=REASON_NO_VARIANT_LINK,
                    reason_detail=_build_reason_detail(
                        ean,
                        _normalize_sku(matches_by_ean[0].variant_sku) if matches_by_ean else None,
                        tnr_id,
                        tnr_variation_id,
                    ),
                )
            )
            continue

        # tnr_id and tnr_variationID both resolved: verify the claimed link.
        claimed_tn = tn_by_ids.get((tnr_id, tnr_variation_id))
        claimed_despublicar = bool(claimed_tn and _is_visible(claimed_tn) and stock == 0)

        # POR_CORREGIR Verdict requirement: raw-equal -> OK (unchanged);
        # no match under ANY normalization -> MAL_PUBLICADO (unchanged
        # verdict, unchanged reasons); raw differs but numeric-GTIN equal
        # -> POR_CORREGIR (new — same underlying product, SKU just needs
        # canonicalizing). Order matters: check raw-equal BEFORE the
        # normalized check so an exact match never gets demoted.
        #
        # Dead-link fallback: when the stored tnr_id/tnr_variationID link
        # doesn't resolve to any TN row (`claimed_tn is None`), that stale
        # link must NOT by itself imply MAL_PUBLICADO — it only means the
        # ERP's cached pointer is wrong. Fall back to the EAN/GTIN match
        # (`matches_by_ean`, already deduped to at most one entry by the
        # len>1 DUPLICADO check above) to decide the real verdict: a
        # correctly-SKU'd published match is OK, a leading-zero-only match
        # is POR_CORREGIR, and truly nothing matching is the only case that
        # stays MAL_PUBLICADO.
        fallback_tn = matches_by_ean[0] if (claimed_tn is None and matches_by_ean) else None
        effective_tn = claimed_tn if claimed_tn is not None else fallback_tn
        effective_sku_raw = _normalize_sku(effective_tn.variant_sku) if effective_tn else None
        if effective_tn is not None and effective_sku_raw == ean:
            verdict = "OK"
        elif (
            effective_tn is not None
            and isinstance(normalize_gtin(effective_tn.variant_sku), str)
            and normalize_gtin(effective_tn.variant_sku) == ean_gtin
        ):
            verdict = "POR_CORREGIR"
        else:
            verdict = "MAL_PUBLICADO"

        # Presence resolution priority: the claimed link (even if it's the
        # WRONG SKU — MAL_PUBLICADO still means the product genuinely
        # exists in TN, just misattributed) takes precedence over the
        # separate EAN-index matches used elsewhere; when the claimed link
        # is dead, fall back to the same EAN/GTIN match used for the verdict
        # above so a resolved fallback isn't under-reported as not_in_tn.
        presence_tn = claimed_tn if claimed_tn is not None else fallback_tn

        # DEAD_LINK vs SKU_MISMATCH (R1.2): both are additive annotations on
        # MAL_PUBLICADO only — `verdict` itself is unchanged either way.
        # `claimed_tn is None` here means neither the claimed link NOR the
        # EAN/GTIN fallback resolved anything (a resolving fallback would
        # already have produced OK/POR_CORREGIR above) — that is DEAD_LINK.
        # `claimed_tn is not None` means the claimed TN row genuinely exists
        # but its SKU doesn't match the GBP EAN under any normalization —
        # that is SKU_MISMATCH.
        reason = None
        reason_detail = None
        if verdict == "MAL_PUBLICADO":
            reason = REASON_DEAD_LINK if claimed_tn is None else REASON_SKU_MISMATCH
            reason_detail = _build_reason_detail(
                ean,
                _normalize_sku(claimed_tn.variant_sku) if claimed_tn else None,
                tnr_id,
                tnr_variation_id,
            )

        results.append(
            ReconcileRow(
                ean=ean or "",
                verdict=verdict,
                gbp_row=row,
                tn_matches=[claimed_tn] if claimed_tn else (matches_by_ean if fallback_tn else []),
                despublicar=claimed_despublicar or despublicar,
                stock=stock,
                **erp_price_kwargs,
                tn_presence=_compute_presence(presence_tn),
                reason=reason,
                reason_detail=reason_detail,
            )
        )

    return results
