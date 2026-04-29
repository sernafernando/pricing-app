/**
 * DataTable — Tabla unificada del módulo compras.
 *
 * Anchos de columna fijos vía <colgroup> + tabular-nums + alignment correcto.
 * Hover row con accent lateral animado en filas navegables.
 * Slots para empty/loading.
 *
 * @typedef {Object} ColumnDef
 * @property {string} key - identificador único
 * @property {string} label - texto del header
 * @property {'left'|'right'|'center'} [align='left']
 * @property {string} [width] - CSS width (ej. '92px', 'auto')
 *
 * @example
 * <DataTable
 *   columns={[
 *     { key: 'fecha', label: 'Fecha', width: '92px' },
 *     { key: 'monto', label: 'Monto', align: 'right', width: '156px' },
 *   ]}
 *   rows={pedidos}
 *   renderCell={(row, col) => col.key === 'monto' ? formatMoneda(row.monto) : row[col.key]}
 *   onRowClick={(row) => openDetail(row.id)}
 * />
 */

import EmptyState from './EmptyState';
import LoadingBlock from './LoadingBlock';
import styles from './DataTable.module.css';

/**
 * @param {Object} props
 * @param {ColumnDef[]} props.columns
 * @param {Array<{id: string|number}>} props.rows
 * @param {(row: object, column: ColumnDef) => React.ReactNode} props.renderCell
 * @param {boolean} [props.loading=false]
 * @param {{icon: React.ReactNode, title: string, subtitle?: string, cta?: object}} [props.empty]
 * @param {(row: object) => void} [props.onRowClick]
 * @param {(row: object) => boolean} [props.navegableRowFn]
 * @param {string} [props.minWidth='720px']
 */
export default function DataTable({
  columns,
  rows,
  renderCell,
  loading = false,
  empty,
  onRowClick,
  navegableRowFn,
  minWidth = '720px',
}) {
  if (loading) {
    return (
      <div className={styles.tableWrapper}>
        <LoadingBlock />
      </div>
    );
  }

  const isEmpty = !rows || rows.length === 0;

  return (
    <div className={styles.tableWrapper}>
      <table className={styles.table} style={{ minWidth }}>
        <colgroup>
          {columns.map((col) => (
            <col key={col.key} style={col.width ? { width: col.width } : undefined} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={
                  col.align === 'right'
                    ? styles.thRight
                    : col.align === 'center'
                      ? styles.thCenter
                      : styles.thLeft
                }
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {isEmpty ? (
            <tr>
              <td colSpan={columns.length} className={styles.emptyRow}>
                {empty ? (
                  <EmptyState
                    icon={empty.icon}
                    title={empty.title}
                    subtitle={empty.subtitle}
                    cta={empty.cta}
                    tone="inline"
                  />
                ) : (
                  <span className={styles.emptyFallback}>Sin datos.</span>
                )}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const navegable = onRowClick && (!navegableRowFn || navegableRowFn(row));
              return (
                <tr
                  key={row.id}
                  className={navegable ? styles.rowClickable : undefined}
                  onClick={navegable ? () => onRowClick(row) : undefined}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={
                        col.align === 'right'
                          ? styles.tdRight
                          : col.align === 'center'
                            ? styles.tdCenter
                            : undefined
                      }
                    >
                      {renderCell(row, col)}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
