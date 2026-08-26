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
 * Row actions cell: consolidates what used to be scattered across the
 * `Coincidencias TN (IDs)` and `Despublicar` columns into one `Acciones`
 * cell. This module owns the pure "what applies to this row" decisions;
 * `RowActionsCell` owns rendering.
 *
 * SOLO se devuelve una acción primaria cuando existe algo que ejecutar.
 * Antes esto devolvía `Revisar` y `Vincular`, que se renderizaban como
 * botones con `onClick={undefined}`: enfocables, con aspecto de acción, y
 * sin hacer absolutamente nada. No hay endpoint de vinculación ni de
 * revisión, así que no hay botón — un control que promete algo que el
 * sistema no puede cumplir es peor que la ausencia del control.
 *
 * Las filas sin acción primaria conservan las que SÍ existen (Banear, y el
 * menú con Despublicar / Editar en TN).
 */
export function resolvePrimaryAction(row, canPublish) {
  if (row.verdict === 'FALTA_PUBLICAR' && canPublish) {
    return { id: 'publicar', label: 'Publicar' };
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
 * Banear is the other half of the operator's triage decision on a
 * FALTA_PUBLICAR/FALTA_VINCULAR row (publish it, or make it stop
 * appearing) — not a secondary/overflow action. Kept as its own pure
 * function (rather than folded back into `resolveSecondaryActions`) so
 * `RowActionsCell` can render it as a visible button next to the primary
 * action instead of burying it in the ⋮ menu (tn-categorias-descubribles
 * fix, defect 2 — it used to live only in the overflow menu / a buried
 * ghost button, and operators couldn't find it).
 */
export function resolveBanAction(row, canBanlist) {
  if (!canBanlist) return null;
  if (row.verdict !== 'FALTA_PUBLICAR' && row.verdict !== 'FALTA_VINCULAR') return null;
  return { id: 'banear', label: 'Banear' };
}

/**
 * Secondary (overflow-menu) actions that apply to this row, permission-gated
 * exactly as the pre-extraction inline ternaries were:
 * - Despublicar: `row.despublicar` AND a resolvable target product id,
 *   gated by `canPublish`.
 * Editar en TN used to be here too; it is now a visible action —
 * see `resolveEditorAction`.
 *
 * Banear is NOT included here — see `resolveBanAction`, rendered as a
 * visible primary-adjacent action instead of a menu item.
 */
/**
 * Single definition of "what this row is called" (PR5). Products never
 * published to ML have no `ml_title` and would render as an anonymous EAN,
 * even though GBP report 78 already carries an ERP `Descripción` for them
 * (exposed as `erp_desc`). Never fabricated — the ERP text is used only when
 * `ml_title` is absent, and `fromErp` lets each caller label it so it is
 * never mistaken for a real ML title.
 *
 * Every place that names a row reads this, so the same product can't appear
 * named in the table and anonymous in the DUPLICADO group header/card.
 */
// DUPLICADO card redesign (pass C): each conflicting TN match's badge uses
// the SAME Publicado/Borrador/Desconocido vocabulary `tnPresenceShortLabelFor`
// introduced for the general table's presence label in pass B — a match's
// own tri-state `published` field (true/false/null, see the `published`
// column docstring) maps onto it directly rather than the row-level "Sí/No"
// wording the old nested table used.
export function matchPublishedLabel(published) {
  if (published === true) return 'Publicado';
  if (published === false) return 'Borrador';
  return 'Desconocido';
}

export function rowIdentity(row) {
  if (row.ml_title) return { text: row.ml_title, fromErp: false };
  if (row.erp_desc) return { text: row.erp_desc, fromErp: true };
  return { text: '', fromErp: false };
}

export function resolveSecondaryActions(row, { canPublish, despublicarTargetProductId }) {
  const actions = [];

  if (row.despublicar && canPublish) {
    const productId = despublicarTargetProductId(row);
    if (productId !== null && productId !== undefined) {
      actions.push({ id: 'despublicar', label: 'Despublicar', productId });
    }
  }

  return actions;
}

/**
 * "Editar en TN" as a VISIBLE row action instead of an overflow-menu item.
 *
 * It used to live in `resolveSecondaryActions`, behind the three-dot menu —
 * so the first thing an operator wants to do with a mis-published row
 * (open it in Tienda Nube and see what is actually loaded) took a click
 * nobody knew was there. Never permission-gated, exactly as it was not
 * gated as a menu item: opening TN in another tab reveals nothing the row
 * does not already show.
 *
 * Returns `null` when no match carries a `tn_admin_url` — there is nothing
 * to link to, and a dead button is worse than no button.
 */
/**
 * "Aceptar como correcto" / "Quitar excepción" — the exit the anomaly
 * verdicts never had.
 *
 * The ban list deliberately does not cover MAL_PUBLICADO/MAL_VINCULADO/
 * DUPLICADO: banning means "don't offer this to publish", never "hide a
 * broken publication". That rule is right, but it left a legitimately
 * intentional anomaly — a SKU that differs on purpose, a deliberate
 * duplicate — screaming forever, and an alert nobody can silence is one
 * people learn to ignore entirely.
 *
 * Driven by `row.evidencia`, which the BACKEND emits only for the verdicts
 * that admit an exception. The client never decides what is acceptable:
 * no `evidencia`, no action. Always reversible — an exception you cannot
 * undo is a decision nobody will dare take.
 */
export function resolveExcepcionAction(row, canExcepciones) {
  if (!canExcepciones) return null;
  if (!row.evidencia) return null;
  const aceptada = row.excepcion_aceptada === true;
  return {
    id: 'aceptar_excepcion',
    label: aceptada ? 'Quitar excepción' : 'Aceptar como correcto',
    evidencia: row.evidencia,
    aceptada,
  };
}

export function resolveEditorAction(row) {
  const editorMatch = pickEditorTnMatch(row);
  if (!editorMatch) return null;
  return {
    id: 'editar_tn',
    label: 'Editar en TN',
    href: editorMatch.tn_admin_url,
    productId: editorMatch.product_id,
  };
}

/**
 * Traduce la respuesta del endpoint de publicación a un toast.
 *
 * El backend responde HTTP 200 con `submitted: false` para SEIS desenlaces
 * distintos (`already_published`, `already_exists`, `precheck_failed`,
 * `rejected_by_proxy`, `rate_limited`, `ambiguous`): solo tres estados se
 * convierten en HTTP 400. Antes la página trataba a los ocho como éxito, así
 * que un producto que nunca llegó a Tienda Nube mostraba un toast verde —
 * el operador reintentaba y volvía a ver el mismo verde.
 *
 * Severidad: `already_published`/`already_exists` no son errores del
 * operador (el producto ya estaba), así que van como `info`. El resto son
 * fallas reales y van como `error`. `success` queda reservado para una
 * publicación que efectivamente ocurrió.
 *
 * El texto siempre incluye el `detail` del backend, que es lo único que
 * explica QUÉ pasó y si hay algo para hacer.
 */
const PUBLISH_INFORMATIVE_STATUSES = new Set(['already_published', 'already_exists']);

export function resolvePublishToast(ean, data) {
  // Sin payload no hay nada que contradiga al éxito: el POST devolvió 200 y
  // no lanzó. Es el comportamiento histórico y el fallback seguro.
  if (!data || data.submitted !== false) {
    return { type: 'success', message: `Producto con EAN ${ean} publicado` };
  }
  const status = data.status || 'desconocido';
  const detail = data.detail || `El backend respondió "${status}" sin más detalle.`;
  if (PUBLISH_INFORMATIVE_STATUSES.has(status)) {
    return { type: 'info', message: `EAN ${ean}: no se creó nada nuevo. ${detail}` };
  }
  return { type: 'error', message: `No se pudo publicar el EAN ${ean}. ${detail}` };
}
