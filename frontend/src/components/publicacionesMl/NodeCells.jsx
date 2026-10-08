import { ChevronDown, ChevronRight } from 'lucide-react';
import MarkupCell from './MarkupCell';
import { describeTreeError } from './groupTree';
import styles from './NodeCells.module.css';
import cellStyles from './cells.module.css';

const KIND_LABELS = {
  marca: 'Marca',
  categoria: 'Categoría',
  subcategoria: 'Subcategoría',
  producto: 'Producto',
  familia: 'Familia',
  item: 'Publicación',
};

const formatCount = (count) => count.toLocaleString('es-AR');

/** Pinned cell of a node: open/close toggle, name, what kind of node it is, and its code. */
export function NodeTitle({ row, onToggle }) {
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
      <div className={styles.nodeText}>
        <span className={styles.nodeLabel} data-muted={node.withoutProduct || node.key === '__none__' ? '' : undefined}>
          {node.label}
        </span>
        <span className={cellStyles.note}>
          {KIND_LABELS[node.kind] ?? node.kind}
          {node.codigo ? ` · ${node.codigo}` : ''}
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

/** Publications in the node. */
export const NodeCount = ({ node }) => <span className={cellStyles.units}>{formatCount(node.count)}</span>;

/** Publications of the node with a negative variation; "—" while the backend does not say. */
export function NodeNegatives({ node }) {
  if (node.negativeCount == null) return <span className={cellStyles.empty}>—</span>;
  return (
    <span className={cellStyles.units} data-negative={node.negativeCount > 0 ? '' : undefined}>
      {formatCount(node.negativeCount)}
    </span>
  );
}

/** Markup range of the node's variations: the list's cell, so a null range reads the same ("—"). */
export function NodeMarkup({ node }) {
  if (node.markup == null) return <MarkupCell markup={null} />;
  return <MarkupCell markup={{ ...node.markup, any_negative: (node.negativeCount ?? 0) > 0, partial: 0 }} />;
}
