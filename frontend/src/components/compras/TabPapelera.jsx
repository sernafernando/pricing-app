import { useCallback, useEffect, useState } from 'react';
import {
  Trash2,
  Eye,
  ChevronLeft,
  ChevronRight,
  X,
  FileText,
  Wallet,
  Inbox,
} from 'lucide-react';
import useComprasPapelera from '../../hooks/useComprasPapelera';
import DataTable from './_shared/DataTable';
import LoadingBlock from './_shared/LoadingBlock';
import FiltersBar from './_shared/FiltersBar';
import styles from './TabPapelera.module.css';

const COLUMNS = [
  { key: 'tipo', label: 'Tipo', width: '120px' },
  { key: 'numero', label: 'Número', width: '160px' },
  { key: 'empresa', label: 'Empresa', width: '140px' },
  { key: 'proveedor', label: 'Proveedor' },
  { key: 'estado_original', label: 'Estado original', width: '140px' },
  { key: 'eliminado_por', label: 'Eliminado por', width: '140px' },
  { key: 'fecha', label: 'Fecha', width: '140px' },
  { key: 'motivo', label: 'Motivo' },
  { key: 'acciones', label: '', align: 'right', width: '60px' },
];

const PAGE_SIZE = 50;

const TIPOS = [
  { value: '', label: 'Todos' },
  { value: 'pedido_compra', label: 'Pedidos' },
  { value: 'orden_pago', label: 'Órdenes de pago' },
];

const iconoPorTipo = (tipo) => (tipo === 'pedido_compra' ? FileText : Wallet);

const labelTipo = (tipo) => {
  if (tipo === 'pedido_compra') return 'Pedido';
  if (tipo === 'orden_pago') return 'OP';
  return tipo || '—';
};

const formatDateTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('es-AR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return iso;
  }
};

export default function TabPapelera() {
  const { listar, obtener, loading, error } = useComprasPapelera();

  // ── Filters + data ──
  const [filtroTipo, setFiltroTipo] = useState('');
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  // ── Detalle modal ──
  const [detalleAbierto, setDetalleAbierto] = useState(null); // { ...papelera } | null
  const [detalleLoading, setDetalleLoading] = useState(false);
  const [detalleError, setDetalleError] = useState(null);

  const fetchPapelera = useCallback(async () => {
    const params = { page, page_size: PAGE_SIZE };
    if (filtroTipo) params.entidad_tipo = filtroTipo;
    try {
      const data = await listar(params);
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch {
      setItems([]);
      setTotal(0);
    }
  }, [listar, page, filtroTipo]);

  useEffect(() => {
    fetchPapelera();
  }, [fetchPapelera]);

  useEffect(() => {
    setPage(1);
  }, [filtroTipo]);

  const handleVerDetalle = async (item) => {
    setDetalleLoading(true);
    setDetalleError(null);
    try {
      const detalle = await obtener(item.id);
      setDetalleAbierto(detalle);
    } catch (err) {
      setDetalleError(err.response?.data?.detail || 'Error al cargar el detalle.');
    } finally {
      setDetalleLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className={styles.container}>
      {/* Banner informativo */}
      <div className={styles.banner}>
        <Trash2 size={14} className={styles.bannerIcon} />
        <span>
          Registro auditable de hard-deletes. Los datos <strong>no</strong> pueden restaurarse
          — solo se conservan para trazabilidad.
        </span>
      </div>

      {/* Filters */}
      <FiltersBar>
        <select
          className={styles.select}
          value={filtroTipo}
          onChange={(e) => setFiltroTipo(e.target.value)}
          aria-label="Filtrar por tipo"
        >
          {TIPOS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </FiltersBar>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {loading && items.length === 0 ? (
        <LoadingBlock text="Cargando papelera…" />
      ) : (
        <>
          <DataTable
            columns={COLUMNS}
            rows={items}
            renderCell={(it, col) => {
              switch (col.key) {
                case 'tipo': {
                  const Icon = iconoPorTipo(it.entidad_tipo);
                  return (
                    <span className={styles.tipoBadge}>
                      <Icon size={13} />
                      {labelTipo(it.entidad_tipo)}
                    </span>
                  );
                }
                case 'numero':
                  return (
                    <span className={styles.tdMono}>
                      {it.numero || `#${it.entidad_id_original}`}
                    </span>
                  );
                case 'empresa':
                  return it.empresa_nombre || '—';
                case 'proveedor':
                  return it.proveedor_nombre || '—';
                case 'estado_original':
                  return <span className={styles.tdSecondary}>{it.estado_original || '—'}</span>;
                case 'eliminado_por':
                  return it.eliminado_por_nombre || `#${it.eliminado_por_id}`;
                case 'fecha':
                  return <span className={styles.tdSecondary}>{formatDateTime(it.created_at)}</span>;
                case 'motivo':
                  return (
                    <span className={styles.tdMotivo} title={it.motivo}>
                      {it.motivo}
                    </span>
                  );
                case 'acciones':
                  return (
                    <button
                      type="button"
                      className={styles.iconBtn}
                      onClick={() => handleVerDetalle(it)}
                      aria-label="Ver snapshot"
                      title="Ver snapshot completo"
                    >
                      <Eye size={14} />
                    </button>
                  );
                default:
                  return null;
              }
            }}
            empty={{
              icon: <Inbox size={28} strokeWidth={1.5} />,
              title: 'La papelera está vacía.',
            }}
            minWidth="1200px"
          />

          {totalPages > 1 && (
            <div className={styles.pagination}>
              <span>
                {total} registros — Página {page} de {totalPages}
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

      {/* Detalle modal */}
      {(detalleAbierto || detalleLoading) && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>
                Snapshot papelera
                {detalleAbierto?.numero ? ` — ${detalleAbierto.numero}` : ''}
              </span>
              <button
                type="button"
                className={styles.modalCloseBtn}
                onClick={() => {
                  setDetalleAbierto(null);
                  setDetalleError(null);
                }}
                aria-label="Cerrar"
              >
                <X size={18} />
              </button>
            </div>

            {detalleError && <div className={styles.errorBanner}>{detalleError}</div>}

            {detalleLoading && (
              <div className={styles.centered}>
                <Loader2 size={20} className={styles.spin} /> Cargando detalle...
              </div>
            )}

            {detalleAbierto && !detalleLoading && (
              <div className={styles.detalleGrid}>
                <div className={styles.metaGroup}>
                  <div>
                    <span className={styles.metaLabel}>Tipo:</span>{' '}
                    <strong>{labelTipo(detalleAbierto.entidad_tipo)}</strong>
                  </div>
                  <div>
                    <span className={styles.metaLabel}>ID original:</span>{' '}
                    <code>{detalleAbierto.entidad_id_original}</code>
                  </div>
                  <div>
                    <span className={styles.metaLabel}>Estado original:</span>{' '}
                    {detalleAbierto.estado_original || '—'}
                  </div>
                  <div>
                    <span className={styles.metaLabel}>Eliminado por:</span>{' '}
                    {detalleAbierto.eliminado_por_nombre || `#${detalleAbierto.eliminado_por_id}`}
                  </div>
                  <div>
                    <span className={styles.metaLabel}>Fecha:</span>{' '}
                    {formatDateTime(detalleAbierto.created_at)}
                  </div>
                  <div>
                    <span className={styles.metaLabel}>Challenge:</span>{' '}
                    <code>{detalleAbierto.challenge_palabra || '—'}</code>
                  </div>
                </div>

                <div className={styles.metaGroup}>
                  <div className={styles.metaLabel}>Motivo</div>
                  <div className={styles.motivoBlock}>{detalleAbierto.motivo}</div>
                </div>

                <div className={styles.metaGroup}>
                  <div className={styles.metaLabel}>Snapshot (JSON)</div>
                  <pre className={styles.snapshotPre}>
                    {JSON.stringify(detalleAbierto.snapshot, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
