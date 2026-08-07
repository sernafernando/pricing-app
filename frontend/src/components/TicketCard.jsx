import { MessageSquareWarning } from 'lucide-react';
import ProvenanceBadge from './ProvenanceBadge';
import styles from './TicketCard.module.css';

/**
 * A single board card (tickets-ai-triage PR 5b, deferred from PR 4c).
 *
 * Draggable since PR 5c: `dragRef`/`dragAttributes`/`dragListeners` are
 * optional dnd-kit `useDraggable()` output, applied directly to this same
 * `<button>` (not a wrapping div) — the button is already the interactive
 * element, so there is no nested-interactive-content a11y issue. All three
 * props are undefined when the card renders outside a draggable context
 * (e.g. these unit tests), so the button behaves exactly as before.
 * Within-column order is never implied to persist — no order column exists
 * (design's "no order column exists"); see `TicketsBoard.jsx`.
 *
 * The pending-proposals indicator is the point of the board: it tells the
 * maintainer at a glance where his attention is owed.
 */
export default function TicketCard({ ticket, onClick, dragRef, dragAttributes, dragListeners, isDragging }) {
  const pendientes = ticket.propuestas_pendientes ?? 0;

  return (
    <button
      type="button"
      ref={dragRef}
      className={isDragging ? `${styles.card} ${styles.cardDragging}` : styles.card}
      onClick={() => onClick?.(ticket.id)}
      {...dragAttributes}
      {...dragListeners}
    >
      <div className={styles.cardHeader}>
        <span className={styles.ticketId}>#{ticket.id}</span>
        {pendientes > 0 && (
          <span
            className={styles.pendingBadge}
            title={`${pendientes} propuesta(s) de IA pendiente(s) de confirmar`}
          >
            <MessageSquareWarning size={11} />
            {pendientes}
          </span>
        )}
      </div>

      <div className={styles.titulo}>{ticket.titulo}</div>
      {ticket.resumen && <div className={styles.resumen}>{ticket.resumen}</div>}

      <div className={styles.metaRow}>
        <span className={styles.metaItem}>
          {ticket.severidad || 'Sin clasificar'}
          <ProvenanceBadge origen={ticket.severidad_origen} />
        </span>
        <span className={styles.metaItem}>
          {ticket.urgencia || 'Sin clasificar'}
          <ProvenanceBadge origen={ticket.urgencia_origen} />
        </span>
      </div>
    </button>
  );
}
