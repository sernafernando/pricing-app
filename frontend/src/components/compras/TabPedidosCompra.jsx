import { useCallback, useEffect, useState } from 'react';
import {
  Plus,
  Search,
  Loader2,
  Eye,
  Pencil,
  Send,
  Check,
  X,
  Ban,
  Truck,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useDebounce } from '../../hooks/useDebounce';
import useComprasPedidos from '../../hooks/useComprasPedidos';
import ModalPedidoCompra from './ModalPedidoCompra';
import ModalPedidoDetalle from './ModalPedidoDetalle';
import styles from './TabPedidosCompra.module.css';

const PAGE_SIZE = 50;

const ESTADOS = [
  'borrador',
  'pendiente_aprobacion',
  'aprobado',
  'rechazado',
  'cancelado',
  'pagado_parcial',
  'pagado',
];

const estadoBadgeClass = (estado) => {
  switch (estado) {
    case 'borrador':
      return styles.badgeBorrador;
    case 'pendiente_aprobacion':
      return styles.badgePendiente;
    case 'aprobado':
      return styles.badgeAprobado;
    case 'rechazado':
      return styles.badgeRechazado;
    case 'cancelado':
      return styles.badgeCancelado;
    case 'pagado_parcial':
      return styles.badgePagadoParcial;
    case 'pagado':
      return styles.badgePagado;
    default:
      return styles.badgeNeutral;
  }
};

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export default function TabPedidosCompra() {
  const { tienePermiso } = usePermisos();
  const canManage = tienePermiso('administracion.gestionar_ordenes_compra');
  const canApprove = tienePermiso('administracion.aprobar_ordenes_compra');

  // Desestructurar funciones memoizadas para evitar loop en useEffect/useCallback.
  const {
    listar: listarPedidos,
    enviarAprobacion,
    aprobar: aprobarPedido,
    rechazar: rechazarPedido,
    cancelar: cancelarPedido,
    generarEtiqueta,
    loading: pedidosLoading,
    error: pedidosError,
  } = useComprasPedidos();

  // ── Data ──
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  // ── Filters ──
  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroEmpresa, setFiltroEmpresa] = useState('');
  const [filtroProveedorId, setFiltroProveedorId] = useState('');
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [busqueda, setBusqueda] = useState('');
  const debouncedBusqueda = useDebounce(busqueda, 300);

  const [empresas, setEmpresas] = useState([]);

  // ── Modals ──
  const [showModalForm, setShowModalForm] = useState(false);
  const [pedidoEditando, setPedidoEditando] = useState(null);
  const [showModalDetalle, setShowModalDetalle] = useState(false);
  const [pedidoDetalleId, setPedidoDetalleId] = useState(null);

  // ── Inline rechazar/cancelar motivo modal ──
  const [motivoModal, setMotivoModal] = useState(null); // { pedidoId, accion, titulo }
  const [motivoTexto, setMotivoTexto] = useState('');
  const [motivoAccionRechazo, setMotivoAccionRechazo] = useState('devolver_a_borrador');
  const [motivoLoading, setMotivoLoading] = useState(false);
  const [motivoError, setMotivoError] = useState(null);

  // ── Fetch ──
  const fetchPedidos = useCallback(async () => {
    const params = { page, page_size: PAGE_SIZE };
    if (filtroEstado) params.estado = filtroEstado;
    if (filtroEmpresa) params.empresa_id = filtroEmpresa;
    if (filtroProveedorId) params.proveedor_id = filtroProveedorId;
    if (filtroDesde) params.desde = filtroDesde;
    if (filtroHasta) params.hasta = filtroHasta;

    try {
      const data = await listarPedidos(params);
      let list = data.items || [];
      // Búsqueda por número en cliente (el backend todavía no la soporta).
      if (debouncedBusqueda.trim()) {
        const q = debouncedBusqueda.trim().toLowerCase();
        list = list.filter((p) => (p.numero || '').toLowerCase().includes(q));
      }
      setItems(list);
      setTotal(data.total || 0);
    } catch {
      setItems([]);
      setTotal(0);
    }
  }, [
    listarPedidos,
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
      const { data } = await api.get('/empresas');
      setEmpresas(data || []);
    } catch {
      setEmpresas([]);
    }
  }, []);

  useEffect(() => {
    fetchEmpresas();
  }, [fetchEmpresas]);

  useEffect(() => {
    fetchPedidos();
  }, [fetchPedidos]);

  // Reset page on filters
  useEffect(() => {
    setPage(1);
  }, [filtroEstado, filtroEmpresa, filtroProveedorId, filtroDesde, filtroHasta, debouncedBusqueda]);

  // ── Actions ──
  const handleOpenCrear = () => {
    setPedidoEditando(null);
    setShowModalForm(true);
  };

  const handleOpenEditar = (pedido) => {
    setPedidoEditando(pedido);
    setShowModalForm(true);
  };

  const handleCloseForm = (reload) => {
    setShowModalForm(false);
    setPedidoEditando(null);
    if (reload) fetchPedidos();
  };

  const handleOpenDetalle = (pedido) => {
    setPedidoDetalleId(pedido.id);
    setShowModalDetalle(true);
  };

  const handleCloseDetalle = (reload) => {
    setShowModalDetalle(false);
    setPedidoDetalleId(null);
    if (reload) fetchPedidos();
  };

  const handleEnviarAprobacion = async (pedido) => {
    try {
      await enviarAprobacion(pedido.id);
      fetchPedidos();
    } catch {
      /* error ya queda en pedidosApi.error */
    }
  };

  const handleAprobar = async (pedido) => {
    try {
      await aprobarPedido(pedido.id, null);
      fetchPedidos();
    } catch {
      /* noop */
    }
  };

  const openMotivoModal = (pedido, accion, titulo) => {
    setMotivoModal({ pedidoId: pedido.id, accion, titulo });
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
        await rechazarPedido(motivoModal.pedidoId, motivoAccionRechazo, motivo);
      } else if (motivoModal.accion === 'cancelar') {
        await cancelarPedido(motivoModal.pedidoId, motivo);
      }
      setMotivoModal(null);
      fetchPedidos();
    } catch (err) {
      setMotivoError(err.response?.data?.detail || 'Error al procesar la acción.');
    } finally {
      setMotivoLoading(false);
    }
  };

  const handleCancelarBorrador = async (pedido) => {
    // Cancelar desde borrador no requiere motivo obligatorio — usamos modal igual para UX.
    openMotivoModal(pedido, 'cancelar', 'Cancelar pedido');
  };

  const handleGenerarEtiqueta = async (pedido) => {
    try {
      await generarEtiqueta(pedido.id);
      fetchPedidos();
    } catch {
      /* noop */
    }
  };

  // ── Render helpers ──
  const renderAcciones = (p) => {
    const estado = p.estado;
    const puedeEditar = canManage && estado === 'borrador';
    const puedeEnviar = canManage && estado === 'borrador';
    const puedeAprobar = canApprove && estado === 'pendiente_aprobacion';
    const puedeRechazar = canApprove && estado === 'pendiente_aprobacion';
    const puedeCancelarBorrador =
      canManage && (estado === 'borrador' || estado === 'pendiente_aprobacion');
    const puedeCancelarAprobado = canManage && estado === 'aprobado';
    const puedeEtiqueta = canManage && estado === 'aprobado' && p.requiere_envio;

    return (
      <div className={styles.rowActions}>
        <button
          className={styles.iconBtn}
          onClick={() => handleOpenDetalle(p)}
          aria-label="Ver detalle"
          title="Ver detalle"
        >
          <Eye size={14} />
        </button>
        {puedeEditar && (
          <button
            className={styles.iconBtn}
            onClick={() => handleOpenEditar(p)}
            aria-label="Editar"
            title="Editar"
          >
            <Pencil size={14} />
          </button>
        )}
        {puedeEnviar && (
          <button
            className={styles.iconBtnPrimary}
            onClick={() => handleEnviarAprobacion(p)}
            aria-label="Enviar a aprobación"
            title="Enviar a aprobación"
          >
            <Send size={14} />
          </button>
        )}
        {puedeAprobar && (
          <button
            className={styles.iconBtnSuccess}
            onClick={() => handleAprobar(p)}
            aria-label="Aprobar"
            title="Aprobar"
          >
            <Check size={14} />
          </button>
        )}
        {puedeRechazar && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => openMotivoModal(p, 'rechazar', 'Rechazar pedido')}
            aria-label="Rechazar"
            title="Rechazar"
          >
            <X size={14} />
          </button>
        )}
        {puedeCancelarBorrador && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => handleCancelarBorrador(p)}
            aria-label="Cancelar"
            title="Cancelar"
          >
            <Ban size={14} />
          </button>
        )}
        {puedeCancelarAprobado && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => openMotivoModal(p, 'cancelar', 'Cancelar pedido aprobado')}
            aria-label="Cancelar aprobado"
            title="Cancelar aprobado"
          >
            <Ban size={14} />
          </button>
        )}
        {puedeEtiqueta && (
          <button
            className={styles.iconBtnPrimary}
            onClick={() => handleGenerarEtiqueta(p)}
            aria-label="Generar etiqueta retiro"
            title="Generar etiqueta retiro"
          >
            <Truck size={14} />
          </button>
        )}
      </div>
    );
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const loading = pedidosLoading;

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
          <input
            type="number"
            className={styles.input}
            placeholder="Proveedor ID"
            value={filtroProveedorId}
            onChange={(e) => setFiltroProveedorId(e.target.value)}
          />
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
            <Search size={14} className={styles.searchIcon} />
            <input
              className={styles.searchInput}
              placeholder="Buscar por número..."
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
            />
          </div>
        </div>
        {canManage && (
          <button className={styles.btnSuccess} onClick={handleOpenCrear}>
            <Plus size={14} /> Nuevo pedido
          </button>
        )}
      </div>

      {pedidosError && (
        <div className={styles.errorBanner}>{pedidosError}</div>
      )}

      {/* Table */}
      {loading && items.length === 0 ? (
        <div className={styles.centered}>
          <Loader2 size={20} className={styles.spin} /> Cargando pedidos...
        </div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>No hay pedidos con los filtros aplicados.</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Número</th>
                <th>Proveedor</th>
                <th>Empresa</th>
                <th>Moneda</th>
                <th className={styles.thRight}>Monto</th>
                <th>Fecha pago</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td className={styles.tdMono}>{p.numero}</td>
                  <td>#{p.proveedor_id}</td>
                  <td>#{p.empresa_id}</td>
                  <td>{p.moneda}</td>
                  <td className={styles.tdRight}>{formatCurrency(p.monto, p.moneda)}</td>
                  <td className={styles.tdSecondary}>{p.fecha_pago_texto || '—'}</td>
                  <td>
                    <span className={`${styles.badge} ${estadoBadgeClass(p.estado)}`}>
                      {p.estado}
                    </span>
                  </td>
                  <td>{renderAcciones(p)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <div className={styles.pagination}>
              <span>
                {total} pedidos — Página {page} de {totalPages}
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

      {/* Modals */}
      {showModalForm && (
        <ModalPedidoCompra
          pedido={pedidoEditando}
          empresas={empresas}
          onClose={handleCloseForm}
        />
      )}

      {showModalDetalle && pedidoDetalleId && (
        <ModalPedidoDetalle
          pedidoId={pedidoDetalleId}
          onClose={handleCloseDetalle}
        />
      )}

      {/* Inline motivo modal */}
      {motivoModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>{motivoModal.titulo}</span>
              <button
                className={styles.modalCloseBtn}
                onClick={() => setMotivoModal(null)}
                aria-label="Cerrar"
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
              <label className={styles.formLabel}>Motivo</label>
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
