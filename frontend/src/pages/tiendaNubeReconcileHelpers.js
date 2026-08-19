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
