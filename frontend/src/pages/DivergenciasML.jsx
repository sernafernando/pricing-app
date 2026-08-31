/**
 * DivergenciasML — operational dashboard for `ml_ops_divergence` rows
 * (slice 7 of ml-ventas-fuente-de-verdad).
 *
 * Consumes GET/PATCH /ml-ventas-ops/divergences (all merged backend, slice
 * 4). Read access needs `ml_ops.ver`; changing a row (state, assignee,
 * note) needs the stricter `ml_ops.gestionar` — a `ml_ops.ver`-only user
 * sees the list with no action controls.
 *
 * Two contract gotchas this page must respect (see design/tasks slice 7):
 *  1. `detected_at` is FIRST detection, not last seen — the detector skips
 *     a divergence whose values haven't changed, so the timestamp does not
 *     advance while the same difference persists. Never label it "última
 *     detección"/"visto por última vez".
 *  2. `window_not_enumerable` rows have NO order (`order_id: null`); the
 *     leaf bounds come back in `window_from`/`window_to` instead. Rendered
 *     distinctly — it means the sweep couldn't read a time window at all,
 *     an infrastructure problem, not a one-sale mismatch.
 *
 * `open` is work to do; `resolved`/`ignored` are closed but NOT final — a
 * recurring divergence reopens itself server-side, so nothing in this page
 * assumes a closed row stays closed.
 */

import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, ShieldAlert } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import ModalTesla from '../components/ModalTesla';
import api from '../services/api';
import styles from './DivergenciasML.module.css';

const PAGE_SIZE = 50;

const KIND_LABELS = {
  missing_in_gbp: 'Falta en GBP',
  missing_in_ml: 'Falta en ML',
  field_mismatch: 'Campo distinto',
  out_of_window_update: 'Actualización fuera de ventana',
  window_not_enumerable: 'Ventana no enumerable',
  unknown: 'Desconocido',
};

const STATE_LABELS = {
  open: 'Abierta',
  acknowledged: 'Reconocida',
  resolved: 'Resuelta',
  ignored: 'Ignorada',
};

const STATE_BADGE_CLASS = {
  open: 'badge-warning',
  acknowledged: 'badge-primary',
  resolved: 'badge-success',
  ignored: 'badge-neutral',
};

const KIND_OPTIONS = Object.keys(KIND_LABELS);
const STATE_OPTIONS = Object.keys(STATE_LABELS);

function formatDate(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

export default function DivergenciasML() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('ml_ops.ver');
  const puedeGestionar = tienePermiso('ml_ops.gestionar');
  const { toast, showToast, hideToast } = useToast(4000);

  const [divergences, setDivergences] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  // 403 (no permission) and 503 (feature switched off) are distinct
  // failures the operator needs to tell apart — never collapsed into one
  // generic error message.
  const [errorKind, setErrorKind] = useState(null); // 'forbidden' | 'disabled' | 'generic' | null

  const [kindFilter, setKindFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');

  const handleKindFilterChange = useCallback((value) => {
    setKindFilter(value);
    setOffset(0);
  }, []);

  const handleStateFilterChange = useCallback((value) => {
    setStateFilter(value);
    setOffset(0);
  }, []);

  // Edit modal (state/assignee/note) — `ml_ops.gestionar` only.
  const [editRow, setEditRow] = useState(null);
  const [editState, setEditState] = useState('');
  const [editAssignedToId, setEditAssignedToId] = useState('');
  const [editNote, setEditNote] = useState('');
  const [saving, setSaving] = useState(false);

  const cargarDivergencias = useCallback(async () => {
    if (!puedeVer) return;
    setLoading(true);
    setErrorKind(null);
    try {
      const params = { limit: PAGE_SIZE, offset };
      if (kindFilter) params.kind = kindFilter;
      if (stateFilter) params.state = stateFilter;
      const { data } = await api.get('/ml-ventas-ops/divergences', { params });
      setDivergences(data.divergences || []);
      setTotal(data.total ?? 0);
    } catch (err) {
      const httpStatus = err?.response?.status;
      if (httpStatus === 403) {
        setErrorKind('forbidden');
      } else if (httpStatus === 503) {
        setErrorKind('disabled');
      } else {
        setErrorKind('generic');
      }
      setDivergences([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [puedeVer, kindFilter, stateFilter, offset]);

  useEffect(() => {
    cargarDivergencias();
  }, [cargarDivergencias]);

  const openEdit = (row) => {
    setEditRow(row);
    setEditState(row.state);
    setEditAssignedToId(row.assigned_to_id != null ? String(row.assigned_to_id) : '');
    setEditNote(row.note || '');
  };

  const closeEdit = () => {
    setEditRow(null);
    setEditState('');
    setEditAssignedToId('');
    setEditNote('');
  };

  const handleSaveEdit = async () => {
    if (!editRow) return;
    setSaving(true);
    try {
      await api.patch(`/ml-ventas-ops/divergences/${editRow.id}`, {
        state: editState,
        assigned_to_id: editAssignedToId.trim() === '' ? null : Number(editAssignedToId.trim()),
        note: editNote.trim() === '' ? null : editNote,
      });
      showToast('Divergencia actualizada', 'success');
      closeEdit();
      cargarDivergencias();
    } catch (err) {
      showToast(err?.response?.data?.detail || 'No se pudo actualizar la divergencia', 'error');
    } finally {
      setSaving(false);
    }
  };

  const outOfWindowCount = divergences.filter((d) => d.kind === 'out_of_window_update').length;

  if (!puedeVer) {
    return null;
  }

  const isFirstPage = offset === 0;
  const isLastPage = offset + PAGE_SIZE >= total;
  const rangeFrom = total === 0 ? 0 : offset + 1;
  const rangeTo = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className={styles.container}>
      <Toast toast={toast} onClose={hideToast} />
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <AlertTriangle size={20} />
          <h1>Divergencias ML Ventas</h1>
        </div>
        <div className={styles.headerActions}>
          <button type="button" className="btn-tesla outline sm" onClick={cargarDivergencias} disabled={loading}>
            {loading ? 'Actualizando...' : 'Actualizar'}
          </button>
        </div>
      </div>

      <p className={styles.description}>
        Diferencias detectadas entre MercadoLibre y GBP. Este es un panel de trabajo: las divergencias
        abiertas requieren acción, y una divergencia cerrada puede reabrirse sola si vuelve a repetirse.
      </p>

      {errorKind === 'forbidden' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> No tenés permiso para ver las divergencias (ml_ops.ver).
        </div>
      )}
      {errorKind === 'disabled' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> La fuente de verdad de ventas ML está deshabilitada actualmente.
        </div>
      )}
      {errorKind === 'generic' && (
        <div className={styles.errorBar}>
          <ShieldAlert size={16} /> Error al cargar las divergencias.
        </div>
      )}

      {outOfWindowCount > 0 && (
        <div className={styles.infoBar}>
          {outOfWindowCount} actualización(es) fuera de la ventana de sincronización en esta página —
          órdenes que ML reportó como cambiadas pero que quedan deliberadamente fuera del barrido.
        </div>
      )}

      <div className={styles.filtersBar}>
        <select
          className={styles.select}
          value={kindFilter}
          onChange={(e) => handleKindFilterChange(e.target.value)}
        >
          <option value="">Todos los tipos</option>
          {KIND_OPTIONS.map((kind) => (
            <option key={kind} value={kind}>{KIND_LABELS[kind]}</option>
          ))}
        </select>
        <select
          className={styles.select}
          value={stateFilter}
          onChange={(e) => handleStateFilterChange(e.target.value)}
        >
          <option value="">Todos los estados</option>
          {STATE_OPTIONS.map((state) => (
            <option key={state} value={state}>{STATE_LABELS[state]}</option>
          ))}
        </select>
      </div>

      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead>
            <tr>
              <th>Tipo</th>
              <th>Orden / Ventana</th>
              <th>Campo</th>
              <th>Valor ML</th>
              <th>Valor GBP</th>
              <th>Estado</th>
              <th>Detectada</th>
              <th>Asignada a</th>
              <th>Nota</th>
              {puedeGestionar && <th>Acciones</th>}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className={styles.loadingCell} colSpan={puedeGestionar ? 10 : 9}>
                  Cargando divergencias...
                </td>
              </tr>
            ) : divergences.length === 0 ? (
              <tr>
                <td className={styles.emptyCell} colSpan={puedeGestionar ? 10 : 9}>
                  No hay divergencias para mostrar
                </td>
              </tr>
            ) : (
              divergences.map((row) => {
                const isUnenumerable = row.kind === 'window_not_enumerable';
                return (
                  <tr key={row.id} className={isUnenumerable ? styles.unenumerableRow : undefined}>
                    <td>{KIND_LABELS[row.kind] || row.kind}</td>
                    <td>
                      {isUnenumerable ? (
                        <span className={styles.windowBounds} title="No se pudo enumerar esta ventana">
                          Ventana: {row.window_from || '—'} a {row.window_to || '—'}
                        </span>
                      ) : (
                        row.order_id ?? '—'
                      )}
                    </td>
                    <td>{isUnenumerable ? '—' : (row.field ?? '—')}</td>
                    <td>{isUnenumerable ? '—' : (row.ml_value ?? '—')}</td>
                    <td>{isUnenumerable ? '—' : (row.gbp_value ?? '—')}</td>
                    <td>
                      <span className={`badge ${STATE_BADGE_CLASS[row.state] || 'badge-neutral'}`}>
                        {STATE_LABELS[row.state] || row.state}
                      </span>
                    </td>
                    <td title="Primera detección — no avanza mientras la misma diferencia persista">
                      {formatDate(row.detected_at)}
                    </td>
                    <td>{row.assigned_to_id ?? '—'}</td>
                    <td className={styles.cellNote}>{row.note || '—'}</td>
                    {puedeGestionar && (
                      <td>
                        <button
                          type="button"
                          className="btn-tesla outline-subtle-primary sm"
                          onClick={() => openEdit(row)}
                        >
                          Gestionar
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.paginationBar}>
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
          disabled={isFirstPage}
        >
          Anterior
        </button>
        <span>
          mostrando {rangeFrom}-{rangeTo} de {total} divergencias
        </span>
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
          disabled={isLastPage}
        >
          Siguiente
        </button>
      </div>

      <ModalTesla
        isOpen={Boolean(editRow)}
        onClose={closeEdit}
        title="Gestionar divergencia"
        subtitle={editRow ? `#${editRow.id} — ${KIND_LABELS[editRow.kind] || editRow.kind}` : ''}
        size="sm"
        footer={
          <>
            <button type="button" className="btn-tesla ghost sm" onClick={closeEdit} disabled={saving}>
              Cancelar
            </button>
            <button type="button" className="btn-tesla primary sm" onClick={handleSaveEdit} disabled={saving}>
              {saving ? 'Guardando...' : 'Guardar'}
            </button>
          </>
        }
      >
        <div className={styles.editBody}>
          <label>
            Estado
            <select
              className={styles.select}
              value={editState}
              onChange={(e) => setEditState(e.target.value)}
            >
              {STATE_OPTIONS.map((state) => (
                <option key={state} value={state}>{STATE_LABELS[state]}</option>
              ))}
            </select>
          </label>
          <label>
            Asignada a (ID de usuario)
            <input
              type="number"
              className={styles.configInput}
              value={editAssignedToId}
              onChange={(e) => setEditAssignedToId(e.target.value)}
              placeholder="sin asignar"
            />
          </label>
          <label>
            Nota
            <textarea
              className={styles.editTextarea}
              value={editNote}
              onChange={(e) => setEditNote(e.target.value)}
              rows={4}
            />
          </label>
        </div>
      </ModalTesla>
    </div>
  );
}
