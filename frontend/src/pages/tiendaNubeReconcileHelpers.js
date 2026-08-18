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
