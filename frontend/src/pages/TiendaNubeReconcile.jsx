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
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import api from '../services/api';
import styles from './TiendaNubeReconcile.module.css';

export const COLUMN_SIZING_STORAGE_KEY = 'tnreconcile:colsizing:reporte';

const PAGE_SIZE = 50;

const VERDICT_LABELS = {
  FALTA_VINCULAR: 'Falta vincular',
  FALTA_PUBLICAR: 'Falta publicar',
  MAL_VINCULADO: 'Mal vinculado',
  MAL_PUBLICADO: 'Mal publicado',
  DUPLICADO: 'Duplicado',
  OK: 'OK',
};

const VERDICT_BADGE_CLASS = {
  FALTA_VINCULAR: 'badgeInfo',
  FALTA_PUBLICAR: 'badgeWarning',
  MAL_VINCULADO: 'badgeWarning',
  MAL_PUBLICADO: 'badgeDanger',
  DUPLICADO: 'badgeDanger',
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
];

function verdictLabelFor(verdictId) {
  return VERDICT_LABELS[verdictId] || verdictId;
}

// Fail-safe persistence — absent/corrupt/disabled localStorage MUST never
// throw (mirrors MLQuestions.jsx's loadColumnSizing/saveColumnSizing).
function loadColumnSizing() {
  try {
    const parsed = JSON.parse(localStorage.getItem(COLUMN_SIZING_STORAGE_KEY) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
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
const COLUMNS = [
  { id: 'ean', header: 'EAN', size: 140, cell: (row) => row.ean },
  {
    id: 'verdict',
    header: 'Veredicto',
    size: 150,
    cell: (row) => (
      <span className={`${styles.badge} ${styles[VERDICT_BADGE_CLASS[row.verdict]] || ''}`}>
        {verdictLabelFor(row.verdict)}
      </span>
    ),
  },
  { id: 'despublicar', header: 'Despublicar', size: 110, cell: (row) => (row.despublicar ? 'Sí' : '—') },
  { id: 'matches', header: 'Coincidencias TN', size: 260, cell: null }, // rendered specially — carries the ban action
];

// Tri-state Sí/No/Desconocido — `published` is nullable (rows not yet
// re-synced with TN's real field are genuinely unknown, never "No").
function publishedLabel(published) {
  if (published === true) return 'Sí';
  if (published === false) return 'No';
  return 'Desconocido';
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

export default function TiendaNubeReconcile() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('admin.ver_tn_reconciliacion');
  const puedeGestionarBanlist = tienePermiso('admin.gestionar_tn_reconcile_banlist');
  const { toast, showToast, hideToast } = useToast(4000);

  const [reporte, setReporte] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [subTab, setSubTabState] = useState('todos');
  const [page, setPage] = useState(1);
  const [verdictCounts, setVerdictCounts] = useState({});
  const [catalogCapHit, setCatalogCapHit] = useState(false);

  // Changing sub-tab always resets to page 1 in the same event.
  const setSubTab = useCallback((tab) => {
    setSubTabState(tab);
    setPage(1);
  }, []);

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
    if (subTab === 'todos' || subTab === 'BANLIST') return reporte;
    return reporte.filter((r) => r.verdict === subTab);
  }, [reporte, subTab]);

  const total = currentTabItems.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const showPaginator = total > PAGE_SIZE;
  const rangeStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, total);
  const filasVisibles = useMemo(
    () => currentTabItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [currentTabItems, page]
  );

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
        <button type="button" className="btn-tesla outline sm" onClick={cargarReporte} disabled={loading}>
          {loading ? 'Actualizando...' : 'Actualizar'}
        </button>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}
      {catalogCapHit && (
        <div className={styles.errorBanner}>
          El catálogo de Tienda Nube superó el límite de sincronización interno — la reconciliación
          puede estar incompleta.
        </div>
      )}

      <div className={styles.subTabBar}>
        {VERDICT_SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`${styles.subTab} ${subTab === tab.id ? styles.subTabActive : ''}`}
            onClick={() => setSubTab(tab.id)}
          >
            {tab.label} ({tab.id === 'todos' ? totalTodos : verdictCounts[tab.id] || 0})
          </button>
        ))}
        {puedeGestionarBanlist && (
          <button
            type="button"
            className={`${styles.subTab} ${subTab === 'BANLIST' ? styles.subTabActive : ''}`}
            onClick={() => setSubTab('BANLIST')}
          >
            Banlist ({baneados.length})
          </button>
        )}
      </div>

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
            <div className={styles.columnSizingBar}>
              <button type="button" className="btn-tesla outline-subtle-success sm" onClick={desbanearSeleccionados}>
                Desbanear seleccionados ({baneadosSeleccionados.size})
              </button>
            </div>
          )}
          {loadingBaneados ? (
            <div>Cargando banlist...</div>
          ) : (
            <table className="table-tesla striped">
              <thead>
                <tr>
                  <th></th>
                  <th>EAN</th>
                  <th>Motivo</th>
                  <th>Usuario</th>
                  <th>Fecha</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
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
                      <td>{entry.ean}</td>
                      <td>{entry.motivo || '—'}</td>
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
        <div>Cargando reconciliación...</div>
      ) : subTab === 'DUPLICADO' ? (
        <div>
          {filasVisibles.length === 0 ? (
            <p>No hay grupos duplicados para revisar.</p>
          ) : (
            filasVisibles.map((row, idx) => (
              <div key={`${row.ean}-${idx}`} className={styles.duplicateGroup} data-testid="duplicado-group">
                <div className={styles.duplicateGroupHeader}>
                  EAN GBP: {row.ean} — {row.tn_matches.length} coincidencias TN en conflicto
                </div>
                <table className="table-tesla striped">
                  <thead>
                    <tr>
                      <th>product_id</th>
                      <th>variant_id</th>
                      <th>variant_sku</th>
                      <th>Publicado en TN</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.tn_matches.map((tn) => (
                      <tr key={`${tn.product_id}-${tn.variant_id}`}>
                        <td>product_id: {tn.product_id}</td>
                        <td>variant_id: {tn.variant_id}</td>
                        <td>{tn.variant_sku}</td>
                        <td>{publishedLabel(tn.published)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
                  {table.getFlatHeaders().map((h) => (
                    <th key={h.id}>
                      {flexRender(h.column.columnDef.header, h.getContext())}
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
                  ))}
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
                        col.id === 'matches' ? (
                          <td key={col.id}>
                            {row.tn_matches.length === 0 ? '—' : row.tn_matches.map((tn) => tn.variant_sku).join(', ')}
                            {puedeGestionarBanlist && row.verdict === 'FALTA_PUBLICAR' && (
                              <button
                                type="button"
                                className={`btn-tesla ghost sm ${styles.btnSpaced}`}
                                onClick={() => banearEan(row.ean)}
                              >
                                Banear
                              </button>
                            )}
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
  );
}
