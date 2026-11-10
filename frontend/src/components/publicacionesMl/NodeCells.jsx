import { ChevronDown, ChevronRight } from 'lucide-react';
import MarkupCell from './MarkupCell';
import { describeTreeError } from './groupTree';
import { LEVEL_LABELS } from '../../utils/metricasMlLevels';
import { formatAmount } from '../../utils/ventasMlFormat';
import { KINDS, listingKindLabel } from './listingKindLabels';
import { publicationStatusInfo } from './publicationStatus';
import styles from './NodeCells.module.css';
import cellStyles from './cells.module.css';

// The group levels are Métricas ML's (`marca`, `categoria`, `subcategoria`, `subcategoria_categoria`, `tienda`, `pm`),
// named as Métricas names them; the levels below them are the tree's own.
const KIND_LABELS = {
  ...LEVEL_LABELS,
  producto: 'Producto',
  familia: 'Familia',
  item: 'Publicación',
};

const formatCount = (count) => count.toLocaleString('es-AR');

const publications = (count) => `${formatCount(count)} ${count === 1 ? 'publicación' : 'publicaciones'}`;

/** The second line's count: "N publicaciones", and " · M con markup negativo" when some sell under cost (the
 * negatives come only with ver_ganancia, and never on the Producto view). */
function NodeCountLine({ node }) {
  const negatives = node.negativeCount ?? 0;
  return (
    <>
      {publications(node.count ?? 0)}
      {negatives > 0 && (
        <>
          {' · '}
          <span className={cellStyles.negativeNote}>{formatCount(negatives)} con markup negativo</span>
        </>
      )}
    </>
  );
}

/** Pinned cell of a node: open/close toggle, name, what kind of node it is, and its code. `badges` sit beside the name. */
export function NodeTitle({ row, onToggle, after = null, badges = null }) {
  const { node, expanded } = row;
  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <div className={styles.node}>
      <button
        type="button"
        className={cellStyles.toggle}
        aria-expanded={expanded}
        aria-label={`${expanded ? 'Cerrar' : 'Abrir'} ${node.label}`}
        onClick={() => onToggle(row)}
      >
        <Icon size={14} aria-hidden="true" />
      </button>
      {after}
      <div className={styles.nodeText}>
        {/* The badges are the name's siblings: "Filas finas" cuts only the name (whole in its tooltip), never them. */}
        <span className={styles.nameLine}>
          <span
            className={styles.nodeLabel}
            title={node.label}
            data-muted={node.withoutProduct || node.key === '__none__' ? '' : undefined}
          >
            {node.label}
          </span>
          {badges}
        </span>
        <span className={cellStyles.note}>
          {KIND_LABELS[node.kind] ?? node.kind}
          {node.codigo ? ` · ${node.codigo}` : ''}
          {' · '}
          <NodeCountLine node={node} />
        </span>
      </div>
    </div>
  );
}

/** Pinned cell of the rows that are not nodes or publications: loading, error, empty, "Ver más". */
export function BranchState({ row, onMore, onRetry }) {
  if (row.type === 'more') {
    return (
      <button type="button" className="btn-tesla outline sm" disabled={row.loading} onClick={() => onMore(row.pathKey)}>
        {row.loading ? 'Cargando…' : `Ver más (${formatCount(row.remaining)})`}
      </button>
    );
  }
  if (row.state === 'loading') return <span role="status" className={cellStyles.note}>Cargando…</span>;
  if (row.state === 'error') {
    return (
      <div className={styles.state}>
        <span role="alert">{describeTreeError(row.error)}</span>
        <button type="button" className="btn-tesla outline sm" onClick={() => onRetry(row.pathKey)}>
          Reintentar
        </button>
      </div>
    );
  }
  return <span className={cellStyles.note}>Sin publicaciones con los filtros actuales</span>;
}

// S6: a parent row's Tipo, Estado and Precio summarize ALL its publications under the filters (the backend's
// `kind_counts`, `status_counts`, `price_min`/`price_max`), never the children loaded so far.

// The list's order of the kinds (Clásica, then 3, 6, 9 and 12 cuotas); ML's other types after them.
const KIND_ORDER = Object.keys(KINDS);
const kindRank = (kind) => (KIND_ORDER.includes(kind) ? KIND_ORDER.indexOf(kind) : KIND_ORDER.length);

// The states in the order a reader scans them; any other after them.
const STATUS_ORDER = ['active', 'paused', 'under_review', 'inactive', 'closed', 'gone'];
const statusRank = (status) => (STATUS_ORDER.includes(status) ? STATUS_ORDER.indexOf(status) : STATUS_ORDER.length);
// The plural of each state's label (`publicationStatusInfo`), lowercase; a state missing here reads its label.
const STATUS_PLURALS = { active: 'activas', paused: 'pausadas', inactive: 'inactivas', closed: 'cerradas', gone: 'eliminadas' };
const NO_STATUS = 'sin_estado';

function statusWord(status, count) {
  if (status === NO_STATUS) return 'sin estado';
  if (count !== 1 && STATUS_PLURALS[status]) return STATUS_PLURALS[status];
  return (publicationStatusInfo(status)?.label ?? status).toLowerCase();
}

function SummaryLines({ lines }) {
  if (lines.length === 0) return <span className={cellStyles.empty}>—</span>;
  return (
    <div className={cellStyles.stack}>
      {lines.map((line) => (
        <span key={line} className={cellStyles.summaryLine} data-summary-line="">
          {line}
        </span>
      ))}
    </div>
  );
}

/** Tipo of a parent row: one line per kind, count first ("2 Clásica", "1 6 cuotas"). Kinds that read the same (a
 * co-funded Clásica) share one line. */
export function NodeKinds({ node }) {
  const byLabel = new Map();
  const kinds = Object.entries(node.kindCounts ?? {}).sort(([a], [b]) => kindRank(a) - kindRank(b) || a.localeCompare(b));
  for (const [kind, count] of kinds) {
    const label = listingKindLabel(kind);
    byLabel.set(label, (byLabel.get(label) ?? 0) + count);
  }
  return <SummaryLines lines={[...byLabel].map(([label, count]) => `${formatCount(count)} ${label}`)} />;
}

/** Estado of a parent row: one line per state ("4 activas", "1 pausada"). */
export function NodeStatuses({ node }) {
  const states = Object.entries(node.statusCounts ?? {}).sort(([a], [b]) => statusRank(a) - statusRank(b) || a.localeCompare(b));
  return <SummaryLines lines={states.map(([status, count]) => `${formatCount(count)} ${statusWord(status, count)}`)} />;
}

/** Precio of a parent row: the range of the prices the list shows, one figure when they are all the same. */
export function NodePrice({ node }) {
  const { priceMin: min, priceMax: max } = node;
  if (min == null || max == null) return <span className={cellStyles.empty}>—</span>;
  if (min === max) return <span className={cellStyles.amount}>{formatAmount(min)}</span>;
  return (
    <div className={`${cellStyles.stack} ${cellStyles.stackEnd}`}>
      <span className={cellStyles.amount}>{formatAmount(min)} –</span>
      <span className={cellStyles.amount}>{formatAmount(max)}</span>
    </div>
  );
}

/** A parent row's Tipo, Estado or Precio cell (`column` is the column's key): the summary of ALL its publications. */
export function NodeSummary({ column, node }) {
  if (column === 'tipo') return <NodeKinds node={node} />;
  if (column === 'estado') return <NodeStatuses node={node} />;
  if (column === 'precio') return <NodePrice node={node} />;
  return null;
}

/** Markup range of the node's variations: the list's cell, so a null range reads the same ("—"). */
export function NodeMarkup({ node }) {
  if (node.markup == null) return <MarkupCell markup={null} />;
  return <MarkupCell markup={{ ...node.markup, any_negative: (node.negativeCount ?? 0) > 0, partial: 0 }} />;
}
