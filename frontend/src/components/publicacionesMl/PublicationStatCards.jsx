import { AlertTriangle } from 'lucide-react';
import { isStatActive, statCardGroups, statUpdates } from './statCards';
import styles from './PublicationStatCards.module.css';

const number = new Intl.NumberFormat('es-AR');

/**
 * Productos' stat cards over the screen's filters (S12d4): each figure counts the linked products its click lists,
 * and the click applies that card's filter (`statUpdates`, Productos' `aplicarFiltroStat`); Total Productos clears
 * the filters. The figure of the card on show is marked (`aria-pressed`). The last figures stay while new ones load.
 *
 * `state` is `{ data, loading, error }` of `GET /view/stats`; `markupNotice` says a publication markup filter is on
 * (Markup < 0 / min / max), which the cards cannot apply, as the KPI strip says it.
 */
export default function PublicationStatCards({ state, filters, canSeeMargin, onApply, onReset, onRetry, markupNotice = false }) {
  const stats = state.data?.stats ?? null;
  const groups = statCardGroups(stats, { canSeeMargin });
  const shown = (value) => (value === null ? 'cargando' : number.format(value));

  return (
    <section className={styles.strip} aria-label="Totales de productos" aria-busy={state.loading}>
      {state.error && !stats && (
        <div className={styles.error} role="alert">
          <AlertTriangle size={14} aria-hidden="true" />
          <span>No se pudieron cargar los totales.</span>
          <button type="button" className="btn-tesla ghost sm" onClick={onRetry}>
            Reintentar
          </button>
        </div>
      )}
      {markupNotice && (
        <p className={styles.notice}>Los totales no aplican el filtro de markup de la publicación (Markup &lt; 0, mín. o máx.).</p>
      )}
      <div className={styles.cards}>
        {groups.map((group) => (
          <div key={group.label} className={styles.card} role="group" aria-label={group.label}>
            {group.items.length > 1 && <span className={styles.cardLabel}>{group.label}</span>}
            {group.items.map((item) => {
              const active = !item.reset && isStatActive(filters, item.filter);
              return (
                <button
                  key={item.label}
                  type="button"
                  className={group.items.length > 1 ? styles.subItem : styles.single}
                  aria-pressed={item.reset ? undefined : active}
                  aria-label={`${item.label}: ${shown(item.value)}`}
                  onClick={() => (item.reset ? onReset() : onApply(statUpdates(item.filter)))}
                >
                  <span className={styles.itemLabel}>{item.label}</span>
                  <span className={styles.value}>{item.value === null ? '…' : number.format(item.value)}</span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </section>
  );
}
