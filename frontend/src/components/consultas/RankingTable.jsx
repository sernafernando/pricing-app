import { ChevronUp, ChevronDown, ChevronsUpDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertCircle, PackageSearch } from 'lucide-react';
import styles from './RankingTable.module.css';

// Columns and their sort keys (matches backend SORT_COLUMNS whitelist)
// valor_costo_ars / valor_costo_usd replace old valor_costo
const COLUMNS = [
  { key: 'codigo', label: 'Código', sortable: true, align: 'left' },
  { key: 'descripcion', label: 'Descripción', sortable: true, align: 'left' },
  { key: 'marca', label: 'Marca', sortable: true, align: 'left' },
  { key: 'categoria', label: 'Categoría', sortable: true, align: 'left' },
  { key: null, label: 'PM', sortable: false, align: 'left' },
  { key: 'dias_sin_venta', label: 'Días sin venta', sortable: true, align: 'right' },
  { key: 'unidades_vendidas_ventana', label: 'Uds. vendidas', sortable: true, align: 'right' },
  { key: 'total_stock', label: 'Stock total', sortable: true, align: 'right' },
  { key: 'valor_costo_ars', label: 'Valor costo', sortable: true, align: 'right' },
  { key: 'valor_venta', label: 'Venta (ARS)', sortable: true, align: 'right' },
  { key: 'last_purchase_date', label: 'Última compra', sortable: true, align: 'left' },
  { key: null, label: 'Días ageing ERP', sortable: false, align: 'right' },
];

/**
 * Sort icon for a column header.
 * Shows a badge number (1, 2, 3…) when the column is part of a multi-sort.
 * Shows the asc/desc chevron for active sort columns.
 */
function SortIcon({ colKey, sort }) {
  if (!colKey) return null;
  const idx = sort.findIndex((s) => s.campo === colKey);
  if (idx === -1) return <ChevronsUpDown size={13} className={styles.sortIcon} />;
  const entry = sort[idx];
  const badge = sort.length > 1 ? <span className={styles.sortBadge}>{idx + 1}</span> : null;
  const arrow =
    entry.dir === 'asc' ? (
      <ChevronUp size={13} className={styles.sortIconActive} />
    ) : (
      <ChevronDown size={13} className={styles.sortIconActive} />
    );
  return (
    <span className={styles.sortIndicator}>
      {badge}
      {arrow}
    </span>
  );
}

function formatARS(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'ARS',
    maximumFractionDigits: 0,
  }).format(value);
}

function formatUSD(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);
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

/**
 * Dual-currency cost cell: shows both USD and ARS stacked.
 * Uses the moneda_costo field as an origin tag (shown as a small badge).
 */
function CostCell({ valorCostoArs, valorCostoUsd, monedaCosto }) {
  const arsStr = formatARS(valorCostoArs);
  const usdStr = formatUSD(valorCostoUsd);
  if (valorCostoArs == null && valorCostoUsd == null) return <span>—</span>;
  return (
    <span className={styles.costCell}>
      <span className={styles.costRow}>
        <span className={styles.costCurrency}>ARS</span>
        <span>{arsStr}</span>
      </span>
      <span className={styles.costRow}>
        <span className={styles.costCurrency}>USD</span>
        <span>{usdStr}</span>
      </span>
      {monedaCosto && (
        <span className={styles.monedaBadge} title={`Costo origen: ${monedaCosto}`}>
          {monedaCosto}
        </span>
      )}
    </span>
  );
}

export default function RankingTable({
  items,
  loading,
  error,
  sort,
  onSort,
  page,
  totalPages,
  total,
  pageSize,
  onGoToPage,
}) {
  /**
   * Handle header click.
   * Passes shiftKey so the hook can decide single vs. multi-sort.
   */
  function handleHeaderClick(col, event) {
    if (col.sortable && col.key) {
      onSort(col.key, event.shiftKey);
    }
  }

  const startRow = (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);

  // Determine the primary sort column key for aria-sort
  const primarySort = sort[0] ?? null;

  return (
    <div className={styles.wrapper}>
      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead className="table-tesla-head">
            <tr>
              {COLUMNS.map((col, idx) => {
                const isActive = col.key && sort.some((s) => s.campo === col.key);
                const isPrimary = col.key && primarySort?.campo === col.key;
                return (
                  <th
                    key={col.key ?? `col-${idx}`}
                    className={[
                      col.sortable ? 'sortable' : '',
                      isActive ? 'sorted' : '',
                      col.align === 'right' ? styles.alignRight : '',
                    ].join(' ')}
                    onClick={(e) => handleHeaderClick(col, e)}
                    title={col.sortable && col.key ? 'Click: ordenar. Shift+Click: orden secundario.' : undefined}
                    aria-sort={
                      isPrimary
                        ? primarySort.dir === 'asc'
                          ? 'ascending'
                          : 'descending'
                        : undefined
                    }
                  >
                    <span className={styles.thInner}>
                      {col.label}
                      <SortIcon colKey={col.key} sort={sort} />
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody className="table-tesla-body">
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
                <td className={styles.numericCost}>
                  <CostCell
                    valorCostoArs={item.valor_costo_ars}
                    valorCostoUsd={item.valor_costo_usd}
                    monedaCosto={item.moneda_costo}
                  />
                </td>
                <td className={styles.numeric}>{formatARS(item.valor_venta)}</td>
                <td>{formatDate(item.last_purchase_date)}</td>
                <td className={styles.numeric}>
                  {item.erp_ageing_dias != null ? item.erp_ageing_dias : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
