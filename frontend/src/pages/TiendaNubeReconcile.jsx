/**
 * TiendaNubeReconcile — read-only reconciliation view (Slice 1).
 *
 * Joins GBP export report 78 against the Tienda Nube catalog live (verdicts
 * are never persisted, only ban-list decisions are). Surfaces the verdict
 * taxonomy as sub-tabs, with MAL_PUBLICADO and DUPLICADO as first-class
 * dedicated views per the spec's Data-Quality Anomaly Surfacing requirement.
 *
 * DUPLICADO groups are presented as "needs human review", never as an error,
 * and MUST NOT pre-select/highlight/recommend any conflicting row — the
 * human, not the system, decides (see spec: DUPLICADO Verdict requirement).
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import styles from './TiendaNubeReconcile.module.css';

export const COLUMN_SIZING_STORAGE_KEY = 'tnreconcile:colsizing:reporte';

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
// (everything except OK, which is not an anomaly).
const SUB_TABS = [
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

const COLUMNS = [
  { id: 'ean', header: 'EAN', size: 140 },
  { id: 'verdict', header: 'Veredicto', size: 150 },
  { id: 'despublicar', header: 'Despublicar', size: 110 },
  { id: 'matches', header: 'Coincidencias TN', size: 260 },
];

const EMPTY_TABLE_DATA = [];

export default function TiendaNubeReconcile() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('admin.ver_tn_reconciliacion');
  const puedeGestionarBanlist = tienePermiso('admin.gestionar_tn_reconcile_banlist');

  const [reporte, setReporte] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [subTab, setSubTab] = useState('todos');

  const cargarReporte = useCallback(async () => {
    if (!puedeVer) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.get('/tienda-nube-reconcile/reporte');
      setReporte(response.data || []);
    } catch (err) {
      setError(err?.response?.data?.error?.message || err?.message || 'No se pudo cargar la reconciliación');
    } finally {
      setLoading(false);
    }
  }, [puedeVer]);

  useEffect(() => {
    cargarReporte();
  }, [cargarReporte]);

  const banearEan = useCallback(
    async (ean) => {
      if (!puedeGestionarBanlist) return;
      await api.post('/tienda-nube-reconcile/banear', { ean });
      cargarReporte();
    },
    [puedeGestionarBanlist, cargarReporte]
  );

  const filasVisibles = useMemo(() => {
    if (subTab === 'todos') return reporte.filter((r) => r.verdict !== 'OK');
    return reporte.filter((r) => r.verdict === subTab);
  }, [reporte, subTab]);

  const duplicateGroups = useMemo(() => {
    if (subTab !== 'DUPLICADO') return [];
    // Group by ean+tnr pair context isn't needed here — each row already
    // carries its own tn_matches; grouping visually by shared tn_matches
    // signature keeps rows that reference the same conflict together.
    return filasVisibles;
  }, [filasVisibles, subTab]);

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
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h1>Reconciliación GBP vs Tienda Nube</h1>
          <p className={styles.description}>
            Comparación en vivo del reporte GBP (78) contra el catálogo de Tienda Nube. Solo se
            persisten las decisiones humanas (banlist); los veredictos se recalculan en cada carga.
          </p>
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.subTabBar}>
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`${styles.subTab} ${subTab === tab.id ? styles.subTabActive : ''}`}
            onClick={() => setSubTab(tab.id)}
          >
            {tab.label} ({tab.id === 'todos' ? reporte.filter((r) => r.verdict !== 'OK').length : reporte.filter((r) => r.verdict === tab.id).length})
          </button>
        ))}
      </div>

      {subTab === 'DUPLICADO' && (
        <div className={styles.reviewNotice}>
          Estos grupos requieren revisión humana: puede tratarse de un caso legítimo (por ejemplo, un
          mismo artículo publicado por separado en varios colores). El sistema no preselecciona ni
          recomienda ninguna fila — la decisión de borrar (si corresponde) es siempre del operador.
        </div>
      )}

      {loading ? (
        <div>Cargando reconciliación...</div>
      ) : subTab === 'DUPLICADO' ? (
        <div>
          {duplicateGroups.length === 0 ? (
            <p>No hay grupos duplicados para revisar.</p>
          ) : (
            duplicateGroups.map((row, idx) => (
              <div key={`${row.ean}-${idx}`} className={styles.duplicateGroup}>
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
                      <td>{row.ean}</td>
                      <td>
                        <span className={`${styles.badge} ${styles[VERDICT_BADGE_CLASS[row.verdict]] || ''}`}>
                          {VERDICT_LABELS[row.verdict] || row.verdict}
                        </span>
                      </td>
                      <td>{row.despublicar ? 'Sí' : '—'}</td>
                      <td>
                        {row.tn_matches.length === 0
                          ? '—'
                          : row.tn_matches.map((tn) => tn.variant_sku).join(', ')}
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
