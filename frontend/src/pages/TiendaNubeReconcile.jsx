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
 *
 * Page/orchestrator scope (PR-6 pattern): this file owns state, data
 * fetching and event handlers; markup for each render branch lives in
 * `src/components/tn-reconcile/` (ReconcileSummaryStrip, ReconcileFilterBar,
 * ReconcileTable, ReconcileDuplicadoPanel, BanlistTable and the cell
 * components) — continuing the decomposition PR-6 already established.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import { Loader2 } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import TnPublishModal from '../components/tn-publisher/TnPublishModal';
import api from '../services/api';
import {
  selectTabItems,
  computeSummaryCounts,
  matchesSearch,
  matchesSummaryFilter,
} from './tiendaNubeReconcileHelpers';
import ReconcileSummaryStrip from '../components/tn-reconcile/ReconcileSummaryStrip';
import ReconcileFilterBar from '../components/tn-reconcile/ReconcileFilterBar';
import ReconcileTable from '../components/tn-reconcile/ReconcileTable';
import ExcepcionModal from '../components/tn-reconcile/ExcepcionModal';
import ReconcileDuplicadoPanel from '../components/tn-reconcile/ReconcileDuplicadoPanel';
import BanlistTable from '../components/tn-reconcile/BanlistTable';
import { COLUMNS } from '../components/tn-reconcile/reconcileColumns';
import { VERDICT_SUB_TABS } from '../components/tn-reconcile/reconcileSubTabs';
import { COLUMN_SIZING_STORAGE_KEY, loadColumnSizing, saveColumnSizing, sortItems } from './tiendaNubeReconcileTableHelpers';
import styles from './TiendaNubeReconcile.module.css';

export { COLUMN_SIZING_STORAGE_KEY };

const PAGE_SIZE = 50;

// Round 7, item 3: only the ACTIVE tab's content is ever rendered (one
// panel at a time), so every tab's `aria-controls` must point at the SAME
// single, always-present panel id — not a per-tab id that only exists
// while that specific tab happens to be selected. Pointing every tab at
// this one stable id means `aria-controls` never dangles for an inactive
// tab; `aria-labelledby` on the panel itself still tracks which tab is
// currently "in control" of it.
const TAB_PANEL_ID = 'tn-panel';

const EMPTY_TABLE_DATA = [];

export default function TiendaNubeReconcile() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('admin.ver_tn_reconciliacion');
  const puedeGestionarBanlist = tienePermiso('admin.gestionar_tn_reconcile_banlist');
  // Its OWN permission, not the ban list's: accepting an exception
  // silences a data-quality anomaly, a more consequential call than
  // deciding not to publish something.
  const puedeGestionarExcepciones = tienePermiso('admin.gestionar_tn_reconcile_excepciones');
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

  // Accepting an anomaly as intentional asks for a reason first — an
  // exception with no stated reason is indistinguishable from someone
  // silencing an alert they did not understand. Removing one does not:
  // undoing a silence needs no justification.
  const [excepcionRow, setExcepcionRow] = useState(null);

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

  const aceptarExcepcion = useCallback(
    async (row, motivo) => {
      if (!puedeGestionarExcepciones) return;
      try {
        await api.post('/tienda-nube-reconcile/excepciones/aceptar', {
          // Echoed back verbatim: an exception can only exist for a
          // situation the server itself computed.
          evidencia: row.evidencia,
          ean: row.ean,
          verdict: row.verdict,
          motivo,
        });
        showToast('Excepción aceptada', 'success');
        setExcepcionRow(null);
        cargarReporte();
      } catch (err) {
        showToast(err?.response?.data?.error?.message || 'No se pudo aceptar la excepción', 'error');
      }
    },
    [puedeGestionarExcepciones, cargarReporte, showToast]
  );

  const quitarExcepcion = useCallback(
    async (row) => {
      if (!puedeGestionarExcepciones) return;
      try {
        const listado = await api.get('/tienda-nube-reconcile/excepciones');
        const match = (listado.data || []).find((e) => e.evidencia === row.evidencia);
        if (!match) {
          showToast('Esa excepción ya no existe', 'error');
          cargarReporte();
          return;
        }
        await api.post('/tienda-nube-reconcile/excepciones/quitar', { excepcion_id: match.id });
        showToast('Excepción quitada', 'success');
        cargarReporte();
      } catch (err) {
        showToast(err?.response?.data?.error?.message || 'No se pudo quitar la excepción', 'error');
      }
    },
    [puedeGestionarExcepciones, cargarReporte, showToast]
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

  const [columnSizing, setColumnSizingState] = useState(() => loadColumnSizing(COLUMNS));
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

      <ReconcileSummaryStrip
        summaryCounts={summaryCounts}
        summaryFilterActive={summaryFilterActive}
        summaryFilter={summaryFilter}
        onSelectCard={selectSummaryCard}
      />

      <ReconcileFilterBar
        searchInput={searchInput}
        onSearchChange={handleSearchChange}
        subTab={subTab}
        setSubTab={setSubTab}
        tabRefs={tabRefs}
        onTabKeyDown={handleTabKeyDown}
        totalTodos={totalTodos}
        verdictCounts={verdictCounts}
        puedeGestionarBanlist={puedeGestionarBanlist}
        baneadosCount={baneados.length}
        tabPanelId={TAB_PANEL_ID}
      />

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
        <BanlistTable
          baneados={baneados}
          loadingBaneados={loadingBaneados}
          baneadosSeleccionados={baneadosSeleccionados}
          toggleSeleccionBaneado={toggleSeleccionBaneado}
          desbanearSeleccionados={desbanearSeleccionados}
          desbanearEan={desbanearEan}
        />
      ) : loading ? (
        <div className={styles.loadingState}>
          <Loader2 size={24} className={styles.spinner} aria-hidden="true" />
          Cargando reconciliación...
        </div>
      ) : subTab === 'DUPLICADO' ? (
        <ReconcileDuplicadoPanel
          filasVisibles={filasVisibles}
          showPaginator={showPaginator}
          page={page}
          totalPages={totalPages}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          total={total}
          onPrevPage={() => setPage((p) => Math.max(1, p - 1))}
          onNextPage={() => setPage((p) => Math.min(totalPages, p + 1))}
        />
      ) : (
        <ReconcileTable
          table={table}
          filasVisibles={filasVisibles}
          sortState={sortState}
          toggleStockSort={toggleStockSort}
          hasCustomColumnSizing={hasCustomColumnSizing}
          handleResetColumnSizing={handleResetColumnSizing}
          canBanlist={puedeGestionarBanlist}
          canExcepciones={puedeGestionarExcepciones}
          canPublish={puedeGestionarPublicacion}
          onPublicar={setPublishingRow}
          onBanear={banearEan}
          onAceptarExcepcion={(row) => setExcepcionRow(row)}
          onQuitarExcepcion={quitarExcepcion}
          confirmingProductId={confirmingProductId}
          despublicando={despublicando}
          onStartDespublicarConfirm={setConfirmingProductId}
          onCancelDespublicarConfirm={() => setConfirmingProductId(null)}
          onConfirmDespublicar={despublicarProducto}
          showPaginator={showPaginator}
          page={page}
          totalPages={totalPages}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          total={total}
          onPrevPage={() => setPage((p) => Math.max(1, p - 1))}
          onNextPage={() => setPage((p) => Math.min(totalPages, p + 1))}
        />
      )}
      </div>

      {excepcionRow && (
        <ExcepcionModal
          row={excepcionRow}
          onCancel={() => setExcepcionRow(null)}
          onConfirm={aceptarExcepcion}
        />
      )}

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
