import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Undo2, X } from 'lucide-react';
import api from '../../services/api';
import useCCProveedor from '../../hooks/useCCProveedor';
import { usePermisos } from '../../contexts/PermisosContext';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import styles from './PanelImputaciones.module.css';

/**
 * PanelImputaciones — Panel standalone para gestionar imputaciones de compras.
 *
 * COMPRAS-7.5 — Antes sólo se accedía desde `ModalPedidoDetalle` (read-only).
 * Ahora se puede:
 *   - Filtrar por proveedor / origen_tipo / destino_tipo / rango de fechas.
 *   - Desimputar (reversal append-only — D9 del design).
 *
 * Reimputación: el flujo queda en las UIs existentes (OP/pedido detalle)
 * porque requiere contexto de imputación destino específico — exponerlo
 * suelto sería confuso. El panel es foco: ver + desimputar.
 */

const TIPOS = ['orden_pago', 'pedido_compra', 'cc_saldo_a_favor'];

const INITIAL_FILTERS = {
  proveedor_id: null,
  origen_tipo: '',
  destino_tipo: '',
  desde: '',
  hasta: '',
};

const fmtDateTime = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

const fmtMoney = (value, moneda) => {
  if (value === null || value === undefined) return '—';
  const prefix = moneda === 'USD' ? 'US$' : '$';
  const num = Number(value) || 0;
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export default function PanelImputaciones() {
  // Desestructurar funciones memoizadas para evitar loop en useEffect/useCallback.
  const { listarImputaciones, loading: ccLoading } = useCCProveedor();
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('administracion.gestionar_ordenes_compra');

  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 50 });
  const [localError, setLocalError] = useState(null);
  const [confirmarDesimp, setConfirmarDesimp] = useState(null); // imputacion row o null
  const [motivoDesimp, setMotivoDesimp] = useState('');
  const [enviando, setEnviando] = useState(false);

  const fetchData = useCallback(
    async (page = 1) => {
      setLocalError(null);
      try {
        const params = { page, page_size: 50 };
        if (filters.proveedor_id) params.proveedor_id = filters.proveedor_id;
        if (filters.origen_tipo) params.origen_tipo = filters.origen_tipo;
        if (filters.destino_tipo) params.destino_tipo = filters.destino_tipo;
        if (filters.desde) params.desde = filters.desde;
        if (filters.hasta) params.hasta = filters.hasta;
        const result = await listarImputaciones(params);
        setData(result);
      } catch (err) {
        setLocalError(err.response?.data?.detail || 'Error al listar imputaciones.');
      }
    },
    [filters, listarImputaciones],
  );

  useEffect(() => {
    fetchData(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const aplicarFiltros = () => {
    fetchData(1);
  };

  const limpiarFiltros = () => {
    setFilters(INITIAL_FILTERS);
    // esperamos al próximo tick usando un setTimeout (fetchData usa el closure del state actual)
    setTimeout(() => fetchData(1), 0);
  };

  const confirmarDesimputar = async () => {
    if (!confirmarDesimp) return;
    setEnviando(true);
    try {
      await api.post(`/administracion/compras/imputaciones/${confirmarDesimp.id}/desimputar`, {
        motivo: motivoDesimp || 'Desimputación manual desde panel',
      });
      setConfirmarDesimp(null);
      setMotivoDesimp('');
      await fetchData(data.page);
    } catch (err) {
      setLocalError(err.response?.data?.detail || 'Error al desimputar.');
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <h3 className={styles.title}>Imputaciones</h3>
        <button
          type="button"
          className={styles.refreshBtn}
          onClick={() => fetchData(data.page)}
          aria-label="Refrescar"
          disabled={ccLoading}
        >
          <RefreshCw size={14} /> Refrescar
        </button>
      </div>

      {/* ── Filtros ─────────────────────────────────────────────── */}
      <div className={styles.filtersGrid}>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Proveedor</label>
          <ProveedorComprasAutocomplete
            value={filters.proveedor_id}
            onChange={(id) => setFilters((f) => ({ ...f, proveedor_id: id }))}
          />
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Origen</label>
          <select
            className={styles.select}
            value={filters.origen_tipo}
            onChange={(e) => setFilters((f) => ({ ...f, origen_tipo: e.target.value }))}
          >
            <option value="">Todos</option>
            {TIPOS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Destino</label>
          <select
            className={styles.select}
            value={filters.destino_tipo}
            onChange={(e) => setFilters((f) => ({ ...f, destino_tipo: e.target.value }))}
          >
            <option value="">Todos</option>
            {TIPOS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Desde</label>
          <input
            type="date"
            className={styles.input}
            value={filters.desde}
            onChange={(e) => setFilters((f) => ({ ...f, desde: e.target.value }))}
          />
        </div>

        <div className={styles.filterGroup}>
          <label className={styles.filterLabel}>Hasta</label>
          <input
            type="date"
            className={styles.input}
            value={filters.hasta}
            onChange={(e) => setFilters((f) => ({ ...f, hasta: e.target.value }))}
          />
        </div>

        <div className={styles.filterActions}>
          <button type="button" className={styles.btnPrimary} onClick={aplicarFiltros} disabled={ccLoading}>
            Aplicar
          </button>
          <button type="button" className={styles.btnGhost} onClick={limpiarFiltros} disabled={ccLoading}>
            Limpiar
          </button>
        </div>
      </div>

      {localError && <div className={styles.errorBanner}>{localError}</div>}

      {/* ── Tabla ────────────────────────────────────────────────── */}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>ID</th>
              <th>Fecha</th>
              <th>Proveedor</th>
              <th>Origen</th>
              <th>Destino</th>
              <th>Monto</th>
              <th>Reversal de</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 && (
              <tr>
                <td colSpan={8} className={styles.emptyRow}>
                  {ccLoading ? 'Cargando...' : 'Sin imputaciones para los filtros aplicados.'}
                </td>
              </tr>
            )}
            {data.items.map((imp) => (
              <tr key={imp.id}>
                <td>{imp.id}</td>
                <td>{fmtDateTime(imp.created_at)}</td>
                <td>{imp.proveedor_id}</td>
                <td>
                  <span className={styles.pill}>{imp.origen_tipo}</span>
                  <span className={styles.pillId}>#{imp.origen_id}</span>
                </td>
                <td>
                  <span className={styles.pill}>{imp.destino_tipo}</span>
                  <span className={styles.pillId}>#{imp.destino_id}</span>
                </td>
                <td>{fmtMoney(imp.monto, imp.moneda)}</td>
                <td>{imp.reversal_de_id ? `#${imp.reversal_de_id}` : '—'}</td>
                <td>
                  {puedeGestionar && !imp.reversal_de_id && (
                    <button
                      type="button"
                      className={styles.btnAction}
                      onClick={() => {
                        setConfirmarDesimp(imp);
                        setMotivoDesimp('');
                      }}
                      title="Desimputar"
                    >
                      <Undo2 size={14} /> Desimputar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.total > 0 && (
        <div className={styles.paginator}>
          <span>
            {data.items.length} de {data.total} (página {data.page})
          </span>
          <div className={styles.pagerBtns}>
            <button
              type="button"
              className={styles.btnGhost}
              onClick={() => fetchData(Math.max(1, data.page - 1))}
              disabled={data.page === 1 || ccLoading}
            >
              Anterior
            </button>
            <button
              type="button"
              className={styles.btnGhost}
              onClick={() => fetchData(data.page + 1)}
              disabled={data.page * data.page_size >= data.total || ccLoading}
            >
              Siguiente
            </button>
          </div>
        </div>
      )}

      {/* ── Modal de confirmación desimputar ─────────────────────── */}
      {confirmarDesimp && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>Desimputar imputación #{confirmarDesimp.id}</span>
              <button
                type="button"
                className={styles.modalCloseBtn}
                onClick={() => setConfirmarDesimp(null)}
                aria-label="Cerrar"
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p>
                Esta acción inserta un <strong>reversal append-only</strong>. La imputación original
                no se borra — queda el rastro en la cadena. ¿Confirmar?
              </p>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Motivo (opcional)</label>
                <textarea
                  className={styles.textarea}
                  value={motivoDesimp}
                  onChange={(e) => setMotivoDesimp(e.target.value)}
                  placeholder="Ej.: error de carga, reimputación a pedido distinto, etc."
                  rows={3}
                />
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                type="button"
                className={styles.btnGhost}
                onClick={() => setConfirmarDesimp(null)}
                disabled={enviando}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnDanger}
                onClick={confirmarDesimputar}
                disabled={enviando}
              >
                {enviando ? 'Desimputando...' : 'Confirmar desimputación'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
