import { ChevronDown, ChevronRight } from 'lucide-react';
import styles from './cells.module.css';

/**
 * Expands / collapses the variation sub-rows of a publication. Rendered only
 * for publications with more than one variation (`variations_count > 1`): one
 * variation has nothing to expand.
 */
export default function VariationsToggle({ item, expanded, onToggle }) {
  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      className={styles.toggle}
      aria-expanded={expanded}
      aria-label={`${expanded ? 'Ocultar' : 'Ver'} las ${item.variations_count} variaciones de ${item.item_id}`}
      onClick={() => onToggle(item.item_id)}
    >
      <Icon size={14} aria-hidden="true" />
    </button>
  );
}
