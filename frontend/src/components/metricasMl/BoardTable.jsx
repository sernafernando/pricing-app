import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, CornerDownRight, Layers, Package } from 'lucide-react';
import Sparkline from './Sparkline';
import { formatSignedMoney, markupTone, moneyTone } from '../../utils/ventasMlTone';
import {
  ageingTone,
  deltaTone,
  formatAgeing,
  formatDeltaPp,
  formatLastSale,
  formatPct,
  formatUnits,
  publicationDescriptor,
  weeklySums,
} from '../../utils/metricasMlFormat';
import { COLUMN_GROUPS } from './metricasMlColumns';
import { LEVEL_LABELS, LEVEL_NOUNS, nodeId } from '../../utils/metricasMlLevels';
import styles from './BoardTable.module.css';

/**
 * The Métricas ML "watchlist" table (tablero.png): grouped headers, one row
 * per product (or publication), expandable publication sub-rows, inline
 * sparklines. Purely presentational: the page owns the data, the expanded
 * set and the sort; this renders the columns the page says are visible
 * (`columns`, from the TanStack visibility state the ColumnPicker drives).
 *
 * Layout promises (pinned by the visual suite): the table scrolls sideways
 * INSIDE its card, the Producto column stays pinned to the left while it
 * does, and money never wraps.
 */


// How far each level of the "Agrupado" tree steps in under its parent.
const INDENT_PX = 18;

// Column id -> the backend `sort` value it orders by.
const SORT_BY = {
  producto: 'title',
  units_24h: 'units_24h',
  units_3d: 'units_3d',
  units_7d: 'units_7d',
  units_15d: 'units_15d',
  units_30d: 'units_30d',
  markup: 'markup',
  markup_delta: 'markup_delta',
  gross: 'gross',
  total_gauss: 'total_gauss',
  last_sale: 'last_sale',
  ageing: 'ageing',
  stock: 'stock',
};

/** The row's ERP stock: "—" ONLY when unknown; a known 0 reads "0" and a
 * negative stock (oversold in the ERP) its number in the danger tone, so
 * neither can pass for "Sin dato". */
function StockCell({ value }) {
  const known = value !== null && value !== undefined;
  const kind = !known ? 'unknown' : value < 0 ? 'negative' : value === 0 ? 'zero' : 'positive';
  const tone = kind === 'negative' ? styles.tone_negative : kind === 'unknown' ? styles.muted : '';
  return (
    <span className={`${styles.units} ${tone}`} data-stock={kind}>
      {known ? formatUnits(value) : '—'}
    </span>
  );
}

function UnitsCell({ value, strong }) {
  return (
    <span className={`${styles.units} ${strong ? styles.strong : ''} ${value ? '' : styles.muted}`}>
      {formatUnits(value)}
    </span>
  );
}

function DeltaBadge({ value, compact }) {
  const tone = deltaTone(value);
  if (!tone) return <span className={styles.muted}>—</span>;
  return (
    <span className={compact ? styles.deltaText : styles.delta} data-tone={tone}>
      {formatDeltaPp(value)}
    </span>
  );
}

function ProductBadges({ row, canSeeMargin }) {
  const badges = [];
  if (canSeeMargin && row.markup_pct !== null && row.markup_pct < 0) badges.push('PÉRDIDA');
  if (row.alerts.includes('sin_ventas_30d') && row.alerts.includes('ageing_60d')) badges.push('INMOVILIZADO');
  return badges.map((badge) => (
    <span key={badge} className={styles.dangerBadge}>
      {badge}
    </span>
  ));
}

/** "12 productos · 31 publicaciones": what a group row sums. */
function groupCounts(row) {
  const products = row.products_count ?? 0;
  const pubs = row.publications_count ?? 0;
  return `${products === 1 ? '1 producto' : `${products} productos`} · ${pubs === 1 ? '1 publicación' : `${pubs} publicaciones`}`;
}

/** How far a row sits under its parent: the CSS indents by `--indent`. */
function indentStyle(depth) {
  return { '--indent': `${depth * INDENT_PX}px` };
}

/** A node of the "Agrupado" tree: what it opens into (`child_level`), its level's tag
 * and, at the top, the stack icon; deeper nodes drop the icon to leave the room to
 * the indentation. */
function GroupCell({ row, depth, expanded, onToggle }) {
  const opensInto = LEVEL_NOUNS[row.child_level]?.all ?? 'los productos';
  return (
    <div className={styles.product} style={indentStyle(depth)} data-node-level={row.level}>
      <button
        type="button"
        className={styles.expand}
        aria-expanded={expanded}
        aria-label={`${expanded ? 'Ocultar' : 'Ver'} ${opensInto} de ${row.title}`}
        onClick={onToggle}
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {depth === 0 && (
        <span className={styles.thumb} aria-hidden="true">
          <Layers size={18} />
        </span>
      )}
      <div className={styles.productText}>
        <div className={styles.titleLine}>
          {row.level && <span className={styles.levelTag}>{LEVEL_LABELS[row.level] ?? row.level}</span>}
          <span className={styles.title} title={row.title}>
            {row.title}
          </span>
        </div>
        <div className={styles.meta}>
          <span>{groupCounts(row)}</span>
        </div>
      </div>
    </div>
  );
}

function Thumb({ row }) {
  if (row.thumbnail) return <img className={styles.thumb} src={row.thumbnail} alt="" loading="lazy" />;
  return (
    <span className={styles.thumb} aria-hidden="true">
      <Package size={18} />
    </span>
  );
}

function ProductCell({ row, groupBy, canSeeMargin, isSub, depth, expanded, onToggle }) {
  if (groupBy === 'group' && row.child_level) {
    return <GroupCell row={row} depth={depth} expanded={expanded} onToggle={onToggle} />;
  }
  if (groupBy === 'group') {
    // The last level of the tree is PRODUCTS: sku and brand over the title.
    return (
      <div className={styles.subProduct} style={indentStyle(depth)}>
        <div className={styles.subLine}>
          <CornerDownRight size={12} className={styles.subArrow} aria-hidden="true" />
          {row.sku && <span className={styles.sku}>{row.sku}</span>}
          {row.marca && (
            <>
              <span className={styles.dotSep}>·</span>
              <span className={styles.descriptor}>{row.marca}</span>
            </>
          )}
        </div>
        <div className={styles.subTitle} title={row.title}>
          {row.title}
        </div>
      </div>
    );
  }
  if (isSub) {
    return (
      <div className={styles.subProduct}>
        <div className={styles.subLine}>
          <CornerDownRight size={12} className={styles.subArrow} aria-hidden="true" />
          <span className={styles.mla}>{row.mla}</span>
          {row.is_best && <span className={styles.bestBadge}>Mejor</span>}
          <span className={styles.dotSep}>·</span>
          <span className={styles.descriptor}>{publicationDescriptor(row)}</span>
        </div>
        <div className={styles.subTitle} title={row.title}>
          {row.title}
        </div>
      </div>
    );
  }
  const isProduct = groupBy === 'product';
  return (
    <div className={styles.product}>
      {isProduct && (
        <button
          type="button"
          className={styles.expand}
          aria-expanded={expanded}
          aria-label={`${expanded ? 'Ocultar' : 'Ver'} publicaciones de ${row.title}`}
          onClick={onToggle}
        >
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
      )}
      <Thumb row={row} />
      <div className={styles.productText}>
        <div className={styles.titleLine}>
          <span className={styles.title} title={row.title}>
            {isProduct ? row.title : row.mla}
          </span>
          <ProductBadges row={row} canSeeMargin={canSeeMargin} />
        </div>
        <div className={styles.meta}>
          {isProduct ? (
            <>
              {row.sku && <span className={styles.sku}>{row.sku}</span>}
              {row.marca && (
                <>
                  <span className={styles.dotSep}>·</span>
                  <span>{row.marca}</span>
                </>
              )}
              <span className={styles.dotSep}>·</span>
              <span className={row.publications_count > 1 ? styles.pubsPill : ''}>
                {row.publications_count === 1 ? '1 publicación' : `${row.publications_count} publicaciones`}
              </span>
            </>
          ) : (
            <>
              <span className={styles.descriptor}>{publicationDescriptor(row)}</span>
              <span className={styles.dotSep}>·</span>
              <span className={styles.metaTitle} title={row.title}>
                {row.title}
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function renderCell(colId, row, ctx) {
  const { isSub } = ctx;
  switch (colId) {
    case 'producto':
      return <ProductCell row={row} {...ctx} />;
    case 'units_24h':
    case 'units_3d':
    case 'units_7d':
    case 'units_15d':
      return <UnitsCell value={row[colId]} />;
    case 'units_30d':
      return <UnitsCell value={row.units_30d} strong />;
    case 'units_trend': {
      const weeks = weeklySums(row.series_units_90d);
      const tone = weeks.length > 1 ? deltaTone(weeks.at(-1) - weeks.at(-2)) : null;
      return (
        <Sparkline values={weeks} width={isSub ? 80 : 96} height={isSub ? 22 : 28} tone={tone} label="Unidades por semana, 90 días" />
      );
    }
    case 'markup': {
      const tone = markupTone(row.markup_pct);
      return <span className={`${styles.markup} ${tone ? styles[`tone_${tone}`] : styles.muted}`}>{formatPct(row.markup_pct)}</span>;
    }
    case 'markup_delta':
      return <DeltaBadge value={row.markup_delta_pp} compact={isSub} />;
    case 'markup_trend':
      return (
        <Sparkline
          values={row.series_markup_90d || []}
          width={isSub ? 100 : 120}
          height={isSub ? 24 : 32}
          tone={deltaTone(row.markup_delta_pp)}
          label="Markup diario, 90 días"
        />
      );
    case 'markup_range':
      return (
        <span className={styles.range}>
          {row.markup_min_90d === null ? '—' : `${formatPct(row.markup_min_90d)} / ${formatPct(row.markup_max_90d)}`}
        </span>
      );
    case 'gross':
      return (
        <span className={styles.money} data-money>
          {formatSignedMoney(row.gross)}
        </span>
      );
    case 'total_gauss': {
      const tone = moneyTone(row.total_gauss);
      const mTone = markupTone(row.markup_pct);
      return (
        <div className={styles.gaussCell}>
          <span className={`${styles.money} ${styles.moneyStrong} ${styles[`money_${tone}`] || ''}`} data-money>
            {formatSignedMoney(row.total_gauss)}
          </span>
          {!isSub && row.markup_pct !== null && (
            <span className={`${styles.markupChip} ${mTone ? styles[`chip_${mTone}`] : ''}`}>
              {row.markup_pct > 0 ? '+' : ''}
              {formatPct(row.markup_pct)} markup
            </span>
          )}
        </div>
      );
    }
    case 'last_sale': {
      const { when, ago } = formatLastSale(row.last_sale_at, ctx.now);
      return (
        <div className={styles.lastSale}>
          <span className={styles.when}>{when}</span>
          {!isSub && <span className={styles.ago}>{ago}</span>}
        </div>
      );
    }
    case 'ageing': {
      const tone = ageingTone(row.ageing_days);
      return (
        <span className={`${styles.ageing} ${tone ? styles[`chip_${tone}`] : ''}`}>{formatAgeing(row.ageing_days)}</span>
      );
    }
    case 'stock':
      // `productos_erp.stock` of the row's product; "—" when the ERP has none.
      return <StockCell value={row.stock} />;
    default:
      // Sell-in / sell-out: announced, never invented.
      return <span className={styles.placeholder}>—</span>;
  }
}

const NUMERIC = new Set([
  'units_24h',
  'units_3d',
  'units_7d',
  'units_15d',
  'units_30d',
  'markup',
  'gross',
  'total_gauss',
]);
const CENTERED = new Set(['units_trend', 'markup_delta', 'markup_trend', 'markup_range', 'ageing', 'stock', 'compras_30d', 'sell_through', 'cobertura']);

function cellClass(colId, groupStart, groupEnd) {
  return [
    colId === 'producto' ? styles.colProducto : '',
    NUMERIC.has(colId) ? styles.numeric : '',
    CENTERED.has(colId) ? styles.centered : '',
    groupStart ? styles.groupStart : '',
    groupEnd ? styles.groupEnd : '',
  ]
    .filter(Boolean)
    .join(' ');
}

export default function BoardTable({
  rows,
  columns,
  groupBy,
  canSeeMargin,
  expanded,
  subRows,
  onToggleExpand,
  sort,
  sortDesc,
  onSort,
  now,
}) {
  const groups = COLUMN_GROUPS.map((group) => ({
    ...group,
    columns: columns.filter((col) => col.group === group.id),
  })).filter((group) => group.columns.length > 0);
  const edges = new Map();
  for (const group of groups) {
    edges.set(group.columns[0].id, { ...(edges.get(group.columns[0].id) || {}), start: true, soon: group.soon });
    const lastId = group.columns.at(-1).id;
    edges.set(lastId, { ...(edges.get(lastId) || {}), end: true, soon: group.soon });
  }
  const ctxBase = { groupBy, canSeeMargin, now };
  const colClass = (col) => {
    const edge = edges.get(col.id) || {};
    return `${cellClass(col.id, edge.start, edge.end)} ${col.group === 'sellin' ? styles.soonCol : ''}`;
  };

  // `depth` 0 is a board row; deeper rows are what an open row opened into.
  // `id` is the row's node id (the keys down to it): the same key under two
  // parents is two rows, so it -- not the key -- names a row and its state.
  const renderRow = (row, { depth = 0, id = nodeId([row.key]) } = {}) => {
    const isSub = depth > 0;
    return (
      <tr
        key={isSub ? `sub-${id}` : row.key}
        data-depth={depth}
        className={isSub ? `${styles.subRow} ${expanded.has(id) ? styles.openRow : ''}` : expanded.has(id) ? styles.openRow : ''}
      >
        {columns.map((col) => (
          <td key={col.id} className={colClass(col)} data-col-id={col.id}>
            {renderCell(col.id, row, {
              ...ctxBase,
              isSub,
              depth,
              expanded: expanded.has(id),
              onToggle: () => onToggleExpand(row, { path: JSON.parse(id) }),
            })}
          </td>
        ))}
      </tr>
    );
  };

  const note = (key, id, text, extra) => (
    <tr key={`${key}-${id}`} className={styles.subRow} data-note={key}>
      <td className={styles.colProducto}>
        <span className={styles.subNote}>{text}</span>
        {extra}
      </td>
      <td colSpan={columns.length - 1} />
    </tr>
  );

  // A row and, when it is open, everything it opened into -- recursively for
  // the nodes of the "Agrupado" tree, each level with its own state and notes.
  const renderTree = (row, path, depth) => {
    const id = nodeId(path);
    const out = [renderRow(row, { depth, id })];
    const opensRows = groupBy === 'group' ? Boolean(row.child_level) : groupBy === 'product';
    if (!opensRows || !expanded.has(id)) return out;
    const state = subRows[id];
    const loaded = state?.rows || [];
    for (const sub of loaded) {
      out.push(...renderTree(sub, [...path, sub.key], depth + 1));
    }
    const isGroup = groupBy === 'group';
    const level = state?.level ?? row.child_level;
    const nouns = LEVEL_NOUNS[level] ?? LEVEL_NOUNS.product;
    const loadMore = (
      <button type="button" className={styles.moreButton} onClick={() => onToggleExpand(row, { more: true, path })}>
        {state?.error ? 'Reintentar' : `Ver más ${nouns.plural}`}
      </button>
    );
    if (!state || state.loading) {
      out.push(note('loading', id, `Cargando ${isGroup ? nouns.plural : 'publicaciones'}…`));
    } else if (state.error) {
      const failure = isGroup ? nouns.all : 'las publicaciones';
      // A page that failed after others loaded: retry just that page.
      out.push(note('error', id, `No se pudieron cargar ${failure}.`, isGroup && loaded.length > 0 ? loadMore : null));
    } else if (isGroup && state.total > loaded.length) {
      out.push(note('more', id, `Mostrando ${loaded.length} de ${state.total} ${nouns.plural}`, loadMore));
    } else if (isGroup && loaded.length === 0) {
      out.push(note('empty', id, `No hay ${nouns.plural} para estos filtros.`));
    }
    return out;
  };

  return (
    <table className={styles.table}>
      <thead>
        <tr className={styles.groupRow}>
          {groups.map((group) => (
            <th
              key={group.id}
              scope="colgroup"
              colSpan={group.columns.length}
              className={`${group.id === 'producto' ? styles.colProducto : styles.groupHead} ${group.soon ? styles.soonHead : ''}`}
            >
              {group.label}
              {group.soon && <span className={styles.soonBadge}>Próximamente</span>}
            </th>
          ))}
        </tr>
        <tr className={styles.leafRow}>
          {columns.map((col) => {
            const sortKey = SORT_BY[col.id];
            const active = sortKey && sortKey === sort;
            return (
              <th
                key={col.id}
                scope="col"
                className={colClass(col)}
                aria-sort={active ? (sortDesc ? 'descending' : 'ascending') : undefined}
              >
                {sortKey ? (
                  <button type="button" className={styles.sortButton} onClick={() => onSort(sortKey)}>
                    {col.header}
                    {active &&
                      (sortDesc ? (
                        <ArrowDown size={11} className={styles.sortArrow} aria-hidden="true" />
                      ) : (
                        <ArrowUp size={11} className={styles.sortArrow} aria-hidden="true" />
                      ))}
                  </button>
                ) : (
                  col.header
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.flatMap((row) => renderTree(row, [row.key], 0))}
      </tbody>
    </table>
  );
}
