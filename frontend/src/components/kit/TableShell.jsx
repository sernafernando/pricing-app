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
 *
 * Grouped, it reads like Métricas ML's board: a labelled group spans its
 * columns, a column of no group spans both header rows, and the first column
 * of each group (`data-group-start`, header and body) carries the divider.
 * Every header and body cell names its column (`data-column`).
 */
import { Fragment } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import styles from './TableShell.module.css';

const toCssWidth = (width) => (typeof width === 'number' ? `${width}px` : width);

const ARIA_SORT = { asc: 'ascending', desc: 'descending' };

/**
 * Enter/Space on the ROW itself opens it. Keys typed inside a control the row
 * hosts (input, button, link) belong to that control, so only events whose
 * target is the row are handled.
 */
function activateOnKey(event, row, onRowClick) {
  if (event.target !== event.currentTarget) return;
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  onRowClick(row, event);
}

const INTERACTIVE = 'button, a, input, select, textarea, label, [role="button"]';

/** A click on a control hosted in a cell belongs to that control, not the row. */
function activateOnClick(event, row, onRowClick) {
  if (event.target.closest?.(INTERACTIVE)) return;
  onRowClick(row, event);
}

/** Consecutive columns with the same `group` collapse into one spanning cell; a column of no group stands alone. */
function buildGroups(columns) {
  const groups = [];
  columns.forEach((column, index) => {
    const last = groups[groups.length - 1];
    if (last && column.group && last.label === column.group) last.span += 1;
    else groups.push({ label: column.group ?? '', span: 1, key: `${groups.length}:${column.key}`, column, index });
  });
  return groups;
}

/** Whether `columns[index]` opens a group: a divider between groups, never between two columns of none. */
function startsGroup(columns, index) {
  if (index === 0) return false;
  const { group } = columns[index];
  const previous = columns[index - 1].group;
  return Boolean(group || previous) && group !== previous;
}

function HeadCell({ column, index, sort, onSort, groupStart, rowSpan, className }) {
  const active = sort?.key === column.key;
  return (
    <th
      scope="col"
      rowSpan={rowSpan}
      className={className}
      data-column={column.key}
      data-pinned={index === 0 ? '' : undefined}
      data-align={column.align}
      data-group-start={groupStart ? '' : undefined}
      aria-sort={active ? ARIA_SORT[sort.dir] : undefined}
    >
      {column.headerControl}
      {column.sortable ? (
        <button type="button" className={styles.sortButton} onClick={() => onSort?.(column.key)}>
          {column.header}
          {active && (
            <span aria-hidden="true" className={styles.sortMark}>
              {sort.dir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </span>
          )}
        </button>
      ) : (
        column.header
      )}
    </th>
  );
}

/**
 * @param {object} props
 * @param {Array<object>} props.columns `headerControl` (optional) is a control placed in the header cell before the
 *   column's title, outside its sort button (e.g. a select-all checkbox).
 * @param {Array<object>} props.rows
 * @param {(row: object) => string|number} props.getRowKey
 * @param {{key: string, dir: 'asc'|'desc'}} [props.sort]
 * @param {(key: string) => void} [props.onSort]
 * @param {(row: object) => number} [props.getRowDepth] Tree depth, default 0.
 * @param {(row: object) => ({background?: string, text?: string, marker?: string, label?: string} | null)} [props.getRowTone]
 *   A row's color: `background`/`text` paint it, `marker` only edges its first cell; `label` names it (tooltip).
 * @param {(row: object) => import('react').ReactNode} [props.renderSubRows]
 * @param {(row: object, event: import('react').SyntheticEvent) => void} [props.onRowClick] The event lets a page
 *   tell a plain click from Ctrl/Cmd+click.
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
  getRowTone,
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
          {hasGroups ? (
            <>
              <tr className={styles.groupRow}>
                {buildGroups(columns).map((group) =>
                  group.label ? (
                    <th
                      key={group.key}
                      colSpan={group.span}
                      className={styles.groupCell}
                      scope="colgroup"
                      data-group-start={startsGroup(columns, group.index) ? '' : undefined}
                    >
                      {group.label}
                    </th>
                  ) : (
                    <HeadCell
                      key={group.key}
                      column={group.column}
                      index={group.index}
                      sort={sort}
                      onSort={onSort}
                      groupStart={startsGroup(columns, group.index)}
                      rowSpan={2}
                      className={`${styles.headCell} ${styles.headCellSpanning}`}
                    />
                  ),
                )}
              </tr>
              <tr className={styles.leafRowGrouped}>
                {columns.map((column, index) =>
                  column.group ? (
                    <HeadCell
                      key={column.key}
                      column={column}
                      index={index}
                      sort={sort}
                      onSort={onSort}
                      groupStart={startsGroup(columns, index)}
                      className={styles.headCell}
                    />
                  ) : null,
                )}
              </tr>
            </>
          ) : (
            <tr>
              {columns.map((column, index) => (
                <HeadCell key={column.key} column={column} index={index} sort={sort} onSort={onSort} className={styles.headCell} />
              ))}
            </tr>
          )}
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
              const tone = getRowTone?.(row) ?? null;
              return (
                <Fragment key={key}>
                  <tr
                    className={styles.row}
                    style={{
                      '--indent': getRowDepth?.(row) ?? 0,
                      ...(tone?.background && { '--row-tone-bg': tone.background, '--row-tone-fg': tone.text }),
                      ...(tone?.marker && { '--row-marker': tone.marker }),
                    }}
                    data-tone={tone?.background ? '' : undefined}
                    data-marker={tone?.marker ? '' : undefined}
                    title={tone?.label}
                    aria-current={selected || undefined}
                    data-selected={selected ? '' : undefined}
                    data-clickable={onRowClick ? '' : undefined}
                    data-row-key={key}
                    tabIndex={onRowClick ? 0 : undefined}
                    onClick={onRowClick ? (e) => activateOnClick(e, row, onRowClick) : undefined}
                    onKeyDown={onRowClick ? (e) => activateOnKey(e, row, onRowClick) : undefined}
                  >
                    {columns.map((column, index) => (
                      <td
                        key={column.key}
                        className={styles.cell}
                        data-pinned={index === 0 ? '' : undefined}
                        data-align={column.align}
                        data-group-start={hasGroups && startsGroup(columns, index) ? '' : undefined}
                        data-column={column.key}
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
