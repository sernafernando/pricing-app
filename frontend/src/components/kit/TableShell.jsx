/**
 * TableShell — a table that owns a bounded scroller on BOTH axes
 * (publicaciones-ml-vista P10b, design 8.2).
 *
 * Why its own scroller: #1419 showed that a horizontal scroll container makes
 * a `position: sticky` `<th>` pin to that container instead of the viewport,
 * so a TopBar-offset header slid down over the first row. Here the scroller is
 * ALWAYS the sticky context (it has a `max-height`), so the header is
 * `top: 0` and the first column is `left: 0` at every width -- nothing depends
 * on the TopBar offset and the panel can shrink the table freely.
 *
 * Generic on purpose: it knows nothing about publications. A page passes
 * `columns` (`render(row)` per cell) and `rows`; trees and variations come
 * through `getRowDepth` (sets `--indent`) and `renderSubRows` (extra `<tr>`
 * after a row, e.g. variation sub-rows).
 *
 * Column fields: `key`, `header`, `width` (number = px, string verbatim; goes
 * to `<colgroup>`), `sortable`, `group` (consecutive equal groups share one
 * spanning header cell above the leaf row), `align`, `render(row)`.
 * The first column is pinned.
 */
import { Fragment } from 'react';
import styles from './TableShell.module.css';

const toCssWidth = (width) => (typeof width === 'number' ? `${width}px` : width);

const ARIA_SORT = { asc: 'ascending', desc: 'descending' };

/** Consecutive columns with the same `group` collapse into one spanning cell. */
function buildGroups(columns) {
  const groups = [];
  for (const column of columns) {
    const last = groups[groups.length - 1];
    if (last && column.group && last.label === column.group) last.span += 1;
    else groups.push({ label: column.group ?? '', span: 1, key: `${groups.length}:${column.key}` });
  }
  return groups;
}

/**
 * @param {object} props
 * @param {Array<object>} props.columns
 * @param {Array<object>} props.rows
 * @param {(row: object) => string|number} props.getRowKey
 * @param {{key: string, dir: 'asc'|'desc'}} [props.sort]
 * @param {(key: string) => void} [props.onSort]
 * @param {(row: object) => number} [props.getRowDepth] Tree depth, default 0.
 * @param {(row: object) => import('react').ReactNode} [props.renderSubRows]
 * @param {(row: object) => void} [props.onRowClick]
 * @param {string|number} [props.selectedKey]
 * @param {string} [props.offset] CSS length reserved around the table.
 * @param {string} [props.emptyMessage]
 * @param {string} [props.ariaLabel]
 */
export default function TableShell({
  columns,
  rows,
  getRowKey,
  sort,
  onSort,
  getRowDepth,
  renderSubRows,
  onRowClick,
  selectedKey,
  offset,
  emptyMessage = 'Sin resultados',
  ariaLabel,
}) {
  const hasGroups = columns.some((column) => column.group);
  const scrollerStyle = offset ? { '--table-shell-offset': offset } : undefined;

  return (
    <div className={styles.scroller} style={scrollerStyle} data-table-shell-scroller>
      <table className={styles.table} aria-label={ariaLabel}>
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={column.width ? { width: toCssWidth(column.width) } : undefined} />
          ))}
        </colgroup>
        <thead>
          {hasGroups && (
            <tr className={styles.groupRow}>
              {buildGroups(columns).map((group) => (
                <th key={group.key} colSpan={group.span} className={styles.groupCell} scope="colgroup">
                  {group.label}
                </th>
              ))}
            </tr>
          )}
          <tr className={hasGroups ? styles.leafRowGrouped : undefined}>
            {columns.map((column, index) => {
              const active = sort?.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={styles.headCell}
                  data-pinned={index === 0 ? '' : undefined}
                  data-align={column.align}
                  aria-sort={active ? ARIA_SORT[sort.dir] : undefined}
                >
                  {column.sortable ? (
                    <button type="button" className={styles.sortButton} onClick={() => onSort?.(column.key)}>
                      {column.header}
                      {active && (
                        <span aria-hidden="true" className={styles.sortMark}>
                          {sort.dir === 'asc' ? '▲' : '▼'}
                        </span>
                      )}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className={styles.empty}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const key = getRowKey(row);
              const selected = selectedKey !== undefined && selectedKey === key;
              return (
                <Fragment key={key}>
                  <tr
                    className={styles.row}
                    style={{ '--indent': getRowDepth?.(row) ?? 0 }}
                    aria-selected={selected || undefined}
                    data-clickable={onRowClick ? '' : undefined}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {columns.map((column, index) => (
                      <td
                        key={column.key}
                        className={styles.cell}
                        data-pinned={index === 0 ? '' : undefined}
                        data-align={column.align}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                  {renderSubRows?.(row)}
                </Fragment>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
