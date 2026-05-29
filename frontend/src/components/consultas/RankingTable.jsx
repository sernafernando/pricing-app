import { ChevronUp, ChevronDown, ChevronsUpDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertCircle, PackageSearch } from 'lucide-react';
import styles from './RankingTable.module.css';

// Columns and their sort keys (matches backend SORT_COLUMNS whitelist)
const COLUMNS = [
  { key: 'codigo', label: 'Código', sortable: true, align: 'left' },
  { key: 'descripcion', label: 'Descripción', sortable: true, align: 'left' },
  { key: 'marca', label: 'Marca', sortable: true, align: 'left' },
  { key: 'categoria', label: 'Categoría', sortable: true, align: 'left' },
  { key: null, label: 'PM', sortable: false, align: 'left' },
  { key: 'dias_sin_venta', label: 'Días sin venta', sortable: true, align: 'right' },
  { key: 'unidades_vendidas_ventana', label: 'Uds. vendidas', sortable: true, align: 'right' },
  { key: 'total_stock', label: 'Stock total', sortable: true, align: 'right' },
  { key: 'valor_costo', label: 'Costo (ARS)', sortable: true, align: 'right' },
  { key: 'valor_venta', label: 'Venta (ARS)', sortable: true, align: 'right' },
  { key: 'last_purchase_date', label: 'Última compra', sortable: true, align: 'left' },
  { key: null, label: 'Días ageing ERP', sortable: false, align: 'right' },
];

function SortIcon({ column, sortBy, sortDir }) {
  if (!column) return null;
  if (column !== sortBy) return <ChevronsUpDown size={13} className={styles.sortIcon} />;
  return sortDir === 'asc'
    ? <ChevronUp size={13} className={styles.sortIconActive} />
    : <ChevronDown size={13} className={styles.sortIconActive} />;
}

function formatARS(value, moneda) {
  if (value == null) return '—';
  const formatted = new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'ARS',
    maximumFractionDigits: 0,
  }).format(value);

  if (moneda && moneda !== 'ARS') {
    return (
      <span className={styles.valueWithBadge}>
        {formatted}
        <span className={styles.monedaBadge}>{moneda}</span>
      </span>
    );
  }
  return formatted;
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    return new Date(dateStr).toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

export default function RankingTable({
  items,
  loading,
  error,
  sortBy,
  sortDir,
  onSort,
  page,
  totalPages,
  total,
  pageSize,
  onGoToPage,
}) {
  function handleHeaderClick(col) {
    if (col.sortable && col.key) {
      onSort(col.key);
    }
  }

  const startRow = (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);

  return (
    <div className={styles.wrapper}>
      {/* Table scroll container */}
      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead className="table-tesla-head">
            <tr>
              {COLUMNS.map((col, idx) => (
                <th
                  key={col.key ?? `col-${idx}`}
                  className={[
                    col.sortable ? 'sortable' : '',
                    col.key === sortBy ? 'sorted' : '',
                    col.align === 'right' ? styles.alignRight : '',
                  ].join(' ')}
                  onClick={() => handleHeaderClick(col)}
                  aria-sort={
                    col.key === sortBy
                      ? sortDir === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : undefined
                  }
                >
                  <span className={styles.thInner}>
                    {col.label}
                    <SortIcon column={col.key} sortBy={sortBy} sortDir={sortDir} />
                  </span>
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="table-tesla-body">
            {/* Loading overlay rows */}
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className={styles.stateCell}>
                  <div className={styles.loadingState}>
                    <div className={styles.spinner} />
                    <span>Cargando ranking...</span>
                  </div>
                </td>
              </tr>
            )}

            {/* Error state */}
            {error && !loading && (
              <tr>
                <td colSpan={COLUMNS.length} className={styles.stateCell}>
                  <div className={styles.errorState}>
                    <AlertCircle size={20} />
                    <span>{error}</span>
                  </div>
                </td>
              </tr>
            )}

            {/* Empty state */}
            {!loading && !error && items.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className={styles.stateCell}>
                  <div className={styles.emptyState}>
                    <PackageSearch size={32} />
                    <span>No hay productos con los filtros seleccionados.</span>
                  </div>
                </td>
              </tr>
            )}

            {/* Data rows */}
            {items.map((item) => (
              <tr key={item.item_id} className={loading ? styles.rowLoading : ''}>
                <td>{item.codigo ?? '—'}</td>
                <td className={styles.descripcion}>{item.descripcion ?? '—'}</td>
                <td>{item.marca ?? '—'}</td>
                <td>{item.categoria ?? '—'}</td>
                <td>{item.pm ?? <span className={styles.sinPm}>Sin PM</span>}</td>
                <td className={styles.numeric}>
                  {item.dias_sin_venta != null ? item.dias_sin_venta : '—'}
                </td>
                <td className={styles.numeric}>{item.unidades_vendidas_ventana ?? 0}</td>
                <td className={styles.numeric}>{item.total_stock ?? 0}</td>
                <td className={styles.numeric}>
                  {formatARS(item.valor_costo, item.moneda_costo)}
                </td>
                <td className={styles.numeric}>{formatARS(item.valor_venta, null)}</td>
                <td>{formatDate(item.last_purchase_date)}</td>
                <td className={styles.numeric}>
                  {item.erp_ageing_dias != null ? item.erp_ageing_dias : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      {total > 0 && (
        <div className={styles.pagination}>
          <span className={styles.paginationInfo}>
            {startRow}–{endRow} de {total.toLocaleString('es-AR')} productos
          </span>
          <div className={styles.paginationControls}>
            <button
              className={styles.pageBtn}
              onClick={() => onGoToPage(1)}
              disabled={page === 1}
              aria-label="Primera página"
            >
              <ChevronsLeft size={16} />
            </button>
            <button
              className={styles.pageBtn}
              onClick={() => onGoToPage(page - 1)}
              disabled={page === 1}
              aria-label="Página anterior"
            >
              <ChevronLeft size={16} />
            </button>
            <span className={styles.pageNumber}>
              Pág. {page} / {totalPages}
            </span>
            <button
              className={styles.pageBtn}
              onClick={() => onGoToPage(page + 1)}
              disabled={page >= totalPages}
              aria-label="Página siguiente"
            >
              <ChevronRight size={16} />
            </button>
            <button
              className={styles.pageBtn}
              onClick={() => onGoToPage(totalPages)}
              disabled={page >= totalPages}
              aria-label="Última página"
            >
              <ChevronsRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
