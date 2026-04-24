import { useState, useEffect, useCallback, useRef } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import { toLocalDateString } from '../utils/dateUtils';
import { usePermisos } from '../contexts/PermisosContext';
import {
  ScanBarcode, X, ShieldAlert, Ban, Lock,
  Clock, CheckCircle, AlertCircle, Package, RefreshCw,
} from 'lucide-react';
import api from '../services/api';
import SearchInput from '../components/SearchInput';
import styles from './ControlDeposito.module.css';

const ESTADO_CONFIG = {
  pendiente: { label: 'Pendiente', color: 'gray' },
  rma: { label: 'RMA', color: 'blue' },
  deposito: { label: 'Deposito', color: 'green' },
  no_baja: { label: 'No Baja', color: 'orange' },
};

const TERMINAL_STATES = ['deposito', 'no_baja'];

const PAGE_SIZE = 50;

const todayStr = () => toLocalDateString();

// ── Helper: extract challenge word from product description ──

const extractChallengeWord = (text) => {
  if (!text) return null;
  const words = text
    .split(/\s+/)
    .filter((w) => w.length >= 4 && /^[a-záéíóúñü]+$/i.test(w));
  if (words.length === 0) return null;
  return words[Math.floor(Math.random() * words.length)];
};

// ── Component ───────────────────────────────────────────────

export default function ControlDeposito() {
  const { tienePermiso } = usePermisos();

  // Permission gate
  if (!tienePermiso('rma.control_deposito')) {
    return (
      <div className={styles.noPermiso}>
        <ShieldAlert size={48} />
        <p>No tenés permiso para acceder a esta sección.</p>
      </div>
    );
  }

  return <ControlDepositoInner />;
}

function ControlDepositoInner() {
  const { tienePermiso } = usePermisos();
  const puedeNoBaja = tienePermiso('rma.control_deposito_no_baja');

  // ── Date filters ────────────────────────────────────────────
  const [fechaDesde, setFechaDesde] = useState(todayStr());
  const [fechaHasta, setFechaHasta] = useState(todayStr());
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('hoy');

  const aplicarFiltroRapido = (filtro) => {
    const hoy = new Date();
    const fmt = (d) => toLocalDateString(d);
    let desde;
    let hasta = hoy;

    switch (filtro) {
      case 'hoy':
        desde = new Date(hoy);
        break;
      case 'ayer': {
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 1);
        hasta = new Date(desde);
        break;
      }
      case '3d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 2);
        break;
      case '7d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 6);
        break;
      default:
        return;
    }

    setFiltroRapidoActivo(filtro);
    setFechaDesde(fmt(desde));
    setFechaHasta(fmt(hasta));
  };

  // ── Search / Status filter ──────────────────────────────────
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [filtroEstado, setFiltroEstado] = useState('all');

  // ── Data ────────────────────────────────────────────────────
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);

  // ── Stats ───────────────────────────────────────────────────
  const [stats, setStats] = useState({ pendiente: 0, rma: 0, deposito: 0, no_baja: 0 });

  // ── Scanner ─────────────────────────────────────────────────
  const [scanInput, setScanInput] = useState('');
  const [scanFeedback, setScanFeedback] = useState(null);
  const scanRef = useRef(null);

  // ── PIN modal ───────────────────────────────────────────────
  const [showPinModal, setShowPinModal] = useState(false);
  const [pinValue, setPinValue] = useState('');
  const [pinLoading, setPinLoading] = useState(false);
  const [pinError, setPinError] = useState(null);
  const [pendingScanPayload, setPendingScanPayload] = useState(null);
  const pinInputRef = useRef(null);

  // ── No Baja challenge modal ─────────────────────────────────
  const [showNoBajaModal, setShowNoBajaModal] = useState(false);
  const [noBajaItem, setNoBajaItem] = useState(null);
  const [noBajaChallengeWord, setNoBajaChallengeWord] = useState('');
  const [noBajaChallengeInput, setNoBajaChallengeInput] = useState('');
  const [noBajaMotivo, setNoBajaMotivo] = useState('');
  const [noBajaLoading, setNoBajaLoading] = useState(false);

  // ── Auto-focus scanner on mount ─────────────────────────────
  useEffect(() => {
    scanRef.current?.focus();
  }, []);

  // ── Build query params ──────────────────────────────────────
  const buildParams = useCallback(() => {
    const p = new URLSearchParams();
    if (fechaDesde) p.append('fecha_desde', fechaDesde);
    if (fechaHasta) p.append('fecha_hasta', fechaHasta);
    if (debouncedSearch) p.append('search', debouncedSearch);
    if (filtroEstado !== 'all') p.append('estado', filtroEstado);
    p.append('page', String(page));
    p.append('page_size', String(PAGE_SIZE));
    return p;
  }, [fechaDesde, fechaHasta, debouncedSearch, filtroEstado, page]);

  // ── Load table data ─────────────────────────────────────────
  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = buildParams();
      const { data } = await api.get(`/rma-control-deposito/?${params}`);
      setItems(data.items || []);
      setTotalPages(data.total_pages || 1);
      setTotalItems(data.total || 0);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error cargando datos');
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  // ── Load stats ──────────────────────────────────────────────
  const cargarStats = useCallback(async () => {
    try {
      const p = new URLSearchParams();
      if (fechaDesde) p.append('fecha_desde', fechaDesde);
      if (fechaHasta) p.append('fecha_hasta', fechaHasta);
      const { data } = await api.get(`/rma-control-deposito/stats?${p}`);
      setStats({
        pendiente: data.pendiente || 0,
        rma: data.rma || 0,
        deposito: data.deposito || 0,
        no_baja: data.no_baja || 0,
      });
    } catch {
      // Silencioso — stats no son críticos
    }
  }, [fechaDesde, fechaHasta]);

  // ── Effects ─────────────────────────────────────────────────
  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  useEffect(() => {
    cargarStats();
  }, [cargarStats]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [fechaDesde, fechaHasta, debouncedSearch, filtroEstado]);

  // ── Scanner ─────────────────────────────────────────────────

  const parseScanInput = (raw) => {
    const trimmed = raw.trim();
    if (trimmed.startsWith('{')) {
      try {
        const parsed = JSON.parse(trimmed);
        return parsed.id || parsed.serial_number || trimmed;
      } catch {
        // Not valid JSON yet, use raw
      }
    }
    return trimmed;
  };

  const executeScan = async (value, operadorId = null) => {
    const body = { value };
    if (operadorId) body.operador_id = operadorId;

    const { data } = await api.post('/rma-control-deposito/scan', body);
    return data;
  };

  const handleScan = async () => {
    const raw = scanInput.trim();
    if (!raw) return;

    const parsed = parseScanInput(raw);
    setScanInput('');
    setScanFeedback(null);

    try {
      const data = await executeScan(parsed);

      if (data.requires_operador) {
        setPendingScanPayload(parsed);
        setPinValue('');
        setPinError(null);
        setShowPinModal(true);
        setTimeout(() => pinInputRef.current?.focus(), 100);
        return;
      }

      setScanFeedback({
        type: data.ok ? 'success' : 'error',
        message: data.mensaje || (data.ok ? 'Escaneado correctamente' : 'Error al escanear'),
      });

      if (data.ok) {
        cargarDatos();
        cargarStats();
      }
    } catch (err) {
      setScanFeedback({
        type: 'error',
        message: err.response?.data?.detail || 'Error procesando escaneo',
      });
    }

    setTimeout(() => setScanFeedback(null), 3000);
    scanRef.current?.focus();
  };

  const handleScanKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleScan();
    }
  };

  // ── PIN modal handlers ──────────────────────────────────────

  const handlePinSubmit = async () => {
    if (pinValue.length !== 4) return;

    setPinLoading(true);
    setPinError(null);

    try {
      const { data: pinData } = await api.post('/config-operaciones/validar-pin', {
        pin: pinValue,
      });

      if (!pinData.valid) {
        setPinError('PIN inválido');
        setPinLoading(false);
        return;
      }

      // Re-execute scan with operador_id
      setShowPinModal(false);
      setPinValue('');

      try {
        const data = await executeScan(pendingScanPayload, pinData.operador_id);
        setScanFeedback({
          type: data.ok ? 'success' : 'error',
          message: data.mensaje || (data.ok ? 'Escaneado correctamente' : 'Error al escanear'),
        });

        if (data.ok) {
          cargarDatos();
          cargarStats();
        }
      } catch (err) {
        setScanFeedback({
          type: 'error',
          message: err.response?.data?.detail || 'Error procesando escaneo',
        });
      }

      setTimeout(() => setScanFeedback(null), 3000);
      scanRef.current?.focus();
    } catch (err) {
      setPinError(err.response?.data?.detail || 'Error validando PIN');
    } finally {
      setPinLoading(false);
      setPendingScanPayload(null);
    }
  };

  const handlePinKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handlePinSubmit();
    }
  };

  const closePinModal = () => {
    setShowPinModal(false);
    setPinValue('');
    setPinError(null);
    setPendingScanPayload(null);
    scanRef.current?.focus();
  };

  // ── No Baja modal handlers ──────────────────────────────────

  const abrirNoBajaModal = (item) => {
    const word = extractChallengeWord(item.producto_desc);
    setNoBajaItem(item);
    setNoBajaChallengeWord(word || 'CONFIRMAR');
    setNoBajaChallengeInput('');
    setNoBajaMotivo('');
    setShowNoBajaModal(true);
  };

  const handleNoBajaConfirm = async () => {
    if (!noBajaItem) return;
    setNoBajaLoading(true);

    try {
      await api.post(`/rma-control-deposito/${noBajaItem.id}/no-baja`, {
        motivo: noBajaMotivo.trim(),
      });

      setShowNoBajaModal(false);
      setNoBajaItem(null);
      cargarDatos();
      cargarStats();
    } catch (err) {
      setScanFeedback({
        type: 'error',
        message: err.response?.data?.detail || 'Error al marcar no baja',
      });
      setTimeout(() => setScanFeedback(null), 3000);
    } finally {
      setNoBajaLoading(false);
    }
  };

  const closeNoBajaModal = () => {
    setShowNoBajaModal(false);
    setNoBajaItem(null);
    setNoBajaChallengeInput('');
    setNoBajaMotivo('');
  };

  const noBajaConfirmDisabled =
    noBajaChallengeInput.toLowerCase() !== noBajaChallengeWord.toLowerCase() ||
    noBajaMotivo.trim().length < 3 ||
    noBajaLoading;

  // ── Stat click → filter ─────────────────────────────────────

  const handleStatClick = (estado) => {
    setFiltroEstado((prev) => (prev === estado ? 'all' : estado));
  };

  // ── Format date/time ────────────────────────────────────────

  const formatDateTime = (isoStr) => {
    if (!isoStr) return null;
    try {
      const d = new Date(isoStr);
      return d.toLocaleString('es-AR', {
        day: '2-digit',
        month: '2-digit',
        year: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr;
    }
  };

  // ── Render ──────────────────────────────────────────────────

  return (
    <div className={styles.container}>
      {/* ── Scanner Section ──────────────────────────────────── */}
      <div className={styles.scannerSection}>
        <div className={styles.scannerRow}>
          <ScanBarcode size={20} className={styles.scanIcon} />
          <input
            ref={scanRef}
            type="text"
            value={scanInput}
            onChange={(e) => setScanInput(e.target.value)}
            onKeyDown={handleScanKeyDown}
            className={styles.scanInput}
            placeholder="Escanear serie o EAN..."
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        {scanFeedback && (
          <div
            className={
              scanFeedback.type === 'success'
                ? styles.feedbackSuccess
                : styles.feedbackError
            }
          >
            {scanFeedback.type === 'success' ? (
              <CheckCircle size={16} />
            ) : (
              <AlertCircle size={16} />
            )}
            {scanFeedback.message}
          </div>
        )}
      </div>

      {/* ── Stats Bar ────────────────────────────────────────── */}
      <div className={styles.statsBar}>
        {Object.entries(ESTADO_CONFIG).map(([key, cfg]) => (
          <button
            key={key}
            type="button"
            className={`${styles.statCard} ${filtroEstado === key ? styles.statCardActive : ''}`}
            style={{ '--stat-color': `var(--cf-stat-${cfg.color})` }}
            onClick={() => handleStatClick(key)}
          >
            <div className={styles.statAccent} />
            <div className={styles.statValue}>{stats[key] ?? 0}</div>
            <div className={styles.statLabel}>{cfg.label}</div>
          </button>
        ))}
      </div>

      {/* ── Filters Bar ──────────────────────────────────────── */}
      <div className={styles.filtersBar}>
        <div className={styles.filtersLeft}>
          {/* Quick date buttons */}
          <div className={styles.dateQuickFilters}>
            {[
              { key: 'hoy', label: 'Hoy' },
              { key: 'ayer', label: 'Ayer' },
              { key: '3d', label: '3 dias' },
              { key: '7d', label: '7 dias' },
            ].map(({ key, label }) => (
              <button
                key={key}
                type="button"
                className={`${styles.filterBtn} ${filtroRapidoActivo === key ? styles.filterBtnActive : ''}`}
                onClick={() => aplicarFiltroRapido(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Custom date pickers */}
          <input
            type="date"
            value={fechaDesde}
            onChange={(e) => {
              setFechaDesde(e.target.value);
              setFiltroRapidoActivo('custom');
            }}
            className={styles.dateInput}
          />
          <input
            type="date"
            value={fechaHasta}
            onChange={(e) => {
              setFechaHasta(e.target.value);
              setFiltroRapidoActivo('custom');
            }}
            className={styles.dateInput}
          />
        </div>

        <div className={styles.filtersRight}>
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Buscar serie, EAN, producto..."
            size="sm"
          />

          <button
            type="button"
            className={styles.btnRefresh}
            onClick={() => {
              cargarDatos();
              cargarStats();
            }}
            aria-label="Recargar datos"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* ── Status Tabs ──────────────────────────────────────── */}
      <div className={styles.statusTabs}>
        <button
          type="button"
          className={`${styles.statusTab} ${filtroEstado === 'all' ? styles.statusTabActive : ''}`}
          onClick={() => setFiltroEstado('all')}
        >
          Todos
          <span className={styles.tabCount}>{stats.pendiente + stats.rma + stats.deposito + stats.no_baja}</span>
        </button>
        {Object.entries(ESTADO_CONFIG).map(([key, cfg]) => (
          <button
            key={key}
            type="button"
            className={`${styles.statusTab} ${filtroEstado === key ? styles.statusTabActive : ''}`}
            onClick={() => setFiltroEstado(key)}
          >
            {cfg.label}
            <span className={styles.tabCount}>{stats[key] ?? 0}</span>
          </button>
        ))}
      </div>

      {/* ── Table ────────────────────────────────────────────── */}
      {loading ? (
        <div className={styles.loading}>Cargando...</div>
      ) : error ? (
        <div className={styles.error}>{error}</div>
      ) : items.length === 0 ? (
        <div className={styles.empty}>
          <Package size={32} />
          <p>No se encontraron items para los filtros seleccionados.</p>
        </div>
      ) : (
        <>
          <div className={styles.tableContainer}>
            <table className="table-tesla striped">
              <thead>
                <tr className="table-tesla-head">
                  <th>Serie</th>
                  <th>EAN</th>
                  <th>Producto</th>
                  <th>Caso</th>
                  <th>Estado</th>
                  <th>Escaneado RMA</th>
                  <th>Escaneado Depo</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className={styles.cellMono}>{item.serie || '—'}</td>
                    <td className={styles.cellMono}>{item.ean || '—'}</td>
                    <td className={styles.cellProducto} title={item.producto_desc}>
                      {item.producto_desc || '—'}
                    </td>
                    <td>{item.caso || '—'}</td>
                    <td>
                      <span
                        className={styles.badge}
                        style={{
                          '--badge-color': `var(--cf-badge-${ESTADO_CONFIG[item.estado]?.color || 'gray'})`,
                        }}
                      >
                        {ESTADO_CONFIG[item.estado]?.label || item.estado}
                      </span>
                    </td>
                    <td className={styles.cellDate}>
                      {item.escaneado_rma ? (
                        <span className={styles.dateScanned}>
                          <Clock size={13} />
                          {formatDateTime(item.escaneado_rma)}
                        </span>
                      ) : (
                        <span className={styles.cellMuted}>—</span>
                      )}
                    </td>
                    <td className={styles.cellDate}>
                      {item.escaneado_deposito ? (
                        <span className={styles.dateScanned}>
                          <Clock size={13} />
                          {formatDateTime(item.escaneado_deposito)}
                        </span>
                      ) : (
                        <span className={styles.cellMuted}>—</span>
                      )}
                    </td>
                    <td>
                      {puedeNoBaja && !TERMINAL_STATES.includes(item.estado) && (
                        <button
                          type="button"
                          className={styles.actionBtn}
                          onClick={() => abrirNoBajaModal(item)}
                          title="Marcar como No Baja"
                        >
                          <Ban size={14} />
                          No baja
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ── Pagination ───────────────────────────────────── */}
          <div className={styles.pagination}>
            <span className={styles.paginationInfo}>
              {totalItems} item{totalItems !== 1 ? 's' : ''} — Pag. {page} de {totalPages}
            </span>
            <div className={styles.paginationControls}>
              <button
                type="button"
                className={styles.paginationBtn}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                Anterior
              </button>
              <button
                type="button"
                className={styles.paginationBtn}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
              >
                Siguiente
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── PIN Modal ────────────────────────────────────────── */}
      {showPinModal && (
        <div className={styles.sheetOverlay}>
          <div className={styles.pinModal}>
            <div className={styles.modalHeader}>
              <h3>
                <Lock size={18} />
                Operador requerido
              </h3>
              <button
                type="button"
                className={styles.modalClose}
                onClick={closePinModal}
                aria-label="Cerrar modal"
              >
                <X size={20} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p className={styles.pinInstructions}>
                Ingresá tu PIN de 4 digitos para continuar.
              </p>
              <input
                ref={pinInputRef}
                type="password"
                maxLength={4}
                value={pinValue}
                onChange={(e) => {
                  const val = e.target.value.replace(/\D/g, '');
                  setPinValue(val);
                }}
                onKeyDown={handlePinKeyDown}
                className={styles.pinInput}
                placeholder="••••"
                autoComplete="off"
                inputMode="numeric"
              />
              {pinError && (
                <div className={styles.pinError}>
                  <AlertCircle size={14} />
                  {pinError}
                </div>
              )}
            </div>

            <div className={styles.modalFooter}>
              <button
                type="button"
                className={styles.btnCancelar}
                onClick={closePinModal}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnConfirm}
                onClick={handlePinSubmit}
                disabled={pinValue.length !== 4 || pinLoading}
              >
                {pinLoading ? 'Validando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── No Baja Challenge Modal ──────────────────────────── */}
      {showNoBajaModal && noBajaItem && (
        <div className={styles.sheetOverlay}>
          <div className={styles.challengeModal}>
            <div className={styles.modalHeader}>
              <h3>
                <Ban size={18} />
                Marcar como No Baja
              </h3>
              <button
                type="button"
                className={styles.modalClose}
                onClick={closeNoBajaModal}
                aria-label="Cerrar modal"
              >
                <X size={20} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.challengeItemInfo}>
                <p><strong>Serie:</strong> {noBajaItem.serie || '—'}</p>
                <p><strong>Producto:</strong> {noBajaItem.producto_desc || '—'}</p>
              </div>

              <div className={styles.challengeSection}>
                <p className={styles.challengeLabel}>
                  Escribi <strong>{noBajaChallengeWord}</strong> para confirmar:
                </p>
                <input
                  type="text"
                  value={noBajaChallengeInput}
                  onChange={(e) => setNoBajaChallengeInput(e.target.value)}
                  className={styles.challengeInput}
                  placeholder={noBajaChallengeWord}
                  autoFocus
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>

              <div className={styles.challengeSection}>
                <p className={styles.challengeLabel}>
                  Motivo <span className={styles.required}>(obligatorio, min. 3 caracteres)</span>:
                </p>
                <textarea
                  value={noBajaMotivo}
                  onChange={(e) => setNoBajaMotivo(e.target.value)}
                  className={styles.challengeTextarea}
                  placeholder="Describí el motivo por el que no baja..."
                  rows={3}
                />
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button
                type="button"
                className={styles.btnCancelar}
                onClick={closeNoBajaModal}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnConfirmDanger}
                onClick={handleNoBajaConfirm}
                disabled={noBajaConfirmDisabled}
              >
                {noBajaLoading ? 'Procesando...' : 'Confirmar No Baja'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
