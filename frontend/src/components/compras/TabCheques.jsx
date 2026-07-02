import { useCallback, useEffect, useState } from 'react';
import {
  Plus,
  Ban,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Inbox,
  Filter,
  X,
  CheckCircle,
  Archive,
  XCircle,
  CreditCard,
  Landmark,
  ArrowDownCircle,
  BarChart3,
} from 'lucide-react';
import api from '../../services/api';
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

const ESTADOS_CHEQUE = ['emitido', 'diferido', 'en_custodia', 'debitado', 'rechazado', 'anulado'];
const ESTADOS_TERCERO = [
  'en_cartera', 'aceptado', 'entregado', 'en_custodia',
  'depositado', 'acreditado', 'rechazado', 'rechazado_emision', 'anulado',
];

// Vistas del tab principal
const VISTAS = {
  PROPIOS: 'propios',
  CARTERA: 'cartera',
  REPORTE: 'reporte',
};


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
  emitido:           { cls: 'badgeEmitido',          label: 'Emitido' },
  diferido:          { cls: 'badgeDiferido',          label: 'Diferido' },
  debitado:          { cls: 'badgeDebitado',          label: 'Debitado' },
  rechazado:         { cls: 'badgeRechazado',         label: 'Rechazado' },
  anulado:           { cls: 'badgeAnulado',           label: 'Anulado' },
  en_cartera:        { cls: 'badgeEnCartera',         label: 'En cartera' },
  entregado:         { cls: 'badgeEntregado',         label: 'Entregado' },
  depositado:        { cls: 'badgeDepositado',        label: 'Depositado' },
  acreditado:        { cls: 'badgeAcreditado',        label: 'Acreditado' },
  // Slice 3 — e-cheq
  aceptado:          { cls: 'badgeAceptado',          label: 'Aceptado' },
  rechazado_emision: { cls: 'badgeRechazadoEmision',  label: 'Rec. emisión' },
  en_custodia:       { cls: 'badgeEnCustodia',        label: 'En custodia' },
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
  const {
    listar, anular: anularCheque, transicionarEcheq,
    debitar, depositar, acreditar, obtenerReporte,
    loading, error,
  } = useCheques();

  // ── Vista activa ──
  const [vista, setVista] = useState(VISTAS.PROPIOS);

  // ── Filters (propios) ──
  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroMoneda, setFiltroMoneda] = useState('');
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');

  // ── Filters (cartera) ──
  const [filtroEstadoCartera, setFiltroEstadoCartera] = useState('en_cartera');
  const [filtroMonedaCartera, setFiltroMonedaCartera] = useState('');

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

  // ── Modal transición e-cheq (Slice 3) ──
  // accionEcheq: { cheque, accion } — set to open modal
  const [accionEcheq, setAccionEcheq] = useState(null);
  const [motivoEcheq, setMotivoEcheq] = useState('');
  const [errorEcheq, setErrorEcheq] = useState(null);
  const [savingEcheq, setSavingEcheq] = useState(false);

  // ── Slice 4 — Conciliación bancaria ──
  // Modal debitar: { cheque }
  const [debitando, setDebitando] = useState(null);
  const [savingDebitar, setSavingDebitar] = useState(false);
  const [errorDebitar, setErrorDebitar] = useState(null);

  // Modal depositar: { cheque } + selección de banco destino
  const [depositando, setDepositando] = useState(null);
  const [bancosDisponibles, setBancosDisponibles] = useState([]);
  const [bancoDepositoId, setBancoDepositoId] = useState('');
  const [savingDepositar, setSavingDepositar] = useState(false);
  const [errorDepositar, setErrorDepositar] = useState(null);

  // Modal acreditar: { cheque }
  const [acreditando, setAcreditando] = useState(null);
  const [savingAcreditar, setSavingAcreditar] = useState(false);
  const [errorAcreditar, setErrorAcreditar] = useState(null);

  // Reporte FR-4.4
  const [reporte, setReporte] = useState(null);
  const [loadingReporte, setLoadingReporte] = useState(false);

  const fetchCheques = useCallback(async () => {
    if (vista === VISTAS.CARTERA) {
      const params = {
        page,
        page_size: PAGE_SIZE,
        tipo: 'tercero',
      };
      if (filtroEstadoCartera) params.estado = filtroEstadoCartera;
      if (filtroMonedaCartera) params.moneda = filtroMonedaCartera;
      try {
        const result = await listar(params);
        const items = result?.items ?? (Array.isArray(result) ? result : []);
        setCheques(items);
        setTotalItems(result?.total ?? items.length);
      } catch {
        setCheques([]);
        setTotalItems(0);
      }
      return;
    }

    // vista PROPIOS
    const params = {
      page,
      page_size: PAGE_SIZE,
      tipo: 'propio',
    };
    if (filtroEstado) params.estado = filtroEstado;
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
  }, [listar, page, vista, filtroEstado, filtroMoneda, filtroDesde, filtroHasta, filtroEstadoCartera, filtroMonedaCartera]);

  useEffect(() => {
    if (vista !== VISTAS.REPORTE) fetchCheques();
  }, [fetchCheques, vista]);

  // Fetch reporte cuando cambia a vista REPORTE
  useEffect(() => {
    if (vista !== VISTAS.REPORTE) return;
    setLoadingReporte(true);
    obtenerReporte()
      .then((data) => setReporte(data))
      .catch(() => setReporte(null))
      .finally(() => setLoadingReporte(false));
  }, [vista, obtenerReporte]);

  // Cargar bancos disponibles al abrir modal depositar
  useEffect(() => {
    if (!depositando) return;
    api.get('/administracion/bancos?solo_activos=true')
      .then(({ data }) => {
        const items = Array.isArray(data) ? data : (data.items ?? []);
        setBancosDisponibles(items);
      })
      .catch(() => setBancosDisponibles([]));
  }, [depositando]);

  const handleCambiarVista = (v) => {
    setVista(v);
    setPage(1);
    setCheques([]);
  };

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

  const handleEcheq = async () => {
    if (!accionEcheq) return;
    // rechazar_emision requires motivo.
    if (accionEcheq.accion === 'rechazar_emision' && !motivoEcheq.trim()) {
      setErrorEcheq('El motivo es requerido para rechazar la emisión.');
      return;
    }
    setSavingEcheq(true);
    setErrorEcheq(null);
    try {
      const motivo = motivoEcheq.trim() || null;
      await transicionarEcheq(accionEcheq.cheque.id, accionEcheq.accion, motivo);
      setAccionEcheq(null);
      setMotivoEcheq('');
      fetchCheques();
    } catch (err) {
      const d = err.response?.data;
      const msg =
        (typeof d?.detail === 'string' && d.detail) ||
        d?.mensaje ||
        err.message ||
        'Error al procesar acción e-cheq.';
      setErrorEcheq(typeof msg === 'string' ? msg : 'Error al procesar acción e-cheq.');
    } finally {
      setSavingEcheq(false);
    }
  };

  // ── Slice 4 handlers ──
  const handleDebitar = async () => {
    if (!debitando) return;
    setSavingDebitar(true);
    setErrorDebitar(null);
    try {
      await debitar(debitando.id);
      setDebitando(null);
      fetchCheques();
    } catch (err) {
      const d = err.response?.data;
      const msg = (typeof d?.detail === 'string' && d.detail) || err.message || 'Error al debitar.';
      setErrorDebitar(typeof msg === 'string' ? msg : 'Error al debitar.');
    } finally {
      setSavingDebitar(false);
    }
  };

  const handleDepositar = async () => {
    if (!depositando || !bancoDepositoId) {
      setErrorDepositar('Seleccioná un banco destino.');
      return;
    }
    setSavingDepositar(true);
    setErrorDepositar(null);
    try {
      await depositar(depositando.id, Number(bancoDepositoId));
      setDepositando(null);
      setBancoDepositoId('');
      fetchCheques();
    } catch (err) {
      const d = err.response?.data;
      const msg = (typeof d?.detail === 'string' && d.detail) || err.message || 'Error al depositar.';
      setErrorDepositar(typeof msg === 'string' ? msg : 'Error al depositar.');
    } finally {
      setSavingDepositar(false);
    }
  };

  const handleAcreditar = async () => {
    if (!acreditando) return;
    setSavingAcreditar(true);
    setErrorAcreditar(null);
    try {
      await acreditar(acreditando.id);
      setAcreditando(null);
      fetchCheques();
    } catch (err) {
      const d = err.response?.data;
      const msg = (typeof d?.detail === 'string' && d.detail) || err.message || 'Error al acreditar.';
      setErrorAcreditar(typeof msg === 'string' ? msg : 'Error al acreditar.');
    } finally {
      setSavingAcreditar(false);
    }
  };

  const LABEL_ACCION_ECHEQ = {
    aceptar: 'Aceptar e-cheq',
    poner_en_custodia: 'Poner en custodia',
    rechazar_emision: 'Rechazar e-cheq',
  };

  return (
    <div className={styles.container}>

      {/* Toolbar */}
      <div className={styles.toolbar}>
        {/* Segmented: Propios / Cartera */}
        <div className={styles.segmented}>
          <button
            type="button"
            className={`${styles.segBtn} ${vista === VISTAS.PROPIOS ? styles.segBtnActive : ''}`}
            onClick={() => handleCambiarVista(VISTAS.PROPIOS)}
          >
            Propios
          </button>
          <button
            type="button"
            className={`${styles.segBtn} ${vista === VISTAS.CARTERA ? styles.segBtnActive : ''}`}
            onClick={() => handleCambiarVista(VISTAS.CARTERA)}
          >
            Cartera de terceros
          </button>
          <button
            type="button"
            className={`${styles.segBtn} ${vista === VISTAS.REPORTE ? styles.segBtnActive : ''}`}
            onClick={() => handleCambiarVista(VISTAS.REPORTE)}
          >
            <BarChart3 size={13} />
            Reporte
          </button>
        </div>

        <button
          type="button"
          className={styles.btnPrimary}
          onClick={() => setShowModalEmitir(true)}
        >
          <Plus size={14} />
          Cargar cheque
        </button>
      </div>

      {/* Filters — Propios */}
      {vista === VISTAS.PROPIOS && (
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

          {(filtroEstado || filtroMoneda || filtroDesde || filtroHasta) && (
            <button
              type="button"
              className={styles.btnClearFilters}
              onClick={() => {
                setFiltroEstado('');
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
      )}

      {/* Filters — Cartera de terceros */}
      {vista === VISTAS.CARTERA && (
        <div className={styles.filtersRow}>
          <div className={styles.filterIcon}>
            <Filter size={14} />
          </div>

          <select
            className={styles.filterSelect}
            value={filtroEstadoCartera}
            onChange={(e) => { setPage(1); setFiltroEstadoCartera(e.target.value); }}
            aria-label="Filtrar por estado"
          >
            <option value="">Todos los estados</option>
            {ESTADOS_TERCERO.map((e) => (
              <option key={e} value={e}>
                {e.replace('_', ' ').charAt(0).toUpperCase() + e.replace('_', ' ').slice(1)}
              </option>
            ))}
          </select>

          <select
            className={styles.filterSelect}
            value={filtroMonedaCartera}
            onChange={(e) => { setPage(1); setFiltroMonedaCartera(e.target.value); }}
            aria-label="Filtrar por moneda"
          >
            <option value="">Todas las monedas</option>
            <option value="ARS">ARS</option>
            <option value="USD">USD</option>
          </select>

          {(filtroEstadoCartera !== 'en_cartera' || filtroMonedaCartera) && (
            <button
              type="button"
              className={styles.btnClearFilters}
              onClick={() => {
                setFiltroEstadoCartera('en_cartera');
                setFiltroMonedaCartera('');
                setPage(1);
              }}
            >
              Limpiar
            </button>
          )}
        </div>
      )}

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
              {vista === VISTAS.CARTERA ? (
                <tr>
                  <th>Número</th>
                  <th>Banco</th>
                  <th>CUIT librador</th>
                  <th>Librador</th>
                  <th className={styles.thRight}>Monto</th>
                  <th>Mon.</th>
                  <th>Emisión</th>
                  <th>Pago</th>
                  <th>Estado</th>
                  {puedeGestionar && <th className={styles.thRight}>Acciones</th>}
                </tr>
              ) : (
                <tr>
                  <th>Número</th>
                  <th>Tipo</th>
                  <th>Banco</th>
                  <th>Beneficiario / Librador</th>
                  <th className={styles.thRight}>Monto</th>
                  <th>Mon.</th>
                  <th>Emisión</th>
                  <th>Pago</th>
                  <th>Estado</th>
                  {puedeGestionar && <th className={styles.thRight}>Acciones</th>}
                </tr>
              )}
            </thead>
            <tbody>
              {cheques.map((ch) => (
                vista === VISTAS.CARTERA ? (
                  <tr key={ch.id} className={styles.tableRow}>
                    <td className={styles.tdMono}>{ch.numero}</td>
                    <td className={styles.tdSecondary}>{ch.banco_nombre ?? '—'}</td>
                    <td className={styles.tdMono}>{ch.cuit_librador ?? '—'}</td>
                    <td>{ch.librador_nombre ?? ch.proveedor_nombre ?? '—'}</td>
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
                        {/* Depositar: tercero en_cartera|aceptado (Slice 4) */}
                        {['en_cartera', 'aceptado'].includes(ch.estado) && (
                          <button
                            type="button"
                            className={styles.btnAction}
                            onClick={() => { setErrorDepositar(null); setBancoDepositoId(''); setDepositando(ch); }}
                            aria-label={`Depositar cheque ${ch.numero}`}
                          >
                            <Landmark size={12} />
                            Depositar
                          </button>
                        )}
                        {/* Acreditar: depositado o en_custodia (Slice 4) */}
                        {['depositado', 'en_custodia'].includes(ch.estado) && (
                          <button
                            type="button"
                            className={styles.btnAction}
                            onClick={() => { setErrorAcreditar(null); setAcreditando(ch); }}
                            aria-label={`Acreditar cheque ${ch.numero}`}
                          >
                            <ArrowDownCircle size={12} />
                            Acreditar
                          </button>
                        )}
                        {/* e-cheq acciones (Slice 3) — solo si instrumento='echeq' */}
                        {ch.instrumento === 'echeq' && ch.estado === 'en_cartera' && (
                          <button
                            type="button"
                            className={styles.btnAction}
                            onClick={() => setAccionEcheq({ cheque: ch, accion: 'aceptar' })}
                            aria-label={`Aceptar e-cheq ${ch.numero}`}
                          >
                            <CheckCircle size={12} />
                            Aceptar
                          </button>
                        )}
                        {ch.instrumento === 'echeq' && ['en_cartera', 'aceptado'].includes(ch.estado) && (
                          <button
                            type="button"
                            className={styles.btnAction}
                            onClick={() => setAccionEcheq({ cheque: ch, accion: 'poner_en_custodia' })}
                            aria-label={`Poner en custodia e-cheq ${ch.numero}`}
                          >
                            <Archive size={12} />
                            Custodia
                          </button>
                        )}
                        {ch.instrumento === 'echeq' && ['en_cartera', 'aceptado'].includes(ch.estado) && (
                          <button
                            type="button"
                            className={styles.btnDanger}
                            onClick={() => { setMotivoEcheq(''); setAccionEcheq({ cheque: ch, accion: 'rechazar_emision' }); }}
                            aria-label={`Rechazar emisión e-cheq ${ch.numero}`}
                          >
                            <XCircle size={12} />
                            Rechazar
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ) : (
                  <tr key={ch.id} className={styles.tableRow}>
                    <td className={styles.tdMono}>{ch.numero}</td>
                    <td className={styles.tdSecondary}>{ch.tipo}</td>
                    <td className={styles.tdSecondary}>{ch.banco_nombre ?? '—'}</td>
                    <td>
                      {ch.proveedor_nombre ?? ch.librador_nombre ?? '—'}
                      {ch.cuit_librador && (
                        <span className={styles.cuitTag}> · {ch.cuit_librador}</span>
                      )}
                    </td>
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
                      <td className={`${styles.tdRight} ${styles.actionsCell}`}>
                        {/* Debitar: propio emitido/diferido (Slice 4) */}
                        {ch.tipo === 'propio' && ['emitido', 'diferido'].includes(ch.estado) && (
                          <button
                            type="button"
                            className={styles.btnAction}
                            onClick={() => { setErrorDebitar(null); setDebitando(ch); }}
                            aria-label={`Debitar cheque ${ch.numero}`}
                          >
                            <CreditCard size={12} />
                            Debitar
                          </button>
                        )}
                        {/* Anular: propios emitido/diferido */}
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
                        {/* e-cheq custodia (Slice 3) */}
                        {ch.instrumento === 'echeq' && ['emitido', 'diferido'].includes(ch.estado) && (
                          <button
                            type="button"
                            className={styles.btnAction}
                            onClick={() => setAccionEcheq({ cheque: ch, accion: 'poner_en_custodia' })}
                            aria-label={`Poner en custodia e-cheq ${ch.numero}`}
                          >
                            <Archive size={12} />
                            Custodia
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                )
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

      {/* Vista Reporte (FR-4.4) */}
      {vista === VISTAS.REPORTE && (
        <div className={styles.reporteContainer}>
          {loadingReporte ? (
            <div className={styles.loadingBlock}>
              <Loader2 size={20} className={styles.spin} />
              <span>Cargando reporte...</span>
            </div>
          ) : !reporte ? (
            <div className={styles.emptyState}>
              <Inbox size={32} className={styles.emptyIcon} />
              <p>No hay datos de reporte disponibles.</p>
            </div>
          ) : (
            <>
              <section className={styles.reporteSection}>
                <h4 className={styles.reporteTitle}>
                  <Inbox size={16} />
                  En cartera ({reporte.en_cartera?.length ?? 0})
                </h4>
                {reporte.en_cartera?.length === 0 ? (
                  <p className={styles.reporteEmpty}>Sin cheques en cartera.</p>
                ) : (
                  <div className={styles.tableWrapper}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Número</th>
                          <th>Banco</th>
                          <th>CUIT librador</th>
                          <th className={styles.thRight}>Monto</th>
                          <th>Mon.</th>
                          <th>Pago</th>
                          <th>Estado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reporte.en_cartera.map((ch) => (
                          <tr key={ch.id} className={styles.tableRow}>
                            <td className={styles.tdMono}>{ch.numero}</td>
                            <td>{ch.banco_nombre ?? '—'}</td>
                            <td className={styles.tdMono}>{ch.cuit_librador ?? '—'}</td>
                            <td className={`${styles.tdMono} ${styles.tdRight}`}>{formatCurrency(ch.monto, ch.moneda)}</td>
                            <td className={styles.tdSecondary}>{ch.moneda}</td>
                            <td className={styles.tdSecondary}>{formatDate(ch.fecha_pago)}</td>
                            <td><EstadoBadgeCheque estado={ch.estado} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className={styles.reporteSection}>
                <h4 className={styles.reporteTitle}>
                  <CreditCard size={16} />
                  A debitar ({reporte.a_debitar?.length ?? 0})
                </h4>
                {reporte.a_debitar?.length === 0 ? (
                  <p className={styles.reporteEmpty}>Sin cheques a debitar.</p>
                ) : (
                  <div className={styles.tableWrapper}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Número</th>
                          <th>Banco</th>
                          <th className={styles.thRight}>Monto</th>
                          <th>Mon.</th>
                          <th>Fecha pago</th>
                          <th>Estado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reporte.a_debitar.map((ch) => (
                          <tr key={ch.id} className={styles.tableRow}>
                            <td className={styles.tdMono}>{ch.numero}</td>
                            <td>{ch.banco_nombre ?? '—'}</td>
                            <td className={`${styles.tdMono} ${styles.tdRight}`}>{formatCurrency(ch.monto, ch.moneda)}</td>
                            <td className={styles.tdSecondary}>{ch.moneda}</td>
                            <td className={styles.tdSecondary}>{formatDate(ch.fecha_pago)}</td>
                            <td><EstadoBadgeCheque estado={ch.estado} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className={styles.reporteSection}>
                <h4 className={`${styles.reporteTitle} ${styles.reporteTitleVencidos}`}>
                  <XCircle size={16} />
                  Vencidos sin conciliar ({reporte.vencidos?.length ?? 0})
                </h4>
                {reporte.vencidos?.length === 0 ? (
                  <p className={styles.reporteEmpty}>Sin cheques vencidos.</p>
                ) : (
                  <div className={styles.tableWrapper}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Número</th>
                          <th>Tipo</th>
                          <th>Banco</th>
                          <th className={styles.thRight}>Monto</th>
                          <th>Mon.</th>
                          <th>Fecha pago</th>
                          <th>Estado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reporte.vencidos.map((ch) => (
                          <tr key={ch.id} className={`${styles.tableRow} ${styles.rowVencido}`}>
                            <td className={styles.tdMono}>{ch.numero}</td>
                            <td className={styles.tdSecondary}>{ch.tipo}</td>
                            <td>{ch.banco_nombre ?? '—'}</td>
                            <td className={`${styles.tdMono} ${styles.tdRight}`}>{formatCurrency(ch.monto, ch.moneda)}</td>
                            <td className={styles.tdSecondary}>{ch.moneda}</td>
                            <td className={styles.tdSecondary}>{formatDate(ch.fecha_pago)}</td>
                            <td><EstadoBadgeCheque estado={ch.estado} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
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
                <X size={16} />
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

      {/* Modal e-cheq transición (Slice 3) */}
      {accionEcheq && (
        <div className={styles.modalOverlay}>
          <div
            className={styles.modalAnular}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-echeq-title"
          >
            <header className={styles.modalAnularHeader}>
              <h3 id="modal-echeq-title" className={styles.modalAnularTitle}>
                {LABEL_ACCION_ECHEQ[accionEcheq.accion] ?? accionEcheq.accion} — {accionEcheq.cheque.numero}
              </h3>
              <button
                type="button"
                className={styles.btnClose}
                onClick={() => { setAccionEcheq(null); setErrorEcheq(null); setMotivoEcheq(''); }}
                aria-label="Cerrar"
              >
                <X size={16} />
              </button>
            </header>

            <div className={styles.modalAnularBody}>
              <p className={styles.modalAnularDesc}>
                {accionEcheq.accion === 'aceptar' && 'El banco aceptó este e-cheq. Se registrará el estado como aceptado.'}
                {accionEcheq.accion === 'poner_en_custodia' && 'El e-cheq pasará a custodia bancaria (depósito automático al vencimiento). Esta acción es manual y NO integra con rieles bancarios.'}
                {accionEcheq.accion === 'rechazar_emision' && 'El banco rechazó este e-cheq. Se registrará el estado como rechazado. Esta acción es terminal.'}
              </p>
              {errorEcheq && (
                <div className={styles.errorBanner} role="alert">
                  {errorEcheq}
                </div>
              )}
              {accionEcheq.accion === 'rechazar_emision' && (
                <>
                  <label className={styles.fieldLabel} htmlFor="motivo-echeq-rechazo">
                    Motivo del rechazo
                  </label>
                  <textarea
                    id="motivo-echeq-rechazo"
                    className={styles.textarea}
                    value={motivoEcheq}
                    onChange={(e) => setMotivoEcheq(e.target.value)}
                    placeholder="Describí el motivo del rechazo bancario..."
                    rows={3}
                    disabled={savingEcheq}
                  />
                </>
              )}
            </div>

            <footer className={styles.modalAnularFooter}>
              <button
                type="button"
                className={styles.btnCancel}
                onClick={() => { setAccionEcheq(null); setErrorEcheq(null); setMotivoEcheq(''); }}
                disabled={savingEcheq}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnPrimary}
                onClick={handleEcheq}
                disabled={savingEcheq || (accionEcheq.accion === 'rechazar_emision' && !motivoEcheq.trim())}
              >
                {savingEcheq ? (
                  <>
                    <Loader2 size={13} className={styles.spin} />
                    Procesando...
                  </>
                ) : (
                  <>
                    <CheckCircle size={13} />
                    Confirmar
                  </>
                )}
              </button>
            </footer>
          </div>
        </div>
      )}

      {/* Modal debitar (Slice 4) */}
      {debitando && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalAnular} role="dialog" aria-modal="true" aria-labelledby="modal-debitar-title">
            <header className={styles.modalAnularHeader}>
              <h3 id="modal-debitar-title" className={styles.modalAnularTitle}>
                Debitar cheque {debitando.numero}
              </h3>
              <button type="button" className={styles.btnClose} onClick={() => setDebitando(null)} aria-label="Cerrar">
                <X size={16} />
              </button>
            </header>
            <div className={styles.modalAnularBody}>
              <p className={styles.modalAnularDesc}>
                Se registrará un débito bancario de <strong>{formatCurrency(debitando.monto, debitando.moneda)}</strong> en
                el banco {debitando.banco_nombre ?? `id=${debitando.banco_empresa_id}`}.
                Esta acción es irreversible.
              </p>
              {errorDebitar && <div className={styles.errorBanner} role="alert">{errorDebitar}</div>}
            </div>
            <footer className={styles.modalAnularFooter}>
              <button type="button" className={styles.btnCancel} onClick={() => setDebitando(null)} disabled={savingDebitar}>
                Cancelar
              </button>
              <button type="button" className={styles.btnPrimary} onClick={handleDebitar} disabled={savingDebitar}>
                {savingDebitar ? <><Loader2 size={13} className={styles.spin} /> Debitando...</> : <><CreditCard size={13} /> Confirmar débito</>}
              </button>
            </footer>
          </div>
        </div>
      )}

      {/* Modal depositar (Slice 4) */}
      {depositando && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalAnular} role="dialog" aria-modal="true" aria-labelledby="modal-depositar-title">
            <header className={styles.modalAnularHeader}>
              <h3 id="modal-depositar-title" className={styles.modalAnularTitle}>
                Depositar cheque {depositando.numero}
              </h3>
              <button type="button" className={styles.btnClose} onClick={() => setDepositando(null)} aria-label="Cerrar">
                <X size={16} />
              </button>
            </header>
            <div className={styles.modalAnularBody}>
              <p className={styles.modalAnularDesc}>
                Seleccioná la cuenta bancaria donde depositás el cheque de <strong>{formatCurrency(depositando.monto, depositando.moneda)}</strong>.
                No genera movimiento bancario hasta acreditar.
              </p>
              {errorDepositar && <div className={styles.errorBanner} role="alert">{errorDepositar}</div>}
              <label className={styles.fieldLabel} htmlFor="banco-deposito-select">
                Banco destino
              </label>
              <select
                id="banco-deposito-select"
                className={styles.filterSelect}
                value={bancoDepositoId}
                onChange={(e) => setBancoDepositoId(e.target.value)}
                disabled={savingDepositar}
                aria-label="Banco destino"
              >
                <option value="">Seleccioná un banco...</option>
                {bancosDisponibles
                  .filter((b) => b.moneda === depositando.moneda)
                  .map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.banco} ({b.moneda})
                    </option>
                  ))}
              </select>
            </div>
            <footer className={styles.modalAnularFooter}>
              <button type="button" className={styles.btnCancel} onClick={() => setDepositando(null)} disabled={savingDepositar}>
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnPrimary}
                onClick={handleDepositar}
                disabled={savingDepositar || !bancoDepositoId}
              >
                {savingDepositar ? <><Loader2 size={13} className={styles.spin} /> Depositando...</> : <><Landmark size={13} /> Confirmar depósito</>}
              </button>
            </footer>
          </div>
        </div>
      )}

      {/* Modal acreditar (Slice 4) */}
      {acreditando && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalAnular} role="dialog" aria-modal="true" aria-labelledby="modal-acreditar-title">
            <header className={styles.modalAnularHeader}>
              <h3 id="modal-acreditar-title" className={styles.modalAnularTitle}>
                Acreditar cheque {acreditando.numero}
              </h3>
              <button type="button" className={styles.btnClose} onClick={() => setAcreditando(null)} aria-label="Cerrar">
                <X size={16} />
              </button>
            </header>
            <div className={styles.modalAnularBody}>
              <p className={styles.modalAnularDesc}>
                Se registrará un ingreso bancario de <strong>{formatCurrency(acreditando.monto, acreditando.moneda)}</strong> en
                la cuenta destino. Esta acción es irreversible.
              </p>
              {errorAcreditar && <div className={styles.errorBanner} role="alert">{errorAcreditar}</div>}
            </div>
            <footer className={styles.modalAnularFooter}>
              <button type="button" className={styles.btnCancel} onClick={() => setAcreditando(null)} disabled={savingAcreditar}>
                Cancelar
              </button>
              <button type="button" className={styles.btnPrimary} onClick={handleAcreditar} disabled={savingAcreditar}>
                {savingAcreditar ? <><Loader2 size={13} className={styles.spin} /> Acreditando...</> : <><ArrowDownCircle size={13} /> Confirmar acreditación</>}
              </button>
            </footer>
          </div>
        </div>
      )}

    </div>
  );
}
