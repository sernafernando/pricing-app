import { flexRender } from '@tanstack/react-table';
import styles from '../../pages/TiendaNubeReconcile.module.css';
import RowActionsCell from './RowActionsCell';
import Paginador from './Paginador';
import { COLUMNS, despublicarTargetProductId } from './reconcileColumns';

// General reconciliation table branch: column resize/sort header, body
// rows (with the FALTA_VINCULAR matched-ids annotation and the Acciones
// cell), and its paginator. Extracted verbatim from `TiendaNubeReconcile.jsx`
// (structural extraction, PR-6 pattern).
export default function ReconcileTable({
  table,
  filasVisibles,
  sortState,
  toggleStockSort,
  hasCustomColumnSizing,
  handleResetColumnSizing,
  canBanlist,
  canPublish,
  onPublicar,
  onBanear,
  confirmingProductId,
  despublicando,
  onStartDespublicarConfirm,
  onCancelDespublicarConfirm,
  onConfirmDespublicar,
  showPaginator,
  page,
  totalPages,
  rangeStart,
  rangeEnd,
  total,
  onPrevPage,
  onNextPage,
}) {
  return (
    <>
      {hasCustomColumnSizing && (
        <div className={styles.columnSizingBar}>
          <button type="button" className="btn-tesla ghost sm" onClick={handleResetColumnSizing}>
            Restablecer columnas
          </button>
        </div>
      )}
      <div className="table-container-tesla">
        <table className={`table-tesla striped ${styles.resizableTable}`} style={{ width: table.getTotalSize() }}>
          <colgroup>
            {table.getVisibleLeafColumns().map((col) => (
              <col key={col.id} style={{ width: col.getSize() }} />
            ))}
          </colgroup>
          <thead className="table-tesla-head">
            <tr>
              {table.getFlatHeaders().map((h) => {
                // Driven by the column definition's own `sortable` flag,
                // not by a hardcoded id — otherwise the flag is dead
                // config and a future sortable column would silently do
                // nothing.
                const isStockColumn = Boolean(h.column.columnDef.sortable);
                const stockSortDirection = sortState?.column === 'stock' ? sortState.direction : null;
                return (
                <th
                  key={h.id}
                  aria-sort={
                    isStockColumn
                      ? stockSortDirection === 'asc'
                        ? 'ascending'
                        : stockSortDirection === 'desc'
                          ? 'descending'
                          : 'none'
                      : undefined
                  }
                >
                  {isStockColumn ? (
                    <button
                      type="button"
                      className={styles.sortableHeaderBtn}
                      aria-label="Ordenar por stock"
                      onClick={toggleStockSort}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {stockSortDirection === 'asc' ? ' ▲' : stockSortDirection === 'desc' ? ' ▼' : ''}
                    </button>
                  ) : (
                    flexRender(h.column.columnDef.header, h.getContext())
                  )}
                  {h.column.getCanResize() && (
                    <span
                      className={`${styles.resizeGrip} ${h.column.getIsResizing() ? styles.resizeGripActive : ''}`}
                      onMouseDown={h.getResizeHandler()}
                      onTouchStart={h.getResizeHandler()}
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={`Redimensionar columna ${h.column.columnDef.header}`}
                    />
                  )}
                </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {filasVisibles.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="no-data">
                  No hay filas para este veredicto
                </td>
              </tr>
            ) : (
              filasVisibles.map((row, idx) => (
                <tr key={`${row.ean}-${idx}`}>
                  {COLUMNS.map((col) =>
                    col.id === 'tn_presence' && row.verdict === 'FALTA_VINCULAR' &&
                    row.product_id != null && row.variant_id != null ? (
                      <td key={col.id}>
                        {col.cell(row)}
                        <div className={styles.matchedIds}>
                          TN product_id: {row.product_id} / variant_id: {row.variant_id}
                        </div>
                      </td>
                    ) : col.id === 'acciones' ? (
                      <td key={col.id}>
                        <RowActionsCell
                          row={row}
                          canBanlist={canBanlist}
                          canPublish={canPublish}
                          despublicarTargetProductId={despublicarTargetProductId}
                          onPublicar={onPublicar}
                          onBanear={onBanear}
                          confirmingProductId={confirmingProductId}
                          despublicando={despublicando}
                          onStartDespublicarConfirm={onStartDespublicarConfirm}
                          onCancelDespublicarConfirm={onCancelDespublicarConfirm}
                          onConfirmDespublicar={onConfirmDespublicar}
                        />
                      </td>
                    ) : (
                      <td key={col.id}>{col.cell(row)}</td>
                    )
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {showPaginator && (
        <Paginador
          page={page}
          totalPages={totalPages}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          total={total}
          onPrev={onPrevPage}
          onNext={onNextPage}
        />
      )}
    </>
  );
}
