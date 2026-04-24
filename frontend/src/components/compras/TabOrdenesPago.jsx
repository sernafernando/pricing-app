import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Plus,
  Loader2,
  Eye,
  Wallet,
  Ban,
  Layers,
  ChevronLeft,
  ChevronRight,
  X,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Trash2,
  Pencil,
  XCircle,
} from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import useComprasOP from '../../hooks/useComprasOP';
import ModalOrdenPagoNueva from './ModalOrdenPagoNueva';
import ModalEjecutarPago from './ModalEjecutarPago';
import ModalOrdenPagoDetalle from './ModalOrdenPagoDetalle';
import ModalConfirmarEliminacion from './ModalConfirmarEliminacion';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import styles from './TabOrdenesPago.module.css';

const PAGE_SIZE = 50;

const ESTADOS_OP = ['pendiente', 'pagado', 'anulado', 'cancelado'];

const estadoBadgeClass = (estado) => {
  switch (estado) {
    case 'pendiente':
      return styles.badgePendiente;
    case 'pagado':
      return styles.badgePagado;
    case 'anulado':
      return styles.badgeAnulado;
    case 'cancelado':
      return styles.badgeAnulado;
    default:
      return styles.badgeNeutral;
  }
};

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

// dd/mm/yyyy, tratando YYYY-MM-DD como fecha local (sin bug UTC off-by-one).
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

export default function TabOrdenesPago() {
  const { tienePermiso } = usePermisos();
  const canManage = tienePermiso('administracion.gestionar_ordenes_compra');
  const canPay = tienePermiso('administracion.ejecutar_pagos');
  const canDeleteBasura = tienePermiso('administracion.eliminar_compras_basura');

  // Desestructurar funciones memoizadas para evitar loop en useEffect/useCallback.
  const {
    listar: listarOPs,
    obtener: obtenerOP,
    distribuirAutomatico,
    anular: anularOP,
    eliminar: eliminarOP,
    cancelarPendiente: cancelarOPPendiente,
    loading: opLoading,
    error: opError,
  } = useComprasOP();

  // ── Hard-delete papelera state ──
  const [eliminarModal, setEliminarModal] = useState(null); // op | null
  const [eliminarLoading, setEliminarLoading] = useState(false);
  const [eliminarError, setEliminarError] = useState(null);

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroEmpresa, setFiltroEmpresa] = useState('');
  const [filtroProveedorId, setFiltroProveedorId] = useState('');
  const [filtroDesde, setFiltroDesde] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');

  const [empresas, setEmpresas] = useState([]);

  const [showModalNueva, setShowModalNueva] = useState(false);
  const [opPagar, setOpPagar] = useState(null);
  const [opDetalle, setOpDetalle] = useState(null);
  const [anularModal, setAnularModal] = useState(null); // op obj
  const [anularMotivo, setAnularMotivo] = useState('');
  const [anularLoading, setAnularLoading] = useState(false);
  const [anularError, setAnularError] = useState(null);

  // ── Editar OP pendiente (sub-batch 1.1) ──
  // `opEditar` es { op, items } cargado desde /ordenes-pago/{id} para
  // pre-cargar el modal con los items del último evento items_*.
  const [opEditar, setOpEditar] = useState(null);
  const [opEditarLoading, setOpEditarLoading] = useState(false);
  const [opEditarError, setOpEditarError] = useState(null);

  // ── Cancelar OP pendiente (sub-batch 1.2) ──
  const [cancelarModal, setCancelarModal] = useState(null); // op obj
  const [cancelarMotivo, setCancelarMotivo] = useState('');
  const [cancelarLoading, setCancelarLoading] = useState(false);
  const [cancelarError, setCancelarError] = useState(null);

  // ── Pedidos pendientes de pago (Batch C) ──
  const [pendientes, setPendientes] = useState([]);
  const [pendientesOpen, setPendientesOpen] = useState(true);
  const [pedidoInicialOP, setPedidoInicialOP] = useState(null);

  // Deep-link: ?tab=ordenes-pago&accion=nueva-op&pedido_id=123
  const [searchParams, setSearchParams] = useSearchParams();

  const fetchOPs = useCallback(async () => {
    const params = { page, page_size: PAGE_SIZE };
    if (filtroEstado) params.estado = filtroEstado;
    if (filtroEmpresa) params.empresa_id = filtroEmpresa;
    if (filtroProveedorId) params.proveedor_id = filtroProveedorId;
    if (filtroDesde) params.desde = filtroDesde;
    if (filtroHasta) params.hasta = filtroHasta;

    try {
      const data = await listarOPs(params);
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch {
      setItems([]);
      setTotal(0);
    }
  }, [listarOPs, page, filtroEstado, filtroEmpresa, filtroProveedorId, filtroDesde, filtroHasta]);

  const fetchEmpresas = useCallback(async () => {
    try {
      const { data } = await api.get('/admin/empresas');
      setEmpresas(data || []);
    } catch {
      setEmpresas([]);
    }
  }, []);

  const fetchPendientes = useCallback(async () => {
    try {
      const { data } = await api.get('/administracion/compras/pedidos/pendientes-pago');
      setPendientes(Array.isArray(data) ? data : []);
    } catch {
      setPendientes([]);
    }
  }, []);

  useEffect(() => {
    fetchEmpresas();
  }, [fetchEmpresas]);

  useEffect(() => {
    fetchOPs();
  }, [fetchOPs]);

  useEffect(() => {
    fetchPendientes();
  }, [fetchPendientes]);

  // Deep-link: si vino accion=nueva-op&pedido_id=N, pre-cargar y abrir modal.
  useEffect(() => {
    const accion = searchParams.get('accion');
    const pedidoIdParam = searchParams.get('pedido_id');
    if (accion !== 'nueva-op' || !pedidoIdParam) return;

    const pedidoId = Number(pedidoIdParam);
    if (!Number.isInteger(pedidoId) || pedidoId <= 0) return;

    // Intentamos matchear con los pendientes ya cargados.
    const candidato = pendientes.find((p) => p.id === pedidoId);
    if (candidato) {
      setPedidoInicialOP(candidato);
      setShowModalNueva(true);
      // Limpiamos los params para no re-abrir al re-render.
      const next = new URLSearchParams(searchParams);
      next.delete('accion');
      next.delete('pedido_id');
      setSearchParams(next, { replace: true });
    }
  }, [pendientes, searchParams, setSearchParams]);

  useEffect(() => {
    setPage(1);
  }, [filtroEstado, filtroEmpresa, filtroProveedorId, filtroDesde, filtroHasta]);

  // Actions
  const handleDistribuir = async (op) => {
    try {
      await distribuirAutomatico(op.id);
      fetchOPs();
      fetchPendientes();
    } catch {
      /* noop */
    }
  };

  const handleAnularSubmit = async () => {
    if (!anularModal) return;
    const motivo = anularMotivo.trim();
    if (!motivo) {
      setAnularError('El motivo es requerido.');
      return;
    }
    setAnularLoading(true);
    setAnularError(null);
    try {
      await anularOP(anularModal.id, motivo);
      setAnularModal(null);
      setAnularMotivo('');
      fetchOPs();
      fetchPendientes();
    } catch (err) {
      setAnularError(err.response?.data?.detail || 'Error al anular la OP.');
    } finally {
      setAnularLoading(false);
    }
  };

  const handleGenerarOPDesdePedido = (pedido) => {
    setPedidoInicialOP(pedido);
    setShowModalNueva(true);
  };

  /**
   * Abre el modal de edición de OP pendiente. Fetchea el detalle para
   * extraer los items del último evento items_registrados/items_editados.
   */
  const handleOpenEditar = async (op) => {
    setOpEditarLoading(true);
    setOpEditarError(null);
    try {
      const detalle = await obtenerOP(op.id);
      // Buscar el evento items_* más reciente (editados tiene prioridad).
      const eventos = detalle?.eventos || [];
      const eventoItems = eventos.find(
        (e) => e.tipo === 'items_editados' || e.tipo === 'items_registrados'
      );
      const opItems = eventoItems?.payload?.items || [];
      setOpEditar({ op: detalle, opItems });
    } catch (err) {
      setOpEditarError(
        err.response?.data?.detail || 'Error al cargar la OP para edición.'
      );
    } finally {
      setOpEditarLoading(false);
    }
  };

  const handleCancelarSubmit = async () => {
    if (!cancelarModal) return;
    const motivo = cancelarMotivo.trim();
    if (!motivo) {
      setCancelarError('El motivo es requerido.');
      return;
    }
    setCancelarLoading(true);
    setCancelarError(null);
    try {
      await cancelarOPPendiente(cancelarModal.id, motivo);
      setCancelarModal(null);
      setCancelarMotivo('');
      fetchOPs();
      fetchPendientes();
    } catch (err) {
      setCancelarError(err.response?.data?.detail || 'Error al cancelar la OP.');
    } finally {
      setCancelarLoading(false);
    }
  };

  // Fecha formateada + helper "vence en N días"
  const diasHasta = (isoDate) => {
    if (!isoDate) return null;
    try {
      const [y, m, d] = String(isoDate).split('T')[0].split('-');
      if (!y || !m || !d) return null;
      const target = new Date(Number(y), Number(m) - 1, Number(d));
      const hoy = new Date();
      hoy.setHours(0, 0, 0, 0);
      const diffMs = target - hoy;
      return Math.round(diffMs / (1000 * 60 * 60 * 24));
    } catch {
      return null;
    }
  };

  const renderAcciones = (op) => {
    const puedePagar = canPay && op.estado === 'pendiente';
    const puedeEditar = canManage && op.estado === 'pendiente';
    const puedeCancelarPendiente = canManage && op.estado === 'pendiente';
    const puedeAnular = canPay && op.estado === 'pagado';
    const puedeDistribuir =
      canManage &&
      op.estado === 'pendiente' &&
      (op.modo_imputacion === 'a_cuenta' || op.modo_imputacion === 'mixta');
    const puedeEliminarBasura = canDeleteBasura && op.puede_eliminar === true;

    return (
      <div className={styles.rowActions}>
        <button
          className={styles.iconBtn}
          onClick={() => setOpDetalle(op)}
          aria-label="Ver"
          title="Ver detalle"
        >
          <Eye size={14} />
        </button>
        {puedeEditar && (
          <button
            className={styles.iconBtn}
            onClick={() => handleOpenEditar(op)}
            disabled={opEditarLoading}
            aria-label="Editar"
            title="Editar OP pendiente"
          >
            <Pencil size={14} />
          </button>
        )}
        {puedePagar && (
          <button
            className={styles.iconBtnSuccess}
            onClick={() => setOpPagar(op)}
            aria-label="Pagar"
            title="Ejecutar pago"
          >
            <Wallet size={14} />
          </button>
        )}
        {puedeDistribuir && (
          <button
            className={styles.iconBtnPrimary}
            onClick={() => handleDistribuir(op)}
            aria-label="Distribuir FIFO"
            title="Distribuir automáticamente (FIFO)"
          >
            <Layers size={14} />
          </button>
        )}
        {puedeCancelarPendiente && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => {
              setCancelarModal(op);
              setCancelarMotivo('');
              setCancelarError(null);
            }}
            aria-label="Cancelar pendiente"
            title="Cancelar OP pendiente"
          >
            <XCircle size={14} />
          </button>
        )}
        {puedeAnular && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => {
              setAnularModal(op);
              setAnularMotivo('');
              setAnularError(null);
            }}
            aria-label="Anular"
            title="Anular OP"
          >
            <Ban size={14} />
          </button>
        )}
        {puedeEliminarBasura && (
          <button
            className={styles.iconBtnDanger}
            onClick={() => {
              setEliminarModal(op);
              setEliminarError(null);
            }}
            aria-label="Eliminar definitivamente"
            title="Eliminar definitivamente (papelera)"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    );
  };

  const handleConfirmEliminar = async ({ motivo, challenge_palabra_usada }) => {
    if (!eliminarModal) return;
    setEliminarLoading(true);
    setEliminarError(null);
    try {
      await eliminarOP(eliminarModal.id, motivo, challenge_palabra_usada);
      setEliminarModal(null);
      fetchOPs();
    } catch (err) {
      setEliminarError(err.response?.data?.detail || 'Error al eliminar la OP.');
    } finally {
      setEliminarLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const loading = opLoading;

  return (
    <div className={styles.container}>
      {/* Sección: pedidos aprobados esperando pago */}
      <div className={styles.pendientesSection}>
        <button
          type="button"
          className={styles.pendientesHeader}
          onClick={() => setPendientesOpen((v) => !v)}
          aria-expanded={pendientesOpen}
        >
          <div className={styles.pendientesTitle}>
            <AlertCircle size={16} />
            <span>Pedidos aprobados esperando pago</span>
            <span className={styles.pendientesCount}>{pendientes.length}</span>
          </div>
          {pendientesOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {pendientesOpen && (
          <div className={styles.pendientesBody}>
            {pendientes.length === 0 ? (
              <div className={styles.pendientesEmpty}>
                No hay pedidos aprobados esperando pago.
              </div>
            ) : (
              <div className={styles.pendientesList}>
                {pendientes.map((p) => {
                  const dias = diasHasta(p.fecha_pago_estimada);
                  const urgente = dias !== null && dias <= 7;
                  const vencido = dias !== null && dias < 0;
                  return (
                    <div key={p.id} className={styles.pendienteCard}>
                      <div className={styles.pendienteInfo}>
                        <span className={styles.pendienteNumero}>{p.numero}</span>
                        <span className={styles.pendienteProveedor}>
                          {p.proveedor_nombre || `#${p.proveedor_id}`}
                        </span>
                        <span className={styles.pendienteMonto}>
                          {formatCurrency(p.saldo_pendiente ?? p.monto, p.moneda)}
                        </span>
                        {p.fecha_pago_estimada && (
                          <span
                            className={
                              vencido
                                ? styles.pendienteFechaVencida
                                : urgente
                                ? styles.pendienteFechaUrgente
                                : styles.pendienteFecha
                            }
                          >
                            <Clock size={12} />
                            {vencido
                              ? `Vencido hace ${Math.abs(dias)} días`
                              : urgente
                              ? `Vence en ${dias} días`
                              : `Vence ${formatDate(p.fecha_pago_estimada)}`}
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        className={styles.btnPrimarySm}
                        onClick={() => handleGenerarOPDesdePedido(p)}
                        disabled={!canManage}
                        title={canManage ? 'Crear OP imputada a este pedido' : 'Sin permiso'}
                      >
                        <Plus size={12} /> Generar OP
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Top bar */}
      <div className={styles.topBar}>
        <div className={styles.filters}>
          <select
            className={styles.select}
            value={filtroEstado}
            onChange={(e) => setFiltroEstado(e.target.value)}
          >
            <option value="">Todos los estados</option>
            {ESTADOS_OP.map((estado) => (
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
        </div>
        {canManage && (
          <button className={styles.btnSuccess} onClick={() => setShowModalNueva(true)}>
            <Plus size={14} /> Nueva OP
          </button>
        )}
      </div>

      {opError && <div className={styles.errorBanner}>{opError}</div>}

      {/* Table */}
      {loading && items.length === 0 ? (
        <div className={styles.centered}>
          <Loader2 size={20} className={styles.spin} /> Cargando órdenes de pago...
        </div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>No hay órdenes de pago con los filtros aplicados.</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Número</th>
                <th>Empresa</th>
                <th>Proveedor</th>
                <th>Moneda</th>
                <th className={styles.thRight}>Monto</th>
                <th>Modo</th>
                <th>Estado</th>
                <th>Fecha pago</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {items.map((op) => (
                <tr key={op.id}>
                  <td className={styles.tdMono}>{op.numero}</td>
                  <td>{op.empresa_nombre || `#${op.empresa_id}`}</td>
                  <td>{op.proveedor_nombre || `#${op.proveedor_id}`}</td>
                  <td>{op.moneda}</td>
                  <td className={styles.tdRight}>
                    {formatCurrency(op.monto_total, op.moneda)}
                  </td>
                  <td className={styles.tdSecondary}>{op.modo_imputacion}</td>
                  <td>
                    <span className={`${styles.badge} ${estadoBadgeClass(op.estado)}`}>
                      {op.estado}
                    </span>
                  </td>
                  <td className={styles.tdSecondary}>{formatDate(op.fecha_pago_real)}</td>
                  <td>{renderAcciones(op)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <div className={styles.pagination}>
              <span>
                {total} OPs — Página {page} de {totalPages}
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
      {showModalNueva && (
        <ModalOrdenPagoNueva
          empresas={empresas}
          pedidoInicial={pedidoInicialOP}
          pendientesDelProveedor={pendientes}
          onClose={(reload) => {
            setShowModalNueva(false);
            setPedidoInicialOP(null);
            if (reload) {
              fetchOPs();
              fetchPendientes();
            }
          }}
        />
      )}

      {/* Modal editar OP pendiente (sub-batch 1.1) */}
      {opEditar && (
        <ModalOrdenPagoNueva
          empresas={empresas}
          op={opEditar.op}
          opItems={opEditar.opItems}
          pendientesDelProveedor={pendientes}
          onClose={(reload) => {
            setOpEditar(null);
            if (reload) {
              fetchOPs();
              fetchPendientes();
            }
          }}
        />
      )}

      {opEditarError && (
        <div className={styles.errorBanner}>{opEditarError}</div>
      )}

      {opPagar && (
        <ModalEjecutarPago
          op={opPagar}
          onClose={(reload) => {
            setOpPagar(null);
            if (reload) fetchOPs();
          }}
        />
      )}

      {opDetalle && (
        <ModalOrdenPagoDetalle
          op={opDetalle}
          onClose={(reload) => {
            setOpDetalle(null);
            if (reload) fetchOPs();
          }}
          onEjecutarPago={(op) => setOpPagar(op)}
          onAnular={(op) => {
            setAnularModal(op);
            setAnularMotivo('');
            setAnularError(null);
          }}
        />
      )}

      {/* Modal anular (inline — es chico) */}
      {anularModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>Anular OP {anularModal.numero}</span>
              <button
                className={styles.modalCloseBtn}
                onClick={() => {
                  setAnularModal(null);
                  setAnularMotivo('');
                }}
                aria-label="Cerrar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>
            {anularError && <div className={styles.errorBanner}>{anularError}</div>}
            <p className={styles.modalWarning}>
              Esta acción revierte el movimiento de caja, las imputaciones y deja los pedidos
              vinculados en estado aprobado. Es irreversible.
            </p>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Motivo *</label>
              <textarea
                className={styles.textarea}
                value={anularMotivo}
                onChange={(e) => setAnularMotivo(e.target.value)}
                placeholder="Describí el motivo de la anulación..."
                rows={3}
              />
            </div>
            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.btnSecondary}
                onClick={() => setAnularModal(null)}
                disabled={anularLoading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnDanger}
                onClick={handleAnularSubmit}
                disabled={anularLoading}
              >
                {anularLoading ? 'Anulando...' : 'Anular OP'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal cancelar OP pendiente (sub-batch 1.2) */}
      {cancelarModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>
                Cancelar OP {cancelarModal.numero}
              </span>
              <button
                className={styles.modalCloseBtn}
                onClick={() => {
                  setCancelarModal(null);
                  setCancelarMotivo('');
                }}
                aria-label="Cerrar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>
            {cancelarError && <div className={styles.errorBanner}>{cancelarError}</div>}
            <p className={styles.modalWarning}>
              Esta acción marca la OP como cancelada y no se podrá ejecutar el pago.
              No hay movimientos de caja ni imputaciones que revertir porque la OP
              todavía está pendiente.
            </p>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Motivo *</label>
              <textarea
                className={styles.textarea}
                value={cancelarMotivo}
                onChange={(e) => setCancelarMotivo(e.target.value)}
                placeholder="Ej: cargada con error, monto incorrecto..."
                rows={3}
              />
            </div>
            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.btnSecondary}
                onClick={() => setCancelarModal(null)}
                disabled={cancelarLoading}
              >
                Volver
              </button>
              <button
                type="button"
                className={styles.btnDanger}
                onClick={handleCancelarSubmit}
                disabled={cancelarLoading}
              >
                {cancelarLoading ? 'Cancelando...' : 'Cancelar OP'}
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
        titulo="Eliminar OP definitivamente"
        entidadTipo="orden de pago"
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
