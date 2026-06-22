import { useCallback, useEffect, useState } from 'react';
import {
  Plus,
  Ban,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Inbox,
  Filter,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useCheques from '../../hooks/useCheques';
import ModalCheque from './ModalCheque';
import styles from './TabCheques.module.css';

/**
 * TabCheques — lista de cheques (Slice 1).
 *
 * Soporta filtros: estado, tipo, banco (texto), moneda, rango de fechas.
 * Paginación server-side (page_size=50).
 * Acciones: emitir (modal), anular (modal de motivo).
 * Gateado por `tesoreria.gestionar_cheques`.
 */

const PAGE_SIZE = 50;

const ESTADOS_CHEQUE = ['emitido', 'diferido', 'debitado', 'rechazado', 'anulado'];


const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  const [y, m, d] = dateStr.split('-');
  return `${d}/${m}/${y}`;
};

/**
 * EstadoBadgeCheque — mapea los estados del cheque a tonos del EstadoBadge existente.
 * EstadoBadge acepta variant "op"/"pedido"/"nc"; usamos "op" como base con overrides.
 */
const ESTADO_BADGE_MAP = {
  emitido:    { cls: 'badgeEmitido',    label: 'Emitido' },
  diferido:   { cls: 'badgeDiferido',   label: 'Diferido' },
  debitado:   { cls: 'badgeDebitado',   label: 'Debitado' },
  rechazado:  { cls: 'badgeRechazado',  label: 'Rechazado' },
  anulado:    { cls: 'badgeAnulado',    label: 'Anulado' },
  en_cartera: { cls: 'badgeEnCartera',  label: 'En cartera' },
  entregado:  { cls: 'badgeEntregado',  label: 'Entregado' },
  depositado: { cls: 'badgeDepositado', label: 'Depositado' },
  acreditado: { cls: 'badgeAcreditado', label: 'Acreditado' },
};

function EstadoBadgeCheque({ estado }) {
  const tone = ESTADO_BADGE_MAP[estado] ?? { cls: 'badgeFallback', label: estado };
  return (
    <span className={`${styles.badge} ${styles[tone.cls]}`}>
      {tone.label}
    </span>
  );
}

export default function TabCheques() {
  const { tienePermiso } = usePermisos();
  const { listar, anular: anularCheque, loading, error } = useCheques();

  // ── Filters ──
  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroTipo, setFiltroTipo] = useState('');
  const [filtroMoneda, setFiltroMoneda] = useState('');
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');

  // ── Pagination ──
  const [page, setPage] = useState(1);
  const [totalItems, setTotalItems] = useState(0);

  // ── Data ──
  const [cheques, setCheques] = useState([]);

  // ── Modal emitir ──
  const [showModalEmitir, setShowModalEmitir] = useState(false);

  // ── Modal anular ──
  const [anulando, setAnulando] = useState(null); // cheque a anular
  const [motivoAnulacion, setMotivoAnulacion] = useState('');
  const [errorAnulacion, setErrorAnulacion] = useState(null);
  const [savingAnulacion, setSavingAnulacion] = useState(false);

  const fetchCheques = useCallback(async () => {
    const params = {
      page,
      page_size: PAGE_SIZE,
    };
    if (filtroEstado) params.estado = filtroEstado;
    if (filtroTipo) params.tipo = filtroTipo;
    if (filtroMoneda) params.moneda = filtroMoneda;
    if (filtroDesde) params.desde = filtroDesde;
    if (filtroHasta) params.hasta = filtroHasta;

    try {
      const result = await listar(params);
      const items = result?.items ?? (Array.isArray(result) ? result : []);
      setCheques(items);
      setTotalItems(result?.total ?? items.length);
    } catch {
      setCheques([]);
      setTotalItems(0);
    }
  }, [listar, page, filtroEstado, filtroTipo, filtroMoneda, filtroDesde, filtroHasta]);

  useEffect(() => {
    fetchCheques();
  }, [fetchCheques]);

  // Reset to page 1 on filter change.
  const handleFiltroChange = (setter) => (val) => {
    setPage(1);
    setter(val);
  };

  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));

  // ── Permisos ──
  const puedeGestionar = tienePermiso('tesoreria.gestionar_cheques');

  if (!puedeGestionar) {
    return (
      <div className={styles.sinPermiso}>
        <Inbox size={32} />
        <p>No tenés permiso para ver cheques (<code>tesoreria.gestionar_cheques</code>).</p>
      </div>
    );
  }

  const handleAnular = async () => {
    if (!anulando || !motivoAnulacion.trim()) {
      setErrorAnulacion('El motivo es requerido.');
      return;
    }
    setSavingAnulacion(true);
    setErrorAnulacion(null);
    try {
      await anularCheque(anulando.id, motivoAnulacion.trim());
      setAnulando(null);
      setMotivoAnulacion('');
      fetchCheques();
    } catch (err) {
      const d = err.response?.data;
      const msg =
        (typeof d?.detail === 'string' && d.detail) ||
        d?.mensaje ||
        err.message ||
        'Error al anular.';
      setErrorAnulacion(typeof msg === 'string' ? msg : 'Error al anular.');
    } finally {
      setSavingAnulacion(false);
    }
  };

  return (
    <div className={styles.container}>

      {/* Toolbar */}
      <div className={styles.toolbar}>
        <h2 className={styles.sectionTitle}>Cheques propios</h2>
        <button
          type="button"
          className={styles.btnPrimary}
          onClick={() => setShowModalEmitir(true)}
        >
          <Plus size={14} />
          Cargar cheque
        </button>
      </div>

      {/* Filters */}
      <div className={styles.filtersRow}>
        <div className={styles.filterIcon}>
          <Filter size={14} />
        </div>

        <select
          className={styles.filterSelect}
          value={filtroEstado}
          onChange={(e) => handleFiltroChange(setFiltroEstado)(e.target.value)}
          aria-label="Filtrar por estado"
        >
          <option value="">Todos los estados</option>
          {ESTADOS_CHEQUE.map((e) => (
            <option key={e} value={e}>
              {e.charAt(0).toUpperCase() + e.slice(1)}
            </option>
          ))}
        </select>

        <select
          className={styles.filterSelect}
          value={filtroTipo}
          onChange={(e) => handleFiltroChange(setFiltroTipo)(e.target.value)}
          aria-label="Filtrar por tipo"
        >
          <option value="">Todos los tipos</option>
          <option value="propio">Propios</option>
          <option value="tercero">Terceros</option>
        </select>

        <select
          className={styles.filterSelect}
          value={filtroMoneda}
          onChange={(e) => handleFiltroChange(setFiltroMoneda)(e.target.value)}
          aria-label="Filtrar por moneda"
        >
          <option value="">Todas las monedas</option>
          <option value="ARS">ARS</option>
          <option value="USD">USD</option>
        </select>

        <input
          type="date"
          className={styles.filterInput}
          value={filtroDesde}
          onChange={(e) => handleFiltroChange(setFiltroDesde)(e.target.value)}
          aria-label="Desde"
          title="Fecha desde"
        />
        <input
          type="date"
          className={styles.filterInput}
          value={filtroHasta}
          onChange={(e) => handleFiltroChange(setFiltroHasta)(e.target.value)}
          aria-label="Hasta"
          title="Fecha hasta"
        />

        {(filtroEstado || filtroTipo || filtroMoneda || filtroDesde || filtroHasta) && (
          <button
            type="button"
            className={styles.btnClearFilters}
            onClick={() => {
              setFiltroEstado('');
              setFiltroTipo('');
              setFiltroMoneda('');
              setFiltroDesde('');
              setFiltroHasta('');
              setPage(1);
            }}
          >
            Limpiar
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className={styles.errorBanner} role="alert">
          {error}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className={styles.loadingBlock}>
          <Loader2 size={20} className={styles.spin} />
          <span>Cargando cheques...</span>
        </div>
      ) : cheques.length === 0 ? (
        <div className={styles.emptyState}>
          <Inbox size={32} className={styles.emptyIcon} />
          <p>No se encontraron cheques con los filtros actuales.</p>
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Número</th>
                <th>Tipo</th>
                <th>Banco</th>
                <th>Beneficiario</th>
                <th className={styles.thRight}>Monto</th>
                <th>Mon.</th>
                <th>Emisión</th>
                <th>Pago</th>
                <th>Estado</th>
                {puedeGestionar && <th className={styles.thRight}>Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {cheques.map((ch) => (
                <tr key={ch.id} className={styles.tableRow}>
                  <td className={styles.tdMono}>{ch.numero}</td>
                  <td className={styles.tdSecondary}>{ch.tipo}</td>
                  <td className={styles.tdSecondary}>{ch.banco_nombre ?? '—'}</td>
                  <td>{ch.proveedor_nombre ?? '—'}</td>
                  <td className={`${styles.tdMono} ${styles.tdRight}`}>
                    {formatCurrency(ch.monto, ch.moneda)}
                  </td>
                  <td className={styles.tdSecondary}>{ch.moneda}</td>
                  <td className={styles.tdSecondary}>{formatDate(ch.fecha_emision)}</td>
                  <td className={styles.tdSecondary}>{formatDate(ch.fecha_pago)}</td>
                  <td>
                    <EstadoBadgeCheque estado={ch.estado} />
                  </td>
                  {puedeGestionar && (
                    <td className={styles.tdRight}>
                      {['emitido', 'diferido'].includes(ch.estado) && (
                        <button
                          type="button"
                          className={styles.btnDanger}
                          onClick={() => {
                            setAnulando(ch);
                            setMotivoAnulacion('');
                            setErrorAnulacion(null);
                          }}
                          aria-label={`Anular cheque ${ch.numero}`}
                        >
                          <Ban size={12} />
                          Anular
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            type="button"
            className={styles.btnPage}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            aria-label="Página anterior"
          >
            <ChevronLeft size={14} />
          </button>
          <span className={styles.pageInfo}>
            {page} / {totalPages}
          </span>
          <button
            type="button"
            className={styles.btnPage}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            aria-label="Página siguiente"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      )}

      {/* Modal emitir */}
      {showModalEmitir && (
        <ModalCheque
          mode="standalone"
          onClose={(recargar) => {
            setShowModalEmitir(false);
            if (recargar) fetchCheques();
          }}
        />
      )}

      {/* Modal anular */}
      {anulando && (
        <div className={styles.modalOverlay}>
          <div
            className={styles.modalAnular}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-anular-title"
          >
            <header className={styles.modalAnularHeader}>
              <h3 id="modal-anular-title" className={styles.modalAnularTitle}>
                Anular cheque {anulando.numero}
              </h3>
              <button
                type="button"
                className={styles.btnClose}
                onClick={() => setAnulando(null)}
                aria-label="Cerrar"
              >
                ×
              </button>
            </header>

            <div className={styles.modalAnularBody}>
              <p className={styles.modalAnularDesc}>
                Esta acción revertirá la imputación al cuenta corriente del proveedor. Ingresá un
                motivo para continuar.
              </p>
              {errorAnulacion && (
                <div className={styles.errorBanner} role="alert">
                  {errorAnulacion}
                </div>
              )}
              <label className={styles.fieldLabel} htmlFor="motivo-anulacion">
                Motivo
              </label>
              <textarea
                id="motivo-anulacion"
                className={styles.textarea}
                value={motivoAnulacion}
                onChange={(e) => setMotivoAnulacion(e.target.value)}
                placeholder="Describí el motivo de la anulación..."
                rows={3}
                disabled={savingAnulacion}
              />
            </div>

            <footer className={styles.modalAnularFooter}>
              <button
                type="button"
                className={styles.btnCancel}
                onClick={() => setAnulando(null)}
                disabled={savingAnulacion}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnDangerFull}
                onClick={handleAnular}
                disabled={savingAnulacion || !motivoAnulacion.trim()}
              >
                {savingAnulacion ? (
                  <>
                    <Loader2 size={13} className={styles.spin} />
                    Anulando...
                  </>
                ) : (
                  <>
                    <Ban size={13} />
                    Confirmar anulación
                  </>
                )}
              </button>
            </footer>
          </div>
        </div>
      )}

    </div>
  );
}
