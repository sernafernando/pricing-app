import { useCallback, useEffect, useState } from 'react';
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
} from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import useComprasOP from '../../hooks/useComprasOP';
import ModalOrdenPagoNueva from './ModalOrdenPagoNueva';
import ModalEjecutarPago from './ModalEjecutarPago';
import PanelImputaciones from './PanelImputaciones';
import styles from './TabOrdenesPago.module.css';

const PAGE_SIZE = 50;

const ESTADOS_OP = ['pendiente', 'pagado', 'anulado'];

const estadoBadgeClass = (estado) => {
  switch (estado) {
    case 'pendiente':
      return styles.badgePendiente;
    case 'pagado':
      return styles.badgePagado;
    case 'anulado':
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

export default function TabOrdenesPago() {
  const { tienePermiso } = usePermisos();
  const canManage = tienePermiso('administracion.gestionar_ordenes_compra');
  const canPay = tienePermiso('administracion.ejecutar_pagos');

  const opApi = useComprasOP();

  // Sub-tab: OPs (default) | Imputaciones (COMPRAS-7.5)
  const [subTab, setSubTab] = useState('ops');

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
  const [anularModal, setAnularModal] = useState(null); // op obj
  const [anularMotivo, setAnularMotivo] = useState('');
  const [anularLoading, setAnularLoading] = useState(false);
  const [anularError, setAnularError] = useState(null);

  const fetchOPs = useCallback(async () => {
    const params = { page, page_size: PAGE_SIZE };
    if (filtroEstado) params.estado = filtroEstado;
    if (filtroEmpresa) params.empresa_id = filtroEmpresa;
    if (filtroProveedorId) params.proveedor_id = filtroProveedorId;
    if (filtroDesde) params.desde = filtroDesde;
    if (filtroHasta) params.hasta = filtroHasta;

    try {
      const data = await opApi.listar(params);
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch {
      setItems([]);
      setTotal(0);
    }
  }, [opApi, page, filtroEstado, filtroEmpresa, filtroProveedorId, filtroDesde, filtroHasta]);

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
    fetchOPs();
  }, [fetchOPs]);

  useEffect(() => {
    setPage(1);
  }, [filtroEstado, filtroEmpresa, filtroProveedorId, filtroDesde, filtroHasta]);

  // Actions
  const handleDistribuir = async (op) => {
    try {
      await opApi.distribuirAutomatico(op.id);
      fetchOPs();
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
      await opApi.anular(anularModal.id, motivo);
      setAnularModal(null);
      setAnularMotivo('');
      fetchOPs();
    } catch (err) {
      setAnularError(err.response?.data?.detail || 'Error al anular la OP.');
    } finally {
      setAnularLoading(false);
    }
  };

  const renderAcciones = (op) => {
    const puedePagar = canPay && op.estado === 'pendiente';
    const puedeAnular = canPay && op.estado === 'pagado';
    const puedeDistribuir =
      canManage &&
      op.estado === 'pendiente' &&
      (op.modo_imputacion === 'a_cuenta' || op.modo_imputacion === 'mixta');

    return (
      <div className={styles.rowActions}>
        <button
          className={styles.iconBtn}
          onClick={() => opApi.obtener(op.id).catch(() => {})}
          aria-label="Ver"
          title="Ver detalle"
        >
          <Eye size={14} />
        </button>
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
      </div>
    );
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const loading = opApi.loading;

  return (
    <div className={styles.container}>
      {/* Sub-tab switcher: OPs / Imputaciones (COMPRAS-7.5) */}
      <div className={styles.subTabBar}>
        <button
          type="button"
          className={`${styles.subTabBtn} ${subTab === 'ops' ? styles.subTabActive : ''}`}
          onClick={() => setSubTab('ops')}
        >
          Órdenes de Pago
        </button>
        <button
          type="button"
          className={`${styles.subTabBtn} ${subTab === 'imputaciones' ? styles.subTabActive : ''}`}
          onClick={() => setSubTab('imputaciones')}
        >
          Imputaciones
        </button>
      </div>

      {subTab === 'imputaciones' && <PanelImputaciones />}

      {subTab === 'ops' && (
        <>
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
        </div>
        {canManage && (
          <button className={styles.btnSuccess} onClick={() => setShowModalNueva(true)}>
            <Plus size={14} /> Nueva OP
          </button>
        )}
      </div>

      {opApi.error && <div className={styles.errorBanner}>{opApi.error}</div>}

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
                <th>Proveedor</th>
                <th>Empresa</th>
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
                  <td>#{op.proveedor_id}</td>
                  <td>#{op.empresa_id}</td>
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
                  <td className={styles.tdSecondary}>{op.fecha_pago_real || '—'}</td>
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
          onClose={(reload) => {
            setShowModalNueva(false);
            if (reload) fetchOPs();
          }}
        />
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
        </>
      )}
    </div>
  );
}
