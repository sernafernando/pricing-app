import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Plus,
  Eye,
  Pencil,
  Send,
  Check,
  X,
  Ban,
  Truck,
  ChevronLeft,
  ChevronRight,
  DollarSign,
  Clock,
  Trash2,
  Inbox,
} from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useDebounce } from '../../hooks/useDebounce';
import useComprasPedidos from '../../hooks/useComprasPedidos';
import ModalPedidoCompra from './ModalPedidoCompra';
import ModalPedidoDetalle from './ModalPedidoDetalle';
import ModalConfirmarEliminacion from './ModalConfirmarEliminacion';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import SearchInput from '../SearchInput';
import DataTable from './_shared/DataTable';
import EstadoBadge from './_shared/EstadoBadge';
import LoadingBlock from './_shared/LoadingBlock';
import FiltersBar from './_shared/FiltersBar';
import { equivalenteEnArs } from './_shared/formatMoneda';
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

const COLUMNS = [
  { key: 'numero', label: 'Número', width: '160px' },
  { key: 'empresa', label: 'Empresa', width: '140px' },
  { key: 'proveedor', label: 'Proveedor' },
  { key: 'moneda', label: 'Mon.', align: 'center', width: '60px' },
  { key: 'monto', label: 'Saldo', align: 'right', width: '180px' },
  { key: 'plazo', label: 'Plazo', width: '120px' },
  { key: 'fecha_pago', label: 'Fecha pago', width: '160px' },
  { key: 'estado', label: 'Estado', width: '110px' },
  { key: 'acciones', label: '', align: 'right', width: '180px' },
];

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

// Formateo consistente de fechas DATE (YYYY-MM-DD) al locale es-AR (dd/mm/yyyy).
const formatDate = (isoDate) => {
  if (!isoDate) return '—';
  try {
    // Tratamos la fecha como local para evitar el bug de off-by-one UTC.
    const [year, month, day] = String(isoDate).split('T')[0].split('-');
    if (!year || !month || !day) return isoDate;
    return `${day}/${month}/${year}`;
  } catch {
    return isoDate;
  }
};

export default function TabPedidosCompra() {
  const { tienePermiso } = usePermisos();
  const canManage = tienePermiso('administracion.gestionar_ordenes_compra');
  const canApprove = tienePermiso('administracion.aprobar_ordenes_compra');
  const canPay = tienePermiso('administracion.ejecutar_pagos');
  const canDeleteBasura = tienePermiso('administracion.eliminar_compras_basura');

  // Deep-link para "Pagar" (abre tab ordenes-pago con pedido pre-cargado).
  const [, setSearchParams] = useSearchParams();

  // Días hasta fecha para badges "vence en N días".
  const diasHasta = (isoDate) => {
    if (!isoDate) return null;
    try {
      const [y, m, d] = String(isoDate).split('T')[0].split('-');
      if (!y || !m || !d) return null;
      const target = new Date(Number(y), Number(m) - 1, Number(d));
      const hoy = new Date();
      hoy.setHours(0, 0, 0, 0);
      return Math.round((target - hoy) / (1000 * 60 * 60 * 24));
    } catch {
      return null;
    }
  };

  // Desestructurar funciones memoizadas para evitar loop en useEffect/useCallback.
  const {
    listar: listarPedidos,
    enviarAprobacion,
    aprobar: aprobarPedido,
    rechazar: rechazarPedido,
    cancelar: cancelarPedido,
    generarEtiqueta,
    eliminar: eliminarPedido,
    loading: pedidosLoading,
    error: pedidosError,
  } = useComprasPedidos();

  // ── Hard-delete papelera state ──
  const [eliminarModal, setEliminarModal] = useState(null); // pedido | null
  const [eliminarLoading, setEliminarLoading] = useState(false);
  const [eliminarError, setEliminarError] = useState(null);

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

  const handleCloseDetalle = (result) => {
    // Firma backward-compatible:
    //   - false/undefined → cerrar sin recargar.
    //   - true           → cerrar + recargar.
    //   - objeto         → feature D: { reload, clonId?, pedidoId? }. Si
    //     viene un ID nuevo, reabrimos el detalle con ese pedido (nav
    //     bidireccional original↔clon).
    setShowModalDetalle(false);
    if (typeof result === 'object' && result !== null) {
      const { reload, clonId, pedidoId } = result;
      const next = clonId || pedidoId || null;
      if (next) {
        // Reabrir modal con el pedido relacionado (clon o original).
        setPedidoDetalleId(next);
        setShowModalDetalle(true);
        if (reload) fetchPedidos();
        return;
      }
      setPedidoDetalleId(null);
      if (reload) fetchPedidos();
      return;
    }
    setPedidoDetalleId(null);
    if (result) fetchPedidos();
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

  const handlePagarAhora = (pedido) => {
    // Deep-link al tab OPs con pedido pre-cargado (TabOrdenesPago lo lee).
    setSearchParams(
      {
        tab: 'ordenes-pago',
        accion: 'nueva-op',
        pedido_id: String(pedido.id),
      },
      { replace: false }
    );
  };

  const handleOpenEliminar = (pedido) => {
    setEliminarModal(pedido);
    setEliminarError(null);
  };

  const handleConfirmEliminar = async ({ motivo, challenge_palabra_usada }) => {
    if (!eliminarModal) return;
    setEliminarLoading(true);
    setEliminarError(null);
    try {
      await eliminarPedido(eliminarModal.id, motivo, challenge_palabra_usada);
      setEliminarModal(null);
      fetchPedidos();
    } catch (err) {
      setEliminarError(err.response?.data?.detail || 'Error al eliminar el pedido.');
    } finally {
      setEliminarLoading(false);
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
    const puedePagar = canPay && (estado === 'aprobado' || estado === 'pagado_parcial');
    const puedeEliminarBasura = canDeleteBasura && p.puede_eliminar === true;

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
        {puedePagar && (
          <button
            className={styles.iconBtnSuccess}
            onClick={() => handlePagarAhora(p)}
            aria-label="Pagar"
            title="Crear OP imputada a este pedido"
          >
            <DollarSign size={14} />
          </button>
        )}
        {puedeEliminarBasura && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => handleOpenEliminar(p)}
            aria-label="Eliminar definitivamente"
            title="Eliminar definitivamente (papelera)"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    );
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const loading = pedidosLoading;

  // Renderea contenido de cada celda según la columna.
  const renderCell = (p, col) => {
    switch (col.key) {
      case 'numero':
        return <span className={styles.tdMono}>{p.numero}</span>;
      case 'empresa':
        return p.empresa_nombre || `#${p.empresa_id}`;
      case 'proveedor':
        return p.proveedor_nombre || `#${p.proveedor_id}`;
      case 'moneda':
        return <span className={styles.tdMono}>{p.moneda}</span>;
      case 'monto': {
        // Saldo pendiente (= monto - imputaciones efectivas) en moneda del
        // pedido. Si pedido es USD con TC, mostramos saldo ARS = saldo_usd × TC.
        // El total se muestra como subvalor para no perder contexto.
        const saldo = p.saldo_pendiente !== null && p.saldo_pendiente !== undefined
          ? Number(p.saldo_pendiente)
          : Number(p.monto);
        const equivSaldoArs = equivalenteEnArs(saldo, p.moneda, p.tipo_cambio);
        const equivTotalArs = equivalenteEnArs(p.monto, p.moneda, p.tipo_cambio);
        if (equivSaldoArs !== null) {
          return (
            <div className={styles.montoDual}>
              <span className={styles.montoArsPrincipal}>
                {formatCurrency(equivSaldoArs, 'ARS')}
              </span>
              <span className={styles.montoUsdSecundario}>
                {formatCurrency(saldo, 'USD')} pend.
                {equivTotalArs !== null && saldo !== Number(p.monto)
                  ? ` · total ${formatCurrency(equivTotalArs, 'ARS')}`
                  : ''}
              </span>
            </div>
          );
        }
        // ARS o sin TC: mostrar saldo directo
        if (saldo !== Number(p.monto)) {
          return (
            <div className={styles.montoDual}>
              <span className={styles.montoArsPrincipal}>{formatCurrency(saldo, p.moneda)}</span>
              <span className={styles.montoUsdSecundario}>
                pend. · total {formatCurrency(p.monto, p.moneda)}
              </span>
            </div>
          );
        }
        return formatCurrency(p.monto, p.moneda);
      }
      case 'plazo':
        return <span className={styles.tdSecondary}>{p.fecha_pago_texto || '—'}</span>;
      case 'fecha_pago': {
        const dias = diasHasta(p.fecha_pago_estimada);
        const mostrarBadgeVence = p.estado === 'aprobado' && dias !== null && dias <= 7;
        return (
          <span className={styles.fechaPagoCell}>
            <span className={styles.tdSecondary}>{formatDate(p.fecha_pago_estimada)}</span>
            {mostrarBadgeVence && (
              <span
                className={dias < 0 ? styles.badgeVencido : styles.badgeVenceUrgente}
              >
                <Clock size={11} />
                {dias < 0 ? `Vencido ${Math.abs(dias)}d` : dias === 0 ? 'Hoy' : `${dias}d`}
              </span>
            )}
          </span>
        );
      }
      case 'estado':
        return <EstadoBadge variant="pedido" estado={p.estado} />;
      case 'acciones':
        return renderAcciones(p);
      default:
        return null;
    }
  };

  return (
    <div className={styles.container}>
      {/* Filters + primary action */}
      <FiltersBar
        actions={
          canManage && (
            <button className={styles.btnSuccess} onClick={handleOpenCrear}>
              <Plus size={14} /> Nuevo pedido
            </button>
          )
        }
      >
        <select
          className={styles.select}
          value={filtroEstado}
          onChange={(e) => setFiltroEstado(e.target.value)}
          aria-label="Filtrar por estado"
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
          aria-label="Filtrar por empresa"
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
          aria-label="Desde"
        />
        <input
          type="date"
          className={styles.input}
          value={filtroHasta}
          onChange={(e) => setFiltroHasta(e.target.value)}
          title="Hasta"
          aria-label="Hasta"
        />
        <SearchInput
          value={busqueda}
          onChange={setBusqueda}
          placeholder="Buscar por número..."
          size="sm"
          className={styles.searchWrapper}
        />
      </FiltersBar>

      {pedidosError && (
        <div className={styles.errorBanner}>{pedidosError}</div>
      )}

      {/* Table */}
      {loading && items.length === 0 ? (
        <LoadingBlock text="Cargando pedidos…" />
      ) : (
        <>
          <DataTable
            columns={COLUMNS}
            rows={items}
            renderCell={renderCell}
            empty={{
              icon: <Inbox size={28} strokeWidth={1.5} />,
              title: 'No hay pedidos con los filtros aplicados.',
            }}
            minWidth="1100px"
          />

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
        </>
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

      {/* Hard-delete (papelera) modal */}
      <ModalConfirmarEliminacion
        open={!!eliminarModal}
        onClose={() => {
          setEliminarModal(null);
          setEliminarError(null);
        }}
        onConfirm={handleConfirmEliminar}
        titulo="Eliminar pedido definitivamente"
        entidadTipo="pedido"
        entidadNumero={eliminarModal?.numero || ''}
        sourceText={
          eliminarModal
            ? [eliminarModal.numero, eliminarModal.proveedor_nombre, eliminarModal.empresa_nombre]
            : ''
        }
        loading={eliminarLoading}
        error={eliminarError}
      />
    </div>
  );
}
