/**
 * Tiny pure helper extracted from `TiendaNubeReconcile.jsx` so it can be
 * unit tested directly. Kept out of the page component file: exporting a
 * plain function alongside a default component export trips
 * `react-refresh/only-export-components` (same reasoning as
 * `misSubPMsHelpers.js` / `components/parKey.js`).
 */

/**
 * Selects the row set backing the active sub-tab. 'BANLIST' MUST resolve to
 * `baneados`, never `reporte` — before this fix `currentTabItems` fell back
 * to the whole `reporte` on 'BANLIST', so `total`/`totalPages`/`filasVisibles`
 * and the page-clamp effect were silently computed against unrelated
 * verdict rows while that tab actually renders `baneados`.
 */
export function selectTabItems(subTab, reporte, baneados) {
  if (subTab === 'todos') return reporte;
  if (subTab === 'BANLIST') return baneados;
  return reporte.filter((r) => r.verdict === subTab);
}

// Verdicts the "Necesitan revisión" summary card counts — everything that
// requires a human decision rather than a mechanical publish/unblock action.
const REVIEW_VERDICTS = new Set(['DUPLICADO', 'MAL_VINCULADO', 'MAL_PUBLICADO', 'POR_CORREGIR']);

/**
 * A FALTA_PUBLICAR row is "blocked" when its own publish draft carries a
 * blocking flag or a `publish_fields_error` — both are backend-computed
 * fields already present on the row, never derived/invented here.
 */
function isPublishBlocked(row) {
  return Boolean(row.publish_fields_error) || Boolean(row.publish_draft?.blocked);
}

/**
 * Summary-strip counts (PR-10). Derives every number from the already
 * fetched `reporte` set — no new field, no new request. Mirrors the
 * approved design's 4 cards: ready to publish / blocked / needs review /
 * total.
 */
/**
 * Predicate for the summary strip's click-to-filter behaviour (PR-10) — one
 * function shared by `computeSummaryCounts` semantics and the actual table
 * filter, so the card's number and what clicking it shows can never drift
 * apart.
 */
export function matchesSummaryFilter(row, filterId) {
  if (filterId === 'ready') return row.verdict === 'FALTA_PUBLICAR' && !isPublishBlocked(row);
  if (filterId === 'bloqueados') return row.verdict === 'FALTA_PUBLICAR' && isPublishBlocked(row);
  if (filterId === 'revision') return REVIEW_VERDICTS.has(row.verdict);
  return true; // 'total' — every row
}

export function computeSummaryCounts(reporte) {
  let readyToPublish = 0;
  let bloqueados = 0;
  let necesitanRevision = 0;

  for (const row of reporte) {
    if (row.verdict === 'FALTA_PUBLICAR') {
      if (isPublishBlocked(row)) bloqueados += 1;
      else readyToPublish += 1;
    } else if (REVIEW_VERDICTS.has(row.verdict)) {
      necesitanRevision += 1;
    }
  }

  return {
    readyToPublish,
    bloqueados,
    necesitanRevision,
    total: reporte.length,
  };
}

/**
 * Client-side search across EAN, ML title and TN SKU (of the first match) —
 * the three fields an operator is realistically searching by. Case/accent
 * insensitive on title text; EAN/SKU compared as plain substrings.
 */
export function matchesSearch(row, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystacks = [row.ean, row.ml_title, row.erp_desc, row.tn_matches?.[0]?.variant_sku];
  return haystacks.some((value) => typeof value === 'string' && value.toLowerCase().includes(q));
}

/**
 * Row actions cell (PR-A of the reconcile table redesign): consolidates
 * what used to be scattered across the `Coincidencias TN (IDs)` and
 * `Despublicar` columns into one `Acciones` cell. This module owns the pure
 * "what applies to this row" decisions; `RowActionsCell` owns rendering.
 *
 * Primary action is always a REAL, interactive button (never a disabled
 * placeholder) so an operator without `admin.gestionar_tn_publicacion` still
 * has something useful to do: `Revisar`/`Vincular` route to nothing
 * server-side (there is no dedicated review/link endpoint yet) but they are
 * kept clickable — `onAction` fires with the row so a caller CAN wire one up
 * later without another RowActionsCell contract change.
 */
export function resolvePrimaryAction(row, canPublish) {
  if (row.verdict === 'FALTA_PUBLICAR') {
    return canPublish ? { id: 'publicar', label: 'Publicar' } : { id: 'revisar', label: 'Revisar' };
  }
  if (row.verdict === 'FALTA_VINCULAR') {
    return { id: 'vincular', label: 'Vincular' };
  }
  return null;
}

/**
 * Picks WHICH tn_match "Editar en TN" targets, mirroring
 * `despublicarTargetProductId`'s preference (the match TN itself reports as
 * `published: true`, else the first match that actually carries a URL) — the
 * same "pick the one that's actually live" reasoning, now shared by two
 * actions instead of re-implemented per action.
 */
export function pickEditorTnMatch(row) {
  const matches = row.tn_matches || [];
  const withUrl = matches.filter((tn) => tn.tn_admin_url);
  if (withUrl.length === 0) return null;
  const published = withUrl.find((tn) => tn.published === true);
  return published || withUrl[0];
}

/**
 * Table-redesign pass B: picks WHICH tn_match the collapsed `En Tienda
 * Nube` column shows as "the" match (product_id/variant_id pair), mirroring
 * `despublicarTargetProductId`'s same "the one actually live" preference —
 * prefer a match TN itself reports as `published: true`, else the first
 * match. Unlike `pickEditorTnMatch` this does NOT require a `tn_admin_url`
 * (the IDs are worth showing even when there is nothing to link to).
 */
export function primaryTnMatch(row) {
  const matches = row.tn_matches || [];
  if (matches.length === 0) return null;
  const published = matches.find((tn) => tn.published === true);
  return published || matches[0];
}

/**
 * Secondary (overflow-menu) actions that apply to this row, permission-gated
 * exactly as the pre-extraction inline ternaries were:
 * - Banear: FALTA_PUBLICAR or FALTA_VINCULAR, gated by `canBanlist`.
 * - Despublicar: `row.despublicar` AND a resolvable target product id,
 *   gated by `canPublish`.
 * - Editar en TN: any resolvable match with a `tn_admin_url`, ungated (was
 *   never permission-gated in the original inline link either).
 */
export function resolveSecondaryActions(row, { canBanlist, canPublish, despublicarTargetProductId }) {
  const actions = [];

  if (canBanlist && (row.verdict === 'FALTA_PUBLICAR' || row.verdict === 'FALTA_VINCULAR')) {
    actions.push({ id: 'banear', label: 'Banear' });
  }

  if (row.despublicar && canPublish) {
    const productId = despublicarTargetProductId(row);
    if (productId !== null && productId !== undefined) {
      actions.push({ id: 'despublicar', label: 'Despublicar', productId });
    }
  }

  const editorMatch = pickEditorTnMatch(row);
  if (editorMatch) {
    actions.push({ id: 'editar_tn', label: 'Editar en TN', href: editorMatch.tn_admin_url, productId: editorMatch.product_id });
  }

  return actions;
}
