import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Plus,
  Loader2,
  Eye,
  Pencil,
  Send,
  Check,
  X,
  Ban,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Link2,
} from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useDebounce } from '../../hooks/useDebounce';
import useNCsLocales from '../../hooks/useNCsLocales';
import ModalNCLocal from './ModalNCLocal';
import ModalNCLocalDetalle from './ModalNCLocalDetalle';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import SearchInput from '../SearchInput';
import styles from './TabNCsLocales.module.css';

const PAGE_SIZE = 50;

const ESTADOS = [
  'borrador',
  'pendiente_aprobacion',
  'aprobado',
  'rechazado',
  'cancelado',
  'aplicada_parcial',
  'aplicada',
];

const estadoBadgeClass = (estado) => {
  switch (estado) {
    case 'borrador':
      return styles.badgeBorrador;
    case 'pendiente_aprobacion':
      return styles.badgePendiente;
    case 'aprobado':
      return styles.badgeAprobado;
    case 'aplicada_parcial':
      return styles.badgeAplicadaParcial;
    case 'aplicada':
      return styles.badgeAplicada;
    case 'rechazado':
      return styles.badgeRechazado;
    case 'cancelado':
      return styles.badgeCancelado;
    default:
      return styles.badgeNeutral;
  }
};

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

const formatDate = (isoDate) => {
  if (!isoDate) return '—';
  try {
    const [year, month, day] = String(isoDate).split('T')[0].split('-');
    if (!year || !month || !day) return isoDate;
    return `${day}/${month}/${year}`;
  } catch {
    return isoDate;
  }
};

export default function TabNCsLocales() {
  const { tienePermiso } = usePermisos();
  const canManage = tienePermiso('administracion.gestionar_ordenes_compra');
  const canApprove = tienePermiso('administracion.aprobar_ncs_locales');

  // Deep-link: `?tab=ncs-locales&proveedor_id=123` pre-filtra tabla.
  const [searchParams] = useSearchParams();
  const proveedorIdFromQuery = searchParams.get('proveedor_id');

  // Desestructurar funciones memoizadas para evitar loops en useEffect.
  const {
    listar: listarNCs,
    enviarAprobacion,
    aprobar: aprobarNC,
    rechazar: rechazarNC,
    reabrir: reabrirNC,
    cancelar: cancelarNC,
    loading: ncsLoading,
    error: ncsError,
  } = useNCsLocales();

  // ── Data ──
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  // ── Filters ──
  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroEmpresa, setFiltroEmpresa] = useState('');
  const [filtroProveedorId, setFiltroProveedorId] = useState(
    proveedorIdFromQuery || ''
  );
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [busqueda, setBusqueda] = useState('');
  const debouncedBusqueda = useDebounce(busqueda, 300);

  const [empresas, setEmpresas] = useState([]);

  // ── Modals ──
  const [showModalForm, setShowModalForm] = useState(false);
  const [ncEditando, setNcEditando] = useState(null);
  const [showModalDetalle, setShowModalDetalle] = useState(false);
  const [ncDetalleId, setNcDetalleId] = useState(null);

  // ── Inline motivo modal (rechazar / cancelar) ──
  const [motivoModal, setMotivoModal] = useState(null); // { ncId, accion, titulo }
  const [motivoTexto, setMotivoTexto] = useState('');
  const [motivoAccionRechazo, setMotivoAccionRechazo] = useState('devolver_a_borrador');
  const [motivoLoading, setMotivoLoading] = useState(false);
  const [motivoError, setMotivoError] = useState(null);

  // Sincronizar filtro proveedor si el query param cambia.
  useEffect(() => {
    if (proveedorIdFromQuery && proveedorIdFromQuery !== filtroProveedorId) {
      setFiltroProveedorId(proveedorIdFromQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proveedorIdFromQuery]);

  const fetchNCs = useCallback(async () => {
    const params = { page, page_size: PAGE_SIZE };
    if (filtroEstado) params.estado = filtroEstado;
    if (filtroEmpresa) params.empresa_id = filtroEmpresa;
    if (filtroProveedorId) params.proveedor_id = filtroProveedorId;
    if (filtroDesde) params.desde = filtroDesde;
    if (filtroHasta) params.hasta = filtroHasta;

    try {
      const data = await listarNCs(params);
      let list = data.items || [];
      // Búsqueda por número en cliente (el backend todavía no la soporta).
      if (debouncedBusqueda.trim()) {
        const q = debouncedBusqueda.trim().toLowerCase();
        list = list.filter((nc) =>
          (nc.numero || '').toLowerCase().includes(q) ||
          (nc.numero_nc_proveedor || '').toLowerCase().includes(q)
        );
      }
      setItems(list);
      setTotal(data.total || 0);
    } catch {
      setItems([]);
      setTotal(0);
    }
  }, [
    listarNCs,
    page,
    filtroEstado,
    filtroEmpresa,
    filtroProveedorId,
    filtroDesde,
    filtroHasta,
    debouncedBusqueda,
  ]);

  const fetchEmpresas = useCallback(async () => {
    try {
      const { data } = await api.get('/admin/empresas');
      setEmpresas(data || []);
    } catch {
      setEmpresas([]);
    }
  }, []);

  useEffect(() => {
    fetchEmpresas();
  }, [fetchEmpresas]);

  useEffect(() => {
    fetchNCs();
  }, [fetchNCs]);

  // Reset page on filter change.
  useEffect(() => {
    setPage(1);
  }, [
    filtroEstado,
    filtroEmpresa,
    filtroProveedorId,
    filtroDesde,
    filtroHasta,
    debouncedBusqueda,
  ]);

  // ── Actions ──
  const handleOpenCrear = () => {
    setNcEditando(null);
    setShowModalForm(true);
  };

  const handleOpenEditar = (nc) => {
    setNcEditando(nc);
    setShowModalForm(true);
  };

  const handleCloseForm = (reload) => {
    setShowModalForm(false);
    setNcEditando(null);
    if (reload) fetchNCs();
  };

  const handleOpenDetalle = (nc) => {
    setNcDetalleId(nc.id);
    setShowModalDetalle(true);
  };

  const handleCloseDetalle = (reload) => {
    setShowModalDetalle(false);
    setNcDetalleId(null);
    if (reload) fetchNCs();
  };

  const handleEnviarAprobacion = async (nc) => {
    try {
      await enviarAprobacion(nc.id);
      fetchNCs();
    } catch {
      /* error expuesto via ncsError */
    }
  };

  const handleAprobar = async (nc) => {
    try {
      await aprobarNC(nc.id, null);
      fetchNCs();
    } catch {
      /* noop */
    }
  };

  const handleReabrir = async (nc) => {
    try {
      await reabrirNC(nc.id);
      fetchNCs();
    } catch {
      /* noop */
    }
  };

  const openMotivoModal = (nc, accion, titulo) => {
    setMotivoModal({ ncId: nc.id, accion, titulo });
    setMotivoTexto('');
    setMotivoAccionRechazo('devolver_a_borrador');
    setMotivoError(null);
  };

  const handleSubmitMotivo = async () => {
    if (!motivoModal) return;
    const motivo = motivoTexto.trim();
    if (!motivo) {
      setMotivoError('El motivo es requerido.');
      return;
    }
    setMotivoLoading(true);
    setMotivoError(null);
    try {
      if (motivoModal.accion === 'rechazar') {
        await rechazarNC(motivoModal.ncId, motivoAccionRechazo, motivo);
      } else if (motivoModal.accion === 'cancelar') {
        await cancelarNC(motivoModal.ncId, motivo);
      }
      setMotivoModal(null);
      fetchNCs();
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al procesar la acción.';
      setMotivoError(msg);
    } finally {
      setMotivoLoading(false);
    }
  };

  const handleCancelarBorrador = (nc) => {
    openMotivoModal(nc, 'cancelar', `Cancelar NC ${nc.numero}`);
  };

  // ── Render helpers ──
  const renderAcciones = (nc) => {
    const estado = nc.estado;
    const puedeEditar = canManage && estado === 'borrador';
    const puedeEnviar = canManage && estado === 'borrador';
    const puedeAprobar = canApprove && estado === 'pendiente_aprobacion';
    const puedeRechazar = canApprove && estado === 'pendiente_aprobacion';
    const puedeReabrir = canManage && estado === 'rechazado';
    const puedeCancelar =
      canManage && ['borrador', 'pendiente_aprobacion', 'aprobado'].includes(estado);

    return (
      <div className={styles.rowActions}>
        <button
          className={styles.iconBtn}
          onClick={() => handleOpenDetalle(nc)}
          aria-label="Ver detalle"
          title="Ver detalle"
        >
          <Eye size={14} />
        </button>
        {puedeEditar && (
          <button
            className={styles.iconBtn}
            onClick={() => handleOpenEditar(nc)}
            aria-label="Editar"
            title="Editar"
          >
            <Pencil size={14} />
          </button>
        )}
        {puedeEnviar && (
          <button
            className={styles.iconBtnPrimary}
            onClick={() => handleEnviarAprobacion(nc)}
            aria-label="Enviar a aprobación"
            title="Enviar a aprobación"
          >
            <Send size={14} />
          </button>
        )}
        {puedeAprobar && (
          <button
            className={styles.iconBtnSuccess}
            onClick={() => handleAprobar(nc)}
            aria-label="Aprobar"
            title="Aprobar"
          >
            <Check size={14} />
          </button>
        )}
        {puedeRechazar && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => openMotivoModal(nc, 'rechazar', `Rechazar NC ${nc.numero}`)}
            aria-label="Rechazar"
            title="Rechazar"
          >
            <X size={14} />
          </button>
        )}
        {puedeReabrir && (
          <button
            className={styles.iconBtnPrimary}
            onClick={() => handleReabrir(nc)}
            aria-label="Reabrir"
            title="Reabrir (vuelve a borrador)"
          >
            <RotateCcw size={14} />
          </button>
        )}
        {puedeCancelar && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => handleCancelarBorrador(nc)}
            aria-label="Cancelar"
            title="Cancelar"
          >
            <Ban size={14} />
          </button>
        )}
      </div>
    );
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const loading = ncsLoading;

  return (
    <div className={styles.container}>
      {/* Header actions */}
      <div className={styles.topBar}>
        <div className={styles.filters}>
          <select
            className={styles.select}
            value={filtroEstado}
            onChange={(e) => setFiltroEstado(e.target.value)}
          >
            <option value="">Todos los estados</option>
            {ESTADOS.map((estado) => (
              <option key={estado} value={estado}>
                {estado}
              </option>
            ))}
          </select>
          <select
            className={styles.select}
            value={filtroEmpresa}
            onChange={(e) => setFiltroEmpresa(e.target.value)}
          >
            <option value="">Todas las empresas</option>
            {empresas.map((emp) => (
              <option key={emp.id} value={emp.id}>
                {emp.nombre}
              </option>
            ))}
          </select>
          <div className={styles.filterProveedor}>
            <ProveedorComprasAutocomplete
              value={filtroProveedorId ? Number(filtroProveedorId) : null}
              onChange={(id) => setFiltroProveedorId(id ? String(id) : '')}
              placeholder="Proveedor..."
            />
          </div>
          <input
            type="date"
            className={styles.input}
            value={filtroDesde}
            onChange={(e) => setFiltroDesde(e.target.value)}
            title="Desde"
          />
          <input
            type="date"
            className={styles.input}
            value={filtroHasta}
            onChange={(e) => setFiltroHasta(e.target.value)}
            title="Hasta"
          />
          <div className={styles.searchWrapper}>
            <SearchInput
              value={busqueda}
              onChange={setBusqueda}
              placeholder="Buscar por número o Nro NC prov..."
              size="sm"
            />
          </div>
        </div>
        {canManage && (
          <button className={styles.btnSuccess} onClick={handleOpenCrear}>
            <Plus size={14} /> Nueva NC
          </button>
        )}
      </div>

      {ncsError && <div className={styles.errorBanner}>{ncsError}</div>}

      {/* Table */}
      {loading && items.length === 0 ? (
        <div className={styles.centered}>
          <Loader2 size={20} className={styles.spin} /> Cargando NCs...
        </div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>No hay NCs con los filtros aplicados.</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Número</th>
                <th>Empresa</th>
                <th>Proveedor</th>
                <th>Nro NC prov</th>
                <th>Fecha emisión</th>
                <th>Moneda</th>
                <th className={styles.thRight}>Monto</th>
                <th>Estado</th>
                <th>ERP</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {items.map((nc) => {
                const montoNum = Number(nc.monto) || 0;
                const saldoNum = Number(nc.saldo_pendiente);
                const mostrarSaldo =
                  nc.estado === 'aplicada_parcial' &&
                  Number.isFinite(saldoNum) &&
                  saldoNum > 0 &&
                  saldoNum < montoNum;

                return (
                  <tr key={nc.id}>
                    <td className={styles.tdMono}>{nc.numero}</td>
                    <td>{nc.empresa_nombre || `#${nc.empresa_id}`}</td>
                    <td>{nc.proveedor_nombre || `#${nc.proveedor_id}`}</td>
                    <td className={styles.tdSecondary}>
                      {nc.numero_nc_proveedor || '—'}
                    </td>
                    <td className={styles.tdSecondary}>
                      {formatDate(nc.fecha_emision)}
                    </td>
                    <td>{nc.moneda}</td>
                    <td className={styles.tdRight}>
                      {formatCurrency(nc.monto, nc.moneda)}
                      {mostrarSaldo && (
                        <div className={styles.saldoPendienteHint}>
                          Saldo: {formatCurrency(saldoNum, nc.moneda)}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className={`${styles.badge} ${estadoBadgeClass(nc.estado)}`}>
                        {nc.estado}
                      </span>
                    </td>
                    <td>
                      {nc.ct_transaction_id ? (
                        <span className={styles.erpChip} title="Vinculada al ERP">
                          <Link2 size={11} />
                          #{nc.ct_transaction_id}
                        </span>
                      ) : (
                        <span className={styles.tdSecondary}>—</span>
                      )}
                    </td>
                    <td>{renderAcciones(nc)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {totalPages > 1 && (
            <div className={styles.pagination}>
              <span>
                {total} NCs — Página {page} de {totalPages}
              </span>
              <div className={styles.paginationBtns}>
                <button
                  className={styles.pageBtn}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  aria-label="Página anterior"
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  className={styles.pageBtn}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  aria-label="Página siguiente"
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Modal crear/editar */}
      {showModalForm && (
        <ModalNCLocal nc={ncEditando} empresas={empresas} onClose={handleCloseForm} />
      )}

      {/* Modal detalle */}
      {showModalDetalle && ncDetalleId && (
        <ModalNCLocalDetalle ncId={ncDetalleId} onClose={handleCloseDetalle} />
      )}

      {/* Modal motivo (rechazar / cancelar) */}
      {motivoModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>{motivoModal.titulo}</span>
              <button
                className={styles.modalCloseBtn}
                onClick={() => setMotivoModal(null)}
                aria-label="Cerrar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>

            {motivoError && <div className={styles.errorBanner}>{motivoError}</div>}

            {motivoModal.accion === 'rechazar' && (
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Acción</label>
                <select
                  className={styles.select}
                  value={motivoAccionRechazo}
                  onChange={(e) => setMotivoAccionRechazo(e.target.value)}
                >
                  <option value="devolver_a_borrador">Devolver a borrador</option>
                  <option value="cancelar_definitivo">Cancelar definitivamente</option>
                </select>
              </div>
            )}

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Motivo *</label>
              <textarea
                className={styles.textarea}
                value={motivoTexto}
                onChange={(e) => setMotivoTexto(e.target.value)}
                placeholder="Describí el motivo..."
                rows={3}
              />
            </div>

            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.btnSecondary}
                onClick={() => setMotivoModal(null)}
                disabled={motivoLoading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnDanger}
                onClick={handleSubmitMotivo}
                disabled={motivoLoading}
              >
                {motivoLoading ? 'Procesando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
