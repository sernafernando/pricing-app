import { ChevronDown, ChevronRight } from 'lucide-react';
import MarkupCell from './MarkupCell';
import { describeTreeError } from './groupTree';
import { LEVEL_LABELS } from '../../utils/metricasMlLevels';
import { formatAmount } from '../../utils/ventasMlFormat';
import { KINDS, listingKindLabel, listingKindShort } from './listingKindLabels';
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

/** The second line in words, for its tooltip ("Filas finas" cuts it to one line). */
function noteText(node) {
  const negatives = node.negativeCount ?? 0;
  const kind = KIND_LABELS[node.kind] ?? node.kind;
  const code = node.codigo ? ` · ${node.codigo}` : '';
  const cut = negatives > 0 ? ` · ${formatCount(negatives)} con markup negativo` : '';
  return `${kind}${code} · ${publications(node.count ?? 0)}${cut}`;
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
        <span className={`${cellStyles.note} ${styles.nodeNote}`} title={noteText(node)} data-node-note="">
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
// The dot's colour of each state: green active, amber waiting on someone (paused, under review), grey not selling
// (inactive, closed), red gone from ML. Any other state is grey.
const STATUS_TONES = { active: 'success', paused: 'warning', under_review: 'warning', inactive: 'neutral', closed: 'neutral', gone: 'danger' };
const NO_STATUS = 'sin_estado';

function statusWord(status, count) {
  if (status === NO_STATUS) return 'sin estado';
  if (count !== 1 && STATUS_PLURALS[status]) return STATUS_PLURALS[status];
  return (publicationStatusInfo(status)?.label ?? status).toLowerCase();
}

/** A parent row's Tipo or Estado (owner, 2026-11-12: "pones badges y achicá los renglones"): compact badges on one
 * line, each with its whole words ("33 Clásica") in its tooltip and as its accessible name. */
function SummaryChips({ chips }) {
  if (chips.length === 0) return <span className={cellStyles.empty}>—</span>;
  return (
    <div className={cellStyles.chips}>
      {chips.map(({ key, name, tone, short, count, dot }) => (
        <span key={key} role="img" aria-label={name} title={name} className={cellStyles.chip} data-tone={tone} data-summary-chip="">
          {dot ? <span className={cellStyles.chipDot} aria-hidden="true" /> : <span className={cellStyles.chipShort}>{short} </span>}
          {count}
        </span>
      ))}
    </div>
  );
}

/** Tipo of a parent row: one badge per kind, short label then count ("C 2", "6 1"). Kinds that read the same (a
 * co-funded Clásica) share one badge. */
export function NodeKinds({ node }) {
  const byLabel = new Map();
  const kinds = Object.entries(node.kindCounts ?? {}).sort(([a], [b]) => kindRank(a) - kindRank(b) || a.localeCompare(b));
  for (const [kind, count] of kinds) {
    const label = listingKindLabel(kind);
    const seen = byLabel.get(label);
    byLabel.set(label, { kind: seen?.kind ?? kind, count: (seen?.count ?? 0) + count });
  }
  const chips = [...byLabel].map(([label, { kind, count }]) => ({
    key: label,
    name: `${formatCount(count)} ${label}`,
    tone: KINDS[kind]?.tone ?? 'neutral',
    short: listingKindShort(kind),
    count: formatCount(count),
  }));
  return <SummaryChips chips={chips} />;
}

/** Estado of a parent row: one badge per state, its coloured dot and count ("● 4"), "4 activas" in its tooltip. */
export function NodeStatuses({ node }) {
  const states = Object.entries(node.statusCounts ?? {}).sort(([a], [b]) => statusRank(a) - statusRank(b) || a.localeCompare(b));
  const chips = states.map(([status, count]) => ({
    key: status,
    name: `${formatCount(count)} ${statusWord(status, count)}`,
    tone: STATUS_TONES[status] ?? 'neutral',
    count: formatCount(count),
    dot: true,
  }));
  return <SummaryChips chips={chips} />;
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
