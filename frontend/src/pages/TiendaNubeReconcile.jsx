/**
 * TiendaNubeReconcile — read-only reconciliation view + banlist management
 * (Slice 1).
 *
 * Joins GBP export report 78 against the Tienda Nube catalog live (verdicts
 * are never persisted, only ban-list decisions are). Surfaces the verdict
 * taxonomy as sub-tabs, with MAL_PUBLICADO and DUPLICADO as first-class
 * dedicated views per the spec's Data-Quality Anomaly Surfacing requirement,
 * plus a dedicated Banlist sub-tab completing the ban/unban cycle (a
 * mis-banned EAN must always be recoverable from the UI).
 *
 * DUPLICADO groups are presented as "needs human review", never as an error,
 * and MUST NOT pre-select/highlight/recommend any conflicting row — the
 * human, not the system, decides (see spec: DUPLICADO Verdict requirement).
 *
 * Banning only means "don't offer this as something to publish" — it hides
 * FALTA_PUBLICAR/FALTA_VINCULAR, never MAL_VINCULADO/MAL_PUBLICADO/DUPLICADO
 * (enforced server-side in `tn_reconciliation_service.compute_verdicts`).
 *
 * One-shot fetch (third review round — replaces server-side pagination):
 * `/reporte` is called ONCE on mount and again only on an explicit
 * "Actualizar" click or after a ban/unban (a real data change) — NEVER on
 * sub-tab switch or page navigation. Earlier server-side pagination
 * re-triggered a full SOAP fetch per page/tab click, reproducing the exact
 * pool-exhaustion shape an earlier round had fixed; this matches the
 * feature's original intent ("query it live with a button"). Sub-tab
 * filtering and paging are both derived client-side from the one fetched
 * set. Sub-tab counters read the server's `verdict_counts` (the TRUE total
 * per verdict across the WHOLE set), never a client-side page-length count.
 * The banlist count is loaded on mount too (not only when its tab is
 * opened) and refreshed after every ban/unban — the same "no lying counter"
 * standard applied to `verdict_counts`.
 *
 * Accessible tabs: `.subTabBar` is a `role="tablist"`; each button is a
 * `role="tab"` with `aria-selected` tracking the active tab and arrow-key
 * (Left/Right/Home/End) roving-focus navigation. Only the active tab's
 * content is ever rendered (one panel at a time), so every tab's
 * `aria-controls` points at the SAME single, always-present `TAB_PANEL_ID`
 * rather than a per-tab id — a per-tab id would dangle for every INACTIVE
 * tab, itself an accessibility defect (round 7, item 3). The panel's
 * `aria-labelledby` still tracks whichever tab is currently selected.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table';
import { Search, Loader2 } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import TnPublishModal from '../components/tn-publisher/TnPublishModal';
import RowActionsCell from '../components/tn-reconcile/RowActionsCell';
import api from '../services/api';
import {
  selectTabItems,
  computeSummaryCounts,
  matchesSearch,
  matchesSummaryFilter,
  primaryTnMatch,
  rowIdentity,
} from './tiendaNubeReconcileHelpers';
import DuplicateGroupCard from '../components/tn-reconcile/DuplicateGroupCard';
import styles from './TiendaNubeReconcile.module.css';
import { stripHtmlToText } from '../utils/htmlText';

export const COLUMN_SIZING_STORAGE_KEY = 'tnreconcile:colsizing:reporte';

const PAGE_SIZE = 50;

// Round 7, item 3: only the ACTIVE tab's content is ever rendered (one
// panel at a time), so every tab's `aria-controls` must point at the SAME
// single, always-present panel id — not a per-tab id that only exists
// while that specific tab happens to be selected. Pointing every tab at
// this one stable id means `aria-controls` never dangles for an inactive
// tab; `aria-labelledby` on the panel itself still tracks which tab is
// currently "in control" of it.
const TAB_PANEL_ID = 'tn-panel';

const VERDICT_LABELS = {
  FALTA_VINCULAR: 'Falta vincular',
  FALTA_PUBLICAR: 'Falta publicar',
  MAL_VINCULADO: 'Mal vinculado',
  MAL_PUBLICADO: 'Mal publicado',
  DUPLICADO: 'Duplicado',
  // Match-accuracy follow-up: linked, but the TN SKU differs from the GBP
  // EAN only by leading zeros/formatting — needs a human to canonicalize
  // it, never auto-corrected. Own group, distinct from OK and MAL_PUBLICADO.
  POR_CORREGIR: 'Por corregir',
  OK: 'OK',
};

// One distinct colour per verdict (previously FALTA_PUBLICAR/MAL_VINCULADO/
// POR_CORREGIR all shared the same orange, and MAL_PUBLICADO/DUPLICADO
// shared the same red — the badge colour carried no signal).
const VERDICT_BADGE_CLASS = {
  FALTA_VINCULAR: 'badgeInfo',
  FALTA_PUBLICAR: 'badgeSuccess',
  MAL_VINCULADO: 'badgeWarning',
  MAL_PUBLICADO: 'badgeDanger',
  DUPLICADO: 'badgePurple',
  POR_CORREGIR: 'badgeTeal',
  OK: 'badge',
};

// Sub-tabs shown, in order. "todos" aggregates every actionable verdict
// (everything except OK, which is not an anomaly). "BANLIST" is not a
// verdict — it's the banned-EAN management view.
const VERDICT_SUB_TABS = [
  { id: 'todos', label: 'Todos' },
  { id: 'FALTA_VINCULAR', label: 'Falta vincular' },
  { id: 'FALTA_PUBLICAR', label: 'Falta publicar' },
  { id: 'MAL_VINCULADO', label: 'Mal vinculado' },
  { id: 'MAL_PUBLICADO', label: 'Mal publicado' },
  { id: 'DUPLICADO', label: 'Duplicado' },
  { id: 'POR_CORREGIR', label: 'Por corregir' },
];

function verdictLabelFor(verdictId) {
  return VERDICT_LABELS[verdictId] || verdictId;
}

// TN Presence Field requirement — replaces the old ambiguous single
// "Desconocido" label with four distinct, non-ambiguous states.
// "unknown" is NOT "we don't know if this exists in TN" — the backend only
// returns it when the TN row WAS resolved and its `published` flag simply
// has not been re-synced locally yet (see TiendaNubeProducto.published
// docstring). The label must communicate the actionable truth, never
// ignorance of the row's existence.
const TN_PRESENCE_LABELS = {
  published: 'Publicado en TN',
  draft: 'Borrador en TN',
  unknown: 'Existe en TN, publicación no sincronizada',
  not_in_tn: 'No está en Tienda Nube',
};

function tnPresenceLabelFor(presence) {
  return TN_PRESENCE_LABELS[presence] || TN_PRESENCE_LABELS.not_in_tn;
}

// Table redesign pass B: the old long, one-of-a-kind sentence per state
// (e.g. "Existe en TN, publicación no sincronizada") is replaced by a short
// coloured label — `tnPresenceLabelFor` (the long sentence) still backs the
// label's tooltip so the fuller explanation isn't lost, only demoted from
// "the whole cell" to "on hover/focus".
const TN_PRESENCE_SHORT_LABELS = {
  published: 'Publicado',
  draft: 'Borrador',
  unknown: 'Sin sincronizar',
  not_in_tn: 'No está',
};

const TN_PRESENCE_CLASS = {
  published: 'presenceGreen',
  draft: 'presenceOrange',
  unknown: 'presenceOrange',
  not_in_tn: 'presenceTertiary',
};

function tnPresenceShortLabelFor(presence) {
  return TN_PRESENCE_SHORT_LABELS[presence] || TN_PRESENCE_SHORT_LABELS.not_in_tn;
}

/**
 * "En Tienda Nube" cell (pass B: merges the old Presencia en TN, Motivo and
 * Coincidencias TN (IDs) columns into one). No per-row action here —
 * `tn_presence == "unknown"`'s remediation is the single global sync
 * trigger in the page header (see `mostrarSincronizarTn`), never a per-row
 * button (would misrepresent the action's scope, see the original
 * `TnPresenceCell` reasoning this cell now carries forward).
 */
function TnPresenceCell({ row }) {
  const presenceClass = TN_PRESENCE_CLASS[row.tn_presence] || TN_PRESENCE_CLASS.not_in_tn;
  const primaryMatch = primaryTnMatch(row);
  const extraMatches = Math.max(0, (row.tn_matches?.length || 0) - 1);

  return (
    <div className={styles.presenceCell}>
      <span
        className={`${styles.presenceLabel} ${styles[presenceClass]}`}
        title={tnPresenceLabelFor(row.tn_presence)}
      >
        {tnPresenceShortLabelFor(row.tn_presence)}
      </span>
      <MotivoInline row={row} />
      {primaryMatch && (
        <div className={styles.presenceIds}>
          {primaryMatch.product_id}/{primaryMatch.variant_id}
          {extraMatches > 0 && <span className={styles.presenceExtra}> +{extraMatches}</span>}
        </div>
      )}
    </div>
  );
}

// Reason/cause taxonomy (Slice 1) — exhaustive-by-default code -> Spanish
// label map. An unrecognized/absent code renders as an empty cell, never a
// raw code and never "undefined" (R1.6/R1.7: rows with no reason must not
// regress, and a backend that hasn't shipped a new code yet must degrade
// safely rather than crash).
const REASON_LABELS = {
  DEAD_LINK: 'Enlace inexistente en Tienda Nube',
  SKU_MISMATCH: 'SKU no coincide con el EAN',
  NO_VARIANT_LINK: 'Sin vínculo de variante',
};

// Pass B: Motivo is no longer its own column — it renders inline, under the
// presence label, inside the "En Tienda Nube" cell, and simply renders
// nothing when there is no reason (there is no longer a standalone column
// to keep non-empty/aligned, so unlike the old ReasonCell there is no '—'
// placeholder).
function MotivoInline({ row }) {
  if (!row.reason) return null;
  // An unmapped code (a reason the backend added before this map caught up)
  // renders as its raw code rather than disappearing like "no reason at
  // all" would — degrading safely must not erase the signal.
  const label = REASON_LABELS[row.reason] || row.reason;

  const detail = row.reason_detail || {};
  const parts = [];
  if (detail.expected_ean) parts.push(`EAN esperado: ${detail.expected_ean}`);
  if (detail.tn_sku_found) parts.push(`SKU en TN: ${detail.tn_sku_found}`);
  if (detail.claimed_tnr_id) parts.push(`tnr_id declarado: ${detail.claimed_tnr_id}`);
  if (detail.claimed_tnr_variation_id) parts.push(`tnr_variationID declarado: ${detail.claimed_tnr_variation_id}`);

  return (
    <span className={styles.presenceMotivo} title={parts.join(' · ')}>
      {label}
    </span>
  );
}

// Stock cell: unknown stock (`null`) MUST render distinctly from a real
// zero — `0` is exactly the value that raises `despublicar` on the backend,
// so collapsing "unknown" into "0" (or into a blank cell that reads the same
// as zero) would be a real defect (design.md Decision 3). An em dash is
// visibly non-numeric, unlike "0" or an empty string.
const STOCK_UNKNOWN_LABEL = '—';

function StockCell({ row }) {
  return row.stock === null || row.stock === undefined ? STOCK_UNKNOWN_LABEL : String(row.stock);
}

const DESC_SNIPPET_LENGTH = 140;
const THUMB_PREVIEW_SIZE = 220;

/**
 * Product identity cell: thumbnail (hover/focus → larger preview), title and
 * a truncated description the operator can expand in place. Makes each row
 * recognizable at a glance instead of an anonymous EAN.
 */

function ProductoCell({ row }) {
  const [expanded, setExpanded] = useState(false);
  const [previewPos, setPreviewPos] = useState(null);

  const thumbSrc = Array.isArray(row.images) && row.images.length > 0 ? row.images[0] : null;
  const descText = useMemo(() => stripHtmlToText(row.ml_desc), [row.ml_desc]);
  // Identity fallback (PR5): products never published to ML have no
  // `ml_title` — they'd otherwise render as an anonymous EAN even though the
  // ERP already has a description for them (GBP report 78's `Descripción`
  // column, exposed as `erp_desc`). Never fabricated: only used when
  // `ml_title` is absent, and visibly labeled so it's never mistaken for a
  // real ML title.
  const { text: titleText, fromErp: usingErpFallback } = rowIdentity(row);

  // POR_CORREGIR (linked, but the TN SKU differs from the GBP EAN only by
  // leading zeros/formatting): show both values side by side so the
  // operator sees exactly what needs canonicalizing. Every other verdict
  // renders the EAN alone. Only rendered when there is an actual TN match
  // to compare against — a POR_CORREGIR row without a resolved match
  // renders its EAN exactly as any other verdict does.
  const tnSku = row.tn_matches?.[0]?.variant_sku;
  const showEanCompare = row.verdict === 'POR_CORREGIR' && Boolean(tnSku);

  const showPreview = (target) => {
    const rect = target.getBoundingClientRect();
    // Fixed-position preview (escapes the table's overflow container);
    // clamped so it never renders below the viewport.
    const top = Math.min(rect.top, Math.max(8, window.innerHeight - THUMB_PREVIEW_SIZE - 16));
    setPreviewPos({ top, left: rect.right + 10 });
  };

  const altText = titleText ? `Miniatura de ${titleText}` : `Miniatura del EAN ${row.ean}`;
  const isTruncated = descText.length > DESC_SNIPPET_LENGTH;

  return (
    <div className={styles.productoCell}>
      {thumbSrc && (
        /* Keyboard-focusable so the preview is reachable without a mouse;
           role="img" + aria-label give it a meaningful announcement (a bare
           focusable span announces nothing). The inner <img> is
           presentational (alt="" + aria-hidden) so screen readers hear ONE
           description, not two. */
        <span
          className={styles.thumbWrap}
          tabIndex={0}
          role="img"
          aria-label={altText}
          onMouseEnter={(e) => showPreview(e.currentTarget)}
          onMouseLeave={() => setPreviewPos(null)}
          onFocus={(e) => showPreview(e.currentTarget)}
          onBlur={() => setPreviewPos(null)}
        >
          <img src={thumbSrc} alt="" aria-hidden="true" className={styles.thumb} loading="lazy" />
          {previewPos && (
            <img
              src={thumbSrc}
              alt=""
              aria-hidden="true"
              className={styles.thumbPreview}
              style={{ top: previewPos.top, left: previewPos.left }}
            />
          )}
        </span>
      )}
      <div className={styles.prodText}>
        {titleText && (
          <div className={styles.prodTitle} title={titleText}>
            {usingErpFallback && <span className={styles.prodTitleErpTag}>ERP</span>}
            {titleText}
          </div>
        )}
        {descText &&
          (isTruncated ? (
            <button
              type="button"
              className={`${styles.prodDesc} ${expanded ? styles.prodDescExpanded : ''}`}
              title={descText}
              aria-expanded={expanded}
              aria-label={expanded ? 'Contraer descripción' : 'Expandir descripción'}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? descText : `${descText.slice(0, DESC_SNIPPET_LENGTH)}…`}
            </button>
          ) : (
            <span className={`${styles.prodDesc} ${styles.prodDescStatic}`}>{descText}</span>
          ))}
        {showEanCompare ? (
          <div className={styles.eanCompareCell}>
            <div>EAN: {row.ean}</div>
            <div>SKU TN: {tnSku}</div>
          </div>
        ) : (
          <div className={styles.prodEan}>{row.ean}</div>
        )}
      </div>
    </div>
  );
}

// Fail-safe persistence — absent/corrupt/disabled localStorage MUST never
// throw (mirrors MLQuestions.jsx's loadColumnSizing/saveColumnSizing).
// Adding/removing a COLUMNS entry (like this PR's new `acciones` column)
// changes the stored-size shape: a stale saved entry may carry sizes for
// columns that no longer exist, or simply lack one for a brand-new column.
// TanStack tolerates extra unknown keys harmlessly and a missing key just
// falls back to that column's own default `size` — but we filter to KNOWN
// ids here anyway so a corrupted/foreign localStorage payload can never
// grow unbounded or leak an unrelated column's stale width into this table.
function loadColumnSizing() {
  try {
    const parsed = JSON.parse(localStorage.getItem(COLUMN_SIZING_STORAGE_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const knownIds = new Set(COLUMNS.map((c) => c.id));
    return Object.fromEntries(Object.entries(parsed).filter(([id]) => knownIds.has(id)));
  } catch {
    return {};
  }
}

function saveColumnSizing(state) {
  try {
    localStorage.setItem(COLUMN_SIZING_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Disabled/private-mode localStorage: resizing still works in-memory.
  }
}

// Single source of truth for the reporte table's columns: both the header
// (via TanStack) AND the body cells render from this list, so adding/
// removing a column can never desync header and body.
// Table redesign pass B: collapsed from 9 columns to 5. `EAN` moved into
// `Producto`; `Presencia en TN` + `Motivo` + `Coincidencias TN (IDs)` merged
// into `En Tienda Nube`; `Despublicar` dropped outright — the flag it showed
// (`row.despublicar` as Sí/—) is redundant with the presence label plus the
// action already living in the Acciones menu, and carries no information a
// human needs at a glance that those two don't already cover.
const COLUMNS = [
  {
    id: 'producto',
    header: 'Producto',
    size: 340,
    cell: (row) => <ProductoCell row={row} />,
  },
  {
    id: 'verdict',
    header: 'Veredicto',
    size: 140,
    cell: (row) => (
      <span className={`${styles.badge} ${styles[VERDICT_BADGE_CLASS[row.verdict]] || ''}`}>
        {verdictLabelFor(row.verdict)}
      </span>
    ),
  },
  {
    id: 'tn_presence',
    header: 'En Tienda Nube',
    size: 260,
    cell: (row) => <TnPresenceCell row={row} />,
  },
  {
    id: 'stock',
    header: 'Stock',
    size: 100,
    sortable: true,
    cell: (row) => <StockCell row={row} />,
  },
  { id: 'acciones', header: 'Acciones', size: 190, cell: null }, // rendered specially — RowActionsCell (primary + overflow menu)
];

// Slice 4: client-side sort over `currentTabItems`, BEFORE pagination —
// deliberately NOT wired onto TanStack's `getSortedRowModel` (the table
// instance here is used only for column sizing/resize; the body renders
// manually from `COLUMNS`/`filasVisibles`, see the module docstring's
// One-shot-fetch note and design.md Decision 3).
//
// Null/unknown-stock ordering is explicit and intentional, not an accident
// of the comparator: `stock === null` ALWAYS sorts last, in BOTH ascending
// and descending order. This is deliberately asymmetric — an operator
// sorting descending wants the highest stock first, and one sorting
// ascending wants the genuine lowest/zero-stock rows first; in both cases
// "unknown" is the least actionable row and belongs at the bottom, never
// mixed in as if it were a real value.
//
// Ties (equal stock, including two nulls) are broken by EAN for a stable,
// deterministic order across renders — never left to array-insertion order.
function compareByStock(a, b, direction) {
  const aNull = a.stock === null || a.stock === undefined;
  const bNull = b.stock === null || b.stock === undefined;
  if (aNull && bNull) return a.ean.localeCompare(b.ean);
  if (aNull) return 1; // nulls always last, regardless of direction
  if (bNull) return -1;
  if (a.stock !== b.stock) return direction === 'asc' ? a.stock - b.stock : b.stock - a.stock;
  return a.ean.localeCompare(b.ean);
}

function sortItems(items, sortState) {
  if (!sortState || sortState.column !== 'stock') return items;
  // `.slice()` first — sorting must never mutate the source array in place
  // (it's the same `reporte` state array the rest of the component reads).
  return items.slice().sort((a, b) => compareByStock(a, b, sortState.direction));
}

// Picks WHICH tn_match the unpublish action targets: prefer a match TN
// itself reports as `published: true` (the one actually live and worth
// unpublishing); fall back to the first match if none is explicitly
// published=true (published is nullable/unknown — see the `published`
// column docstring).
function despublicarTargetProductId(row) {
  const published = row.tn_matches.find((tn) => tn.published === true);
  if (published) return published.product_id;
  return row.tn_matches[0]?.product_id ?? null;
}

// Shared paginator — used identically by the DUPLICADO branch and the
// general-table branch (previously duplicated verbatim in both).
function Paginador({ page, totalPages, rangeStart, rangeEnd, total, onPrev, onNext }) {
  return (
    <div className={styles.paginatorBar}>
      <span>
        Mostrando {rangeStart}–{rangeEnd} de {total}
      </span>
      <div>
        <button type="button" className="btn-tesla ghost sm" disabled={page <= 1} onClick={onPrev}>
          Anterior
        </button>
        <button
          type="button"
          className={`btn-tesla ghost sm ${styles.btnSpaced}`}
          disabled={page >= totalPages}
          onClick={onNext}
        >
          Siguiente
        </button>
      </div>
    </div>
  );
}

const EMPTY_TABLE_DATA = [];

// Summary strip cards (PR-10) — answer the operator's real question, not
// the raw verdict taxonomy. `targetSubTab` is what a click switches the
// verdict chips to; `filterId` is the extra predicate applied on top
// (`matchesSummaryFilter`), since "ready"/"bloqueados" are both a SPLIT of
// the single FALTA_PUBLICAR verdict that the existing chip set can't
// express on its own.
const SUMMARY_CARDS = [
  {
    id: 'ready',
    label: 'Listo para publicar',
    dot: 'summaryDotGreen',
    hint: 'sin bloqueos',
    targetSubTab: 'FALTA_PUBLICAR',
    countKey: 'readyToPublish',
  },
  {
    id: 'bloqueados',
    label: 'Bloqueados',
    dot: 'summaryDotRed',
    hint: 'faltan medidas o cotización',
    targetSubTab: 'FALTA_PUBLICAR',
    countKey: 'bloqueados',
  },
  {
    id: 'revision',
    label: 'Necesitan revisión',
    dot: 'summaryDotPurple',
    hint: 'duplicados y mal vinculados',
    targetSubTab: 'todos',
    countKey: 'necesitanRevision',
  },
  {
    id: 'total',
    label: 'Total del reporte',
    dot: 'summaryDotGrey',
    hint: 'filas comparadas',
    targetSubTab: 'todos',
    countKey: 'total',
  },
];

export default function TiendaNubeReconcile() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('admin.ver_tn_reconciliacion');
  const puedeGestionarBanlist = tienePermiso('admin.gestionar_tn_reconcile_banlist');
  const puedeGestionarPublicacion = tienePermiso('admin.gestionar_tn_publicacion');
  const { toast, showToast, hideToast } = useToast(4000);

  // Explicit, operator-triggered, single-product unpublish (Slice 2). NEVER
  // bulk, NEVER automatic — a row must be flagged `despublicar` AND the
  // operator must explicitly confirm before the endpoint is called. Keyed
  // by product_id: only one row can be mid-confirmation at a time.
  const [confirmingProductId, setConfirmingProductId] = useState(null);
  const [despublicando, setDespublicando] = useState(false);

  // Publish modal (Sub-slice 3c) — one FALTA_PUBLICAR row at a time.
  const [publishingRow, setPublishingRow] = useState(null);

  // tn_presence "unknown" relabel + sync trigger (Slice 3) — wires the
  // ALREADY-EXISTING POST /tienda-nube/sync endpoint, no new backend action.
  const [syncingTn, setSyncingTn] = useState(false);

  const [reporte, setReporte] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [subTab, setSubTabState] = useState('todos');
  const [page, setPage] = useState(1);
  const [verdictCounts, setVerdictCounts] = useState({});
  const [catalogCapHit, setCatalogCapHit] = useState(false);
  const [gbpRowsCapHit, setGbpRowsCapHit] = useState(false);

  // Client-side stock sort (Slice 4). `null` means "no sort applied yet"
  // (original fetch order); `column`/`direction` otherwise. See `sortItems`.
  const [sortState, setSortState] = useState(null);

  // Client-side search (PR-10) — EAN/title/TN SKU, debounced. `searchInput`
  // is the raw controlled value; `searchQuery` is what actually filters,
  // updated after a short debounce so every keystroke doesn't re-filter 300+
  // rows synchronously.
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const searchDebounceRef = useRef(null);

  const handleSearchChange = useCallback((event) => {
    const value = event.target.value;
    setSearchInput(value);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => setSearchQuery(value), 200);
  }, []);

  useEffect(() => () => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
  }, []);

  // Last successful "Actualizar"/mount fetch timestamp, shown next to the
  // header actions.
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);

  // Toggle sequence: unsorted -> descending (highest stock first, the more
  // useful default for "what to publish first") -> ascending -> unsorted.
  // Changing the sort always resets to page 1 in the same event — the
  // sorted order is unrelated to which page was open, so keeping the old
  // page number could strand the operator past the new last page (the
  // `totalPages` clamp effect below is a second, redundant safety net).
  const toggleStockSort = useCallback(() => {
    setSortState((prev) => {
      if (!prev || prev.column !== 'stock') return { column: 'stock', direction: 'desc' };
      if (prev.direction === 'desc') return { column: 'stock', direction: 'asc' };
      return null;
    });
    setPage(1);
  }, []);

  // Changing sub-tab always resets to page 1 in the same event. Picking a
  // verdict chip directly is a DIFFERENT filter dimension than the summary
  // strip (see `summaryFilter` below) — it always clears whichever summary
  // card was active, so the two never silently combine into an
  // impossible/empty intersection (e.g. "Bloqueados" card + "Mal vinculado"
  // chip, which share no rows).
  const setSubTab = useCallback((tab) => {
    setSubTabState(tab);
    setPage(1);
    setSummaryFilterActive(false);
  }, []);

  // Summary-strip click-to-filter (PR-10). `summaryFilter` starts as
  // 'ready' purely for the FIRST CARD'S VISUAL highlight (per the approved
  // design: "the first card is the active one on load") — `summaryFilterActive`
  // stays false until the operator actually clicks a card, so the initial
  // view is still the full, unfiltered "Todos" tab (no behavior change on
  // mount).
  const [summaryFilter, setSummaryFilter] = useState('ready');
  const [summaryFilterActive, setSummaryFilterActive] = useState(false);

  const selectSummaryCard = useCallback((card) => {
    setSummaryFilter(card.id);
    setSummaryFilterActive(true);
    setSubTabState(card.targetSubTab);
    setPage(1);
  }, []);

  // Roving-focus refs for arrow-key navigation between tabs (WAI-ARIA
  // tablist pattern) — keyed by tab id so focus can be moved
  // programmatically after an arrow key changes the selected tab.
  const tabRefs = useRef({});

  // Banlist view state
  const [baneados, setBaneados] = useState([]);
  const [loadingBaneados, setLoadingBaneados] = useState(false);
  const [baneadosSeleccionados, setBaneadosSeleccionados] = useState(new Set());

  // One-shot fetch: no page/verdict params sent — the full verdict set
  // (everything except OK) is fetched once and filtered/paginated
  // client-side. See module docstring; this is the review-mandated fix for
  // "every page click / sub-tab switch re-ran the full SOAP fetch".
  const cargarReporte = useCallback(async () => {
    if (!puedeVer) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.get('/tienda-nube-reconcile/reporte');
      setReporte(response.data?.items || []);
      setVerdictCounts(response.data?.verdict_counts || {});
      setCatalogCapHit(Boolean(response.data?.catalog_cap_hit));
      setGbpRowsCapHit(Boolean(response.data?.gbp_rows_cap_hit));
      setLastUpdatedAt(new Date());
    } catch (err) {
      setError(err?.response?.data?.error?.message || err?.message || 'No se pudo cargar la reconciliación');
    } finally {
      setLoading(false);
    }
  }, [puedeVer]);

  const cargarBaneados = useCallback(async () => {
    if (!puedeGestionarBanlist) return;
    setLoadingBaneados(true);
    try {
      const response = await api.get('/tienda-nube-reconcile/baneados');
      setBaneados(response.data || []);
    } catch {
      showToast('No se pudo cargar la banlist', 'error');
    } finally {
      setLoadingBaneados(false);
    }
  }, [puedeGestionarBanlist, showToast]);

  // Both load once on mount. The banlist count must be known up-front
  // (never a stale "(0)") — loading it only when its tab is opened was the
  // same "lying counter" bug this slice already fixes for verdict_counts.
  useEffect(() => {
    cargarReporte();
    cargarBaneados();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const banearEan = useCallback(
    async (ean) => {
      if (!puedeGestionarBanlist) return;
      try {
        await api.post('/tienda-nube-reconcile/banear', { ean });
        showToast(`EAN ${ean} agregado a la banlist`, 'success');
        cargarReporte();
        cargarBaneados();
      } catch (err) {
        showToast(err?.response?.data?.error?.message || 'Error al banear el EAN', 'error');
      }
    },
    [puedeGestionarBanlist, cargarReporte, cargarBaneados, showToast]
  );

  const desbanearEan = useCallback(
    async (banlistId) => {
      if (!puedeGestionarBanlist) return;
      try {
        await api.post('/tienda-nube-reconcile/desbanear', { banlist_id: banlistId });
        showToast('EAN removido de la banlist', 'success');
        cargarBaneados();
        cargarReporte();
      } catch (err) {
        showToast(err?.response?.data?.error?.message || 'Error al desbanear el EAN', 'error');
      }
    },
    [puedeGestionarBanlist, cargarBaneados, cargarReporte, showToast]
  );

  const despublicarProducto = useCallback(
    async (productId) => {
      if (!puedeGestionarPublicacion) return;
      setDespublicando(true);
      try {
        await api.post('/tienda-nube-reconcile/despublicar', { product_id: productId });
        showToast(`Producto ${productId} despublicado`, 'success');
        cargarReporte();
      } catch (err) {
        showToast(err?.response?.data?.error?.message || 'Error al despublicar el producto', 'error');
      } finally {
        setDespublicando(false);
        setConfirmingProductId(null);
      }
    },
    [puedeGestionarPublicacion, cargarReporte, showToast]
  );

  const sincronizarTn = useCallback(
    async () => {
      if (!puedeGestionarPublicacion || syncingTn) return;
      setSyncingTn(true);
      try {
        await api.post('/tienda-nube/sync');
        showToast('Sincronización con Tienda Nube completada', 'success');
        cargarReporte();
      } catch (err) {
        showToast(err?.response?.data?.error?.message || 'Error al sincronizar con Tienda Nube', 'error');
      } finally {
        setSyncingTn(false);
      }
    },
    [puedeGestionarPublicacion, syncingTn, cargarReporte, showToast]
  );

  const toggleSeleccionBaneado = useCallback((id) => {
    setBaneadosSeleccionados((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const desbanearSeleccionados = useCallback(async () => {
    if (baneadosSeleccionados.size === 0) return;
    const ids = Array.from(baneadosSeleccionados);
    let processed = 0;
    try {
      for (const banlistId of ids) {
        await api.post('/tienda-nube-reconcile/desbanear', { banlist_id: banlistId });
        processed += 1;
      }
      showToast(`${processed} EAN(s) desbaneados exitosamente`, 'success');
    } catch (err) {
      const detail = err?.response?.data?.error?.message;
      showToast(
        `${processed} de ${ids.length} desbaneados. ${detail || 'Error al desbanear el resto'}`,
        'error'
      );
    } finally {
      // Always clear the selection AND refresh — even on partial failure,
      // some entries were already removed server-side and any remaining
      // selected ids may point at rows that no longer exist or were never
      // attempted; the UI must never keep showing them as "selected".
      setBaneadosSeleccionados(new Set());
      cargarBaneados();
      cargarReporte();
    }
  }, [baneadosSeleccionados, cargarBaneados, cargarReporte, showToast]);

  // Client-side filter (by sub-tab) over the ONE fetched set — the backend
  // is called once, not once per tab.
  const currentTabItems = useMemo(() => {
    let tabItems = selectTabItems(subTab, reporte, baneados);
    if (subTab === 'BANLIST') return tabItems;
    if (summaryFilterActive) tabItems = tabItems.filter((row) => matchesSummaryFilter(row, summaryFilter));
    if (searchQuery.trim()) tabItems = tabItems.filter((row) => matchesSearch(row, searchQuery));
    return tabItems;
  }, [reporte, baneados, subTab, searchQuery, summaryFilterActive, summaryFilter]);

  // Summary strip (PR-10) — derived from the full `reporte`, never from the
  // active sub-tab/search, so the 4 cards always answer "across the whole
  // report", independent of whatever the operator is currently filtering.
  const summaryCounts = useMemo(() => computeSummaryCounts(reporte), [reporte]);

  // Sort applied AFTER filter, BEFORE pagination (filter -> sort ->
  // paginate), so page 1 always shows the true extreme of the sorted set.
  // The BANLIST tab never reaches here with a sort applied in practice
  // (there is no stock column in that view), but `sortItems` is a no-op
  // when `sortState` isn't for the 'stock' column, so this stays correct
  // either way.
  const sortedTabItems = useMemo(() => sortItems(currentTabItems, sortState), [currentTabItems, sortState]);

  // Global sync trigger visibility (Slice 3): shown only when the operator
  // holds the permission AND at least one row in the CURRENT view actually
  // needs it — never shown as a standing, always-available action.
  // The BANLIST tab is excluded explicitly, kept as a defensive guard even
  // though `selectTabItems` now returns `baneados` (never `reporte`) there:
  // banlist rows have no `tn_presence` field, so `.some(...)` below would
  // already evaluate to false — this stays as a second, explicit safety net
  // documenting intent (a banned-EAN view, not a verdict view).
  const mostrarSincronizarTn =
    puedeGestionarPublicacion &&
    subTab !== 'BANLIST' &&
    currentTabItems.some((r) => r.tn_presence === 'unknown');

  const total = currentTabItems.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const showPaginator = total > PAGE_SIZE;
  const rangeStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, total);
  const filasVisibles = useMemo(
    () => sortedTabItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [sortedTabItems, page]
  );

  // Clamp `page` whenever the underlying (filtered) set shrinks — e.g.
  // banning the only row on the last page must not strand the view on an
  // empty page with no way back except switching sub-tabs (fourth review
  // round, item 3).
  useEffect(() => {
    setPage((p) => Math.min(Math.max(1, p), totalPages));
  }, [totalPages]);

  const [columnSizing, setColumnSizingState] = useState(() => loadColumnSizing());
  const columnSizingSaveTimerRef = useRef(null);

  const handleColumnSizingChange = useCallback((updater) => {
    setColumnSizingState((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (columnSizingSaveTimerRef.current) clearTimeout(columnSizingSaveTimerRef.current);
      columnSizingSaveTimerRef.current = setTimeout(() => saveColumnSizing(next), 200);
      return next;
    });
  }, []);

  const handleResetColumnSizing = useCallback(() => {
    if (columnSizingSaveTimerRef.current) clearTimeout(columnSizingSaveTimerRef.current);
    setColumnSizingState({});
    try {
      localStorage.removeItem(COLUMN_SIZING_STORAGE_KEY);
    } catch {
      // no-op — disabled/private-mode localStorage
    }
  }, []);

  const table = useReactTable({
    columns: COLUMNS,
    data: EMPTY_TABLE_DATA,
    columnResizeMode: 'onChange',
    getCoreRowModel: getCoreRowModel(),
    state: { columnSizing },
    onColumnSizingChange: handleColumnSizingChange,
  });

  const hasCustomColumnSizing = Object.keys(columnSizing).length > 0;

  // WAI-ARIA tablist keyboard pattern: Left/Right (and Home/End) move BOTH
  // selection and focus between tabs. Order must match the rendered order
  // (verdict tabs, then Banlist only if it's actually rendered).
  const allTabIds = [...VERDICT_SUB_TABS.map((t) => t.id), ...(puedeGestionarBanlist ? ['BANLIST'] : [])];

  const focusTab = (id) => {
    tabRefs.current[id]?.focus();
  };

  const handleTabKeyDown = (event) => {
    const currentIndex = allTabIds.indexOf(subTab);
    if (currentIndex === -1) return;
    let nextId = null;
    if (event.key === 'ArrowRight') {
      nextId = allTabIds[(currentIndex + 1) % allTabIds.length];
    } else if (event.key === 'ArrowLeft') {
      nextId = allTabIds[(currentIndex - 1 + allTabIds.length) % allTabIds.length];
    } else if (event.key === 'Home') {
      nextId = allTabIds[0];
    } else if (event.key === 'End') {
      nextId = allTabIds[allTabIds.length - 1];
    } else {
      return;
    }
    event.preventDefault();
    setSubTab(nextId);
    focusTab(nextId);
  };

  if (!puedeVer) {
    return null;
  }

  const totalTodos = Object.entries(verdictCounts).reduce((sum, [, count]) => sum + count, 0);

  return (
    <div className={styles.container}>
      <Toast toast={toast} onClose={hideToast} />
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h2>Reconciliación GBP vs Tienda Nube</h2>
          <p className={styles.description}>
            Comparación en vivo del reporte GBP (78) contra el catálogo de Tienda Nube. Solo se
            persisten las decisiones humanas (banlist); los veredictos se recalculan en cada carga.
            Hacé click en "Actualizar" para volver a consultar — no se recarga automáticamente al
            navegar entre pestañas o páginas.
          </p>
        </div>
        <div className={styles.headerActions}>
          {lastUpdatedAt && (
            <span className={styles.updatedAt}>
              Actualizado{' '}
              {lastUpdatedAt.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          {mostrarSincronizarTn && (
            <button
              type="button"
              className="btn-tesla ghost sm"
              onClick={sincronizarTn}
              disabled={syncingTn}
              title="Sincroniza el catálogo completo de Tienda Nube (afecta a todos los productos, no solo a esta vista)"
            >
              {syncingTn ? 'Sincronizando catálogo...' : 'Sincronizar catálogo TN'}
            </button>
          )}
          <button type="button" className="btn-tesla outline sm" onClick={cargarReporte} disabled={loading}>
            {loading ? 'Actualizando...' : 'Actualizar'}
          </button>
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}
      {catalogCapHit && (
        <div className={styles.warningBanner}>
          El catálogo de Tienda Nube superó el límite de sincronización interno — la reconciliación
          puede estar incompleta.
        </div>
      )}
      {gbpRowsCapHit && (
        <div className={styles.warningBanner}>
          El reporte GBP superó el límite de filas interno — la reconciliación puede estar incompleta.
        </div>
      )}

      <div className={styles.summaryStrip}>
        {SUMMARY_CARDS.map((card) => (
          <button
            key={card.id}
            type="button"
            className={`${styles.summaryCard} ${
              summaryFilterActive && summaryFilter === card.id ? styles.summaryCardActive : ''
            }`}
            onClick={() => selectSummaryCard(card)}
          >
            <span className={styles.summaryCardLabel}>
              <span className={`${styles.summaryDot} ${styles[card.dot]}`} aria-hidden="true" />
              {card.label}
            </span>
            <span className={styles.summaryValue}>{summaryCounts[card.countKey]}</span>
            <span className={styles.summaryHint}>{card.hint}</span>
          </button>
        ))}
      </div>

      <div className={styles.filterBar}>
        <div className={styles.searchWrap}>
          <Search size={14} className={styles.searchIcon} aria-hidden="true" />
          <input
            type="search"
            className={styles.searchInput}
            placeholder="Buscar por EAN, título o SKU de TN"
            value={searchInput}
            onChange={handleSearchChange}
            aria-label="Buscar por EAN, título o SKU de TN"
          />
        </div>
        <div
          className={styles.subTabBar}
          role="tablist"
          aria-label="Veredictos de reconciliación"
          onKeyDown={handleTabKeyDown}
        >
          {VERDICT_SUB_TABS.map((tab) => (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[tab.id] = el;
              }}
              type="button"
              role="tab"
              id={`tn-tab-${tab.id}`}
              aria-selected={subTab === tab.id}
              aria-controls={TAB_PANEL_ID}
              tabIndex={subTab === tab.id ? 0 : -1}
              className={`${styles.subTab} ${subTab === tab.id ? styles.subTabActive : ''}`}
              onClick={() => setSubTab(tab.id)}
            >
              {tab.label}{' '}
              <span className={styles.subTabCount}>
                ({tab.id === 'todos' ? totalTodos : verdictCounts[tab.id] || 0})
              </span>
            </button>
          ))}
          {puedeGestionarBanlist && (
            <button
              ref={(el) => {
                tabRefs.current.BANLIST = el;
              }}
              type="button"
              role="tab"
              id="tn-tab-BANLIST"
              aria-selected={subTab === 'BANLIST'}
              aria-controls={TAB_PANEL_ID}
              tabIndex={subTab === 'BANLIST' ? 0 : -1}
              className={`${styles.subTab} ${subTab === 'BANLIST' ? styles.subTabActive : ''}`}
              onClick={() => setSubTab('BANLIST')}
            >
              Banlist <span className={styles.subTabCount}>({baneados.length})</span>
            </button>
          )}
        </div>
      </div>

      <div
        role="tabpanel"
        id={TAB_PANEL_ID}
        aria-labelledby={`tn-tab-${subTab}`}
        tabIndex={0}
      >
      {subTab === 'DUPLICADO' && (
        <div className={styles.reviewNotice}>
          Estos grupos requieren revisión humana: puede tratarse de un caso legítimo (por ejemplo, un
          mismo artículo publicado por separado en varios colores). El sistema no preselecciona ni
          recomienda ninguna fila — la decisión de borrar (si corresponde) es siempre del operador.
        </div>
      )}

      {subTab === 'BANLIST' ? (
        <div>
          {baneadosSeleccionados.size > 0 && (
            <div className={styles.banlistActionsBar}>
              <button type="button" className="btn-tesla outline-subtle-success sm" onClick={desbanearSeleccionados}>
                Desbanear seleccionados ({baneadosSeleccionados.size})
              </button>
            </div>
          )}
          {loadingBaneados ? (
            <div className={styles.loadingState}>
              <Loader2 size={24} className={styles.spinner} aria-hidden="true" />
              Cargando banlist...
            </div>
          ) : (
            <table className="table-tesla striped">
              <thead className="table-tesla-head">
                <tr>
                  <th></th>
                  <th>EAN</th>
                  <th>Motivo</th>
                  <th>Usuario</th>
                  <th>Fecha</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {baneados.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="no-data">
                      No hay EANs en la banlist
                    </td>
                  </tr>
                ) : (
                  baneados.map((entry) => (
                    <tr key={entry.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={baneadosSeleccionados.has(entry.id)}
                          onChange={() => toggleSeleccionBaneado(entry.id)}
                          aria-label={`Seleccionar ${entry.ean}`}
                        />
                      </td>
                      <td className={styles.banlistEan}>{entry.ean}</td>
                      <td>
                        {entry.motivo || <span className={styles.noLink}>—</span>}
                      </td>
                      <td>{entry.usuario_nombre}</td>
                      <td>{new Date(entry.fecha_creacion).toLocaleDateString()}</td>
                      <td>
                        <button
                          type="button"
                          className="btn-tesla outline-subtle-success xs"
                          onClick={() => desbanearEan(entry.id)}
                        >
                          Desbanear
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>
      ) : loading ? (
        <div className={styles.loadingState}>
          <Loader2 size={24} className={styles.spinner} aria-hidden="true" />
          Cargando reconciliación...
        </div>
      ) : subTab === 'DUPLICADO' ? (
        <div>
          {filasVisibles.length === 0 ? (
            <p>No hay grupos duplicados para revisar.</p>
          ) : (
            filasVisibles.map((row, idx) => (
              <DuplicateGroupCard key={`${row.ean}-${idx}`} row={row} />
            ))
          )}
          {showPaginator && (
            <Paginador
              page={page}
              totalPages={totalPages}
              rangeStart={rangeStart}
              rangeEnd={rangeEnd}
              total={total}
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
            />
          )}
        </div>
      ) : (
        <>
          {hasCustomColumnSizing && (
            <div className={styles.columnSizingBar}>
              <button type="button" className="btn-tesla ghost sm" onClick={handleResetColumnSizing}>
                Restablecer columnas
              </button>
            </div>
          )}
          <div className="table-container-tesla">
            <table className={`table-tesla striped ${styles.resizableTable}`} style={{ width: table.getTotalSize() }}>
              <colgroup>
                {table.getVisibleLeafColumns().map((col) => (
                  <col key={col.id} style={{ width: col.getSize() }} />
                ))}
              </colgroup>
              <thead className="table-tesla-head">
                <tr>
                  {table.getFlatHeaders().map((h) => {
                    // Driven by the column definition's own `sortable` flag,
                    // not by a hardcoded id — otherwise the flag is dead
                    // config and a future sortable column would silently do
                    // nothing.
                    const isStockColumn = Boolean(h.column.columnDef.sortable);
                    const stockSortDirection = sortState?.column === 'stock' ? sortState.direction : null;
                    return (
                    <th
                      key={h.id}
                      aria-sort={
                        isStockColumn
                          ? stockSortDirection === 'asc'
                            ? 'ascending'
                            : stockSortDirection === 'desc'
                              ? 'descending'
                              : 'none'
                          : undefined
                      }
                    >
                      {isStockColumn ? (
                        <button
                          type="button"
                          className={styles.sortableHeaderBtn}
                          aria-label="Ordenar por stock"
                          onClick={toggleStockSort}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {stockSortDirection === 'asc' ? ' ▲' : stockSortDirection === 'desc' ? ' ▼' : ''}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                      {h.column.getCanResize() && (
                        <span
                          className={`${styles.resizeGrip} ${h.column.getIsResizing() ? styles.resizeGripActive : ''}`}
                          onMouseDown={h.getResizeHandler()}
                          onTouchStart={h.getResizeHandler()}
                          role="separator"
                          aria-orientation="vertical"
                          aria-label={`Redimensionar columna ${h.column.columnDef.header}`}
                        />
                      )}
                    </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {filasVisibles.length === 0 ? (
                  <tr>
                    <td colSpan={COLUMNS.length} className="no-data">
                      No hay filas para este veredicto
                    </td>
                  </tr>
                ) : (
                  filasVisibles.map((row, idx) => (
                    <tr key={`${row.ean}-${idx}`}>
                      {COLUMNS.map((col) =>
                        col.id === 'tn_presence' && row.verdict === 'FALTA_VINCULAR' &&
                        row.product_id != null && row.variant_id != null ? (
                          <td key={col.id}>
                            {col.cell(row)}
                            <div className={styles.matchedIds}>
                              TN product_id: {row.product_id} / variant_id: {row.variant_id}
                            </div>
                          </td>
                        ) : col.id === 'acciones' ? (
                          <td key={col.id}>
                            <RowActionsCell
                              row={row}
                              canBanlist={puedeGestionarBanlist}
                              canPublish={puedeGestionarPublicacion}
                              despublicarTargetProductId={despublicarTargetProductId}
                              onPublicar={setPublishingRow}
                              onBanear={banearEan}
                              confirmingProductId={confirmingProductId}
                              despublicando={despublicando}
                              onStartDespublicarConfirm={setConfirmingProductId}
                              onCancelDespublicarConfirm={() => setConfirmingProductId(null)}
                              onConfirmDespublicar={despublicarProducto}
                            />
                          </td>
                        ) : (
                          <td key={col.id}>{col.cell(row)}</td>
                        )
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {showPaginator && (
            <Paginador
              page={page}
              totalPages={totalPages}
              rangeStart={rangeStart}
              rangeEnd={rangeEnd}
              total={total}
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
            />
          )}
        </>
      )}
      </div>

      {publishingRow && (
        <TnPublishModal
          // Remount per product so title/images (lazy useState initializers)
          // re-init when switching rows — never publish product B with A's data.
          key={publishingRow.ean}
          row={publishingRow}
          isOpen
          onClose={() => setPublishingRow(null)}
          onPublished={(ean) => {
            setPublishingRow(null);
            showToast(`Producto con EAN ${ean} publicado`, 'success');
            cargarReporte();
          }}
        />
      )}
    </div>
  );
}
