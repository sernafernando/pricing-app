import { MessageSquareWarning } from 'lucide-react';
import ProvenanceBadge from './ProvenanceBadge';
import styles from './TicketCard.module.css';

/**
 * A single board card (tickets-ai-triage PR 5b, deferred from PR 4c).
 * Read-only — no drag handle, no affordance implying within-column order
 * is persisted (it isn't, see design's "no order column exists").
 *
 * The pending-proposals indicator is the point of the board: it tells the
 * maintainer at a glance where his attention is owed.
 */
export default function TicketCard({ ticket, onClick }) {
  const pendientes = ticket.propuestas_pendientes ?? 0;

  return (
    <button type="button" className={styles.card} onClick={() => onClick?.(ticket.id)}>
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
