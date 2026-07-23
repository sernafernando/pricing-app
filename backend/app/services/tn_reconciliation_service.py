"""TN Reconciliation Service — stateless verdict computation (Slice 1, read-only).

Joins GBP export report 78 against the locally synced `tienda_nube_productos`
catalog and computes a live verdict per GBP row. No reconciliation fact is
persisted — only human decisions (ban list, mark-for-deletion, resolution)
survive across loads (see design.md "Technical Approach").

Join key: GBP `Código` (EAN) <-> `tienda_nube_productos.variant_sku`.
`tnr_id`/`tnr_variationID` (the ERP's cached TN product/variant ids) are used
ONLY to detect DUPLICADO groupings and to re-verify an already-claimed link
against `product_id`/`variant_id` — never as the primary join key.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.api.endpoints.gbp_parser import (
    OPERATION_CONFIG,
    authenticate_user,
    call_soap_service,
    parse_soap_response,
)
from app.models.tienda_nube_producto import TiendaNubeProducto

GBP_REPORT_ID_TN_RECONCILE = 78


class GBPFetchError(Exception):
    """Raised when GBP export report 78 cannot be fetched or parsed.

    The caller (endpoint layer) MUST surface this as a clear error to the
    operator and MUST NOT perform any partial write (Graceful Degradation).
    """


@dataclass
class ReconcileRow:
    """One GBP row overlaid with its computed verdict and matched TN rows."""

    ean: str
    verdict: str
    gbp_row: dict
    tn_matches: list = field(default_factory=list)
    despublicar: bool = False


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
        xml_content = await call_soap_service(soap_body, soap_action, token)
        if "TOKEN Expired" in xml_content:
            token = await authenticate_user()
            xml_content = await call_soap_service(soap_body, soap_action, token)
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


def _as_int(value, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _is_visible(tn: TiendaNubeProducto) -> bool:
    """Fail-safe check for "actually published/visible in the storefront".

    MUST key off TN's real `published` field, never `activo` — `activo` only
    means "present in the last full sync" and is set true for every product
    the /products endpoint returns, including unpublished/draft ones.
    `published IS None` means the row hasn't been re-synced with the new
    field yet (unknown), and MUST NOT be treated as published — never
    over-claim DESPUBLICAR on unknown data.
    """
    return getattr(tn, "published", None) is True


def compute_verdicts(
    gbp_rows: list[dict],
    tn_productos: list[TiendaNubeProducto],
    banned_eans: Optional[set[str]] = None,
) -> list[ReconcileRow]:
    """Compute the verdict taxonomy for each GBP row.

    Verdicts: FALTA_VINCULAR, FALTA_PUBLICAR, MAL_VINCULADO, DUPLICADO,
    MAL_PUBLICADO, OK (fully matched — not an anomaly, not returned as an
    action item but kept so `despublicar` can still be surfaced).

    DUPLICADO is a human-review anomaly only — this function never picks a
    "correct" row/variant among duplicates. It reports every conflicting row
    with full context (`tn_matches`) for the operator to judge.
    """
    banned_eans = banned_eans or set()

    # Index TN products by normalized variant_sku (EAN-join). A null/empty
    # sku is never indexed, so it can never match any EAN (Verdict Edge Cases).
    tn_by_sku: dict[str, list[TiendaNubeProducto]] = {}
    for tn in tn_productos:
        sku = _normalize_sku(tn.variant_sku)
        if sku is None:
            continue
        tn_by_sku.setdefault(sku, []).append(tn)

    # Index TN products by (product_id, variant_id) — used only to re-verify
    # an already-claimed link (tnr_id/tnr_variationID), never as the join key.
    tn_by_ids: dict[tuple, TiendaNubeProducto] = {}
    for tn in tn_productos:
        tn_by_ids[(tn.product_id, tn.variant_id)] = tn

    # Detect DUPLICADO groups: two or more GBP rows sharing the same
    # (tnr_id, tnr_variationID) pair.
    dup_groups: dict[tuple, list[int]] = {}
    for idx, row in enumerate(gbp_rows):
        tnr_id = _as_int(row.get("tnr_id"))
        tnr_variation_id = _as_int(row.get("tnr_variationID"))
        if tnr_id > 0:
            dup_groups.setdefault((tnr_id, tnr_variation_id), []).append(idx)

    duplicated_indices = {idx for indices in dup_groups.values() if len(indices) > 1 for idx in indices}

    results: list[ReconcileRow] = []
    for idx, row in enumerate(gbp_rows):
        ean = _normalize_sku(row.get("Código"))
        tnr_id = _as_int(row.get("tnr_id"))
        tnr_variation_id = _as_int(row.get("tnr_variationID"))
        stock = _as_int(row.get("stock"))

        matches_by_ean = tn_by_sku.get(ean, []) if ean else []

        despublicar = any(_is_visible(tn) and stock == 0 for tn in matches_by_ean)

        if idx in duplicated_indices:
            results.append(ReconcileRow(ean=ean or "", verdict="DUPLICADO", gbp_row=row, tn_matches=matches_by_ean))
            continue

        if len(matches_by_ean) > 1:
            # Multiple TN variants share the same EAN — never silently
            # resolved to one arbitrary variant (Verdict Edge Cases).
            results.append(ReconcileRow(ean=ean or "", verdict="DUPLICADO", gbp_row=row, tn_matches=matches_by_ean))
            continue

        if tnr_id == 0:
            if matches_by_ean:
                verdict = "FALTA_VINCULAR"
            elif ean and ean in banned_eans:
                continue  # banned: hidden from the actionable view
            else:
                verdict = "FALTA_PUBLICAR"
            results.append(
                ReconcileRow(
                    ean=ean or "", verdict=verdict, gbp_row=row, tn_matches=matches_by_ean, despublicar=despublicar
                )
            )
            continue

        if tnr_variation_id == 0:
            results.append(
                ReconcileRow(
                    ean=ean or "",
                    verdict="MAL_VINCULADO",
                    gbp_row=row,
                    tn_matches=matches_by_ean,
                    despublicar=despublicar,
                )
            )
            continue

        # tnr_id and tnr_variationID both resolved: verify the claimed link.
        claimed_tn = tn_by_ids.get((tnr_id, tnr_variation_id))
        claimed_despublicar = bool(claimed_tn and _is_visible(claimed_tn) and stock == 0)
        if claimed_tn is None or _normalize_sku(claimed_tn.variant_sku) != ean:
            verdict = "MAL_PUBLICADO"
        else:
            verdict = "OK"

        results.append(
            ReconcileRow(
                ean=ean or "",
                verdict=verdict,
                gbp_row=row,
                tn_matches=[claimed_tn] if claimed_tn else matches_by_ean,
                despublicar=claimed_despublicar or despublicar,
            )
        )

    return results
