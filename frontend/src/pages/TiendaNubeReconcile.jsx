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
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import api from '../services/api';
import styles from './TiendaNubeReconcile.module.css';

export const COLUMN_SIZING_STORAGE_KEY = 'tnreconcile:colsizing:reporte';

// Slice 1's report is a bounded internal view over a single ERP export
// report — request one generously-sized page instead of building a full
// pager UI (fast-follow if the report ever exceeds this size; see the
// endpoint's TN_PRODUCTOS_QUERY_CAP scaling note).
const REPORT_PAGE_SIZE = 200;

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
// verdict — it's the banned-EAN management view (added to complete the
// ban/unban cycle: a mis-banned EAN must be recoverable from the UI).
const VERDICT_SUB_TABS = [
  { id: 'todos', label: 'Todos' },
  { id: 'FALTA_VINCULAR', label: 'Falta vincular' },
  { id: 'FALTA_PUBLICAR', label: 'Falta publicar' },
  { id: 'MAL_VINCULADO', label: 'Mal vinculado' },
  { id: 'MAL_PUBLICADO', label: 'Mal publicado' },
  { id: 'DUPLICADO', label: 'Duplicado' },
];

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
        {VERDICT_LABELS[row.verdict] || row.verdict}
      </span>
    ),
  },
  { id: 'despublicar', header: 'Despublicar', size: 110, cell: (row) => (row.despublicar ? 'Sí' : '—') },
  { id: 'matches', header: 'Coincidencias TN', size: 260, cell: null }, // rendered specially — carries the ban action
];

const EMPTY_TABLE_DATA = [];

export default function TiendaNubeReconcile() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('admin.ver_tn_reconciliacion');
  const puedeGestionarBanlist = tienePermiso('admin.gestionar_tn_reconcile_banlist');
  const { toast, showToast, hideToast } = useToast(4000);

  const [reporte, setReporte] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [subTab, setSubTab] = useState('todos');

  // Banlist view state
  const [baneados, setBaneados] = useState([]);
  const [loadingBaneados, setLoadingBaneados] = useState(false);
  const [baneadosSeleccionados, setBaneadosSeleccionados] = useState(new Set());

  const cargarReporte = useCallback(async () => {
    if (!puedeVer) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.get('/tienda-nube-reconcile/reporte', { params: { page_size: REPORT_PAGE_SIZE } });
      setReporte(response.data?.items || []);
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

  useEffect(() => {
    cargarReporte();
  }, [cargarReporte]);

  useEffect(() => {
    if (subTab === 'BANLIST') {
      cargarBaneados();
    }
  }, [subTab, cargarBaneados]);

  const banearEan = useCallback(
    async (ean) => {
      if (!puedeGestionarBanlist) return;
      try {
        await api.post('/tienda-nube-reconcile/banear', { ean });
        showToast(`EAN ${ean} agregado a la banlist`, 'success');
        cargarReporte();
      } catch (err) {
        showToast(err?.response?.data?.detail || 'Error al banear el EAN', 'error');
      }
    },
    [puedeGestionarBanlist, cargarReporte, showToast]
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
        showToast(err?.response?.data?.detail || 'Error al desbanear el EAN', 'error');
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
    try {
      for (const banlistId of ids) {
        await api.post('/tienda-nube-reconcile/desbanear', { banlist_id: banlistId });
      }
      showToast(`${ids.length} EAN(s) desbaneados exitosamente`, 'success');
      setBaneadosSeleccionados(new Set());
      cargarBaneados();
      cargarReporte();
    } catch (err) {
      showToast(err?.response?.data?.detail || 'Error al desbanear masivamente', 'error');
    }
  }, [baneadosSeleccionados, cargarBaneados, cargarReporte, showToast]);

  const filasVisibles =
    subTab === 'todos' || subTab === 'BANLIST'
      ? reporte.filter((r) => r.verdict !== 'OK')
      : reporte.filter((r) => r.verdict === subTab);

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

  return (
    <div className={styles.container}>
      <Toast toast={toast} onClose={hideToast} />
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h2>Reconciliación GBP vs Tienda Nube</h2>
          <p className={styles.description}>
            Comparación en vivo del reporte GBP (78) contra el catálogo de Tienda Nube. Solo se
            persisten las decisiones humanas (banlist); los veredictos se recalculan en cada carga.
          </p>
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.subTabBar}>
        {VERDICT_SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`${styles.subTab} ${subTab === tab.id ? styles.subTabActive : ''}`}
            onClick={() => setSubTab(tab.id)}
          >
            {tab.label} ({tab.id === 'todos' ? reporte.filter((r) => r.verdict !== 'OK').length : reporte.filter((r) => r.verdict === tab.id).length})
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
                      <th>activo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.tn_matches.map((tn) => (
                      <tr key={`${tn.product_id}-${tn.variant_id}`}>
                        <td>product_id: {tn.product_id}</td>
                        <td>variant_id: {tn.variant_id}</td>
                        <td>{tn.variant_sku}</td>
                        <td>{tn.activo ? 'Sí' : 'No'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))
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
                    <th key={h.id} style={{ position: 'relative' }}>
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
                                className="btn-tesla ghost sm"
                                onClick={() => banearEan(row.ean)}
                                style={{ marginLeft: 8 }}
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
        </>
      )}
    </div>
  );
}
