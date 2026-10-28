import styles from './PublicationStatCards.module.css';

const number = new Intl.NumberFormat('es-AR');
const NO_TYPES = [];

const sameStatus = (filters, status) => filters.estado.length === 1 && filters.estado[0] === status;
const withPromo = (filters) => filters.promo_estado === 'aplicada' && filters.promo_tipos.length === 0;

/**
 * The Publicaciones view's summary (owner, 2026-10-28): how many publications are active, paused, with a started
 * promotion and without one, over the list's filters. The figures are the `/items` facets (`status` and `promo`), so
 * they follow every other filter. Con promo counts the same set its click lists: the backend counts the publications
 * with a started promotion, which is what "Aplicada" (`con_promo_aplicada`) filters. A click applies the figure's
 * filter (the status, or "Aplicada" promotions) and a
 * second click takes it off; Sin promo has no filter of its own, so it is only a figure. No answer yet reads "…", a
 * promo count the backend could not read "–": never 0.
 */
export default function PublicationCountCards({ facets, filters, onApply }) {
  const promo = facets ? (facets.promo ?? null) : undefined;
  const cards = [
    {
      label: 'Activas',
      value: facets?.status?.active ?? (facets ? 0 : undefined),
      active: sameStatus(filters, 'active'),
      apply: (on) => ({ estado: on ? [] : ['active'] }),
    },
    {
      label: 'Pausadas',
      value: facets?.status?.paused ?? (facets ? 0 : undefined),
      active: sameStatus(filters, 'paused'),
      apply: (on) => ({ estado: on ? [] : ['paused'] }),
    },
    {
      label: 'Con promo',
      value: promo === undefined ? undefined : (promo?.con_promo ?? null),
      active: withPromo(filters),
      apply: (on) => ({ promo_estado: on ? '' : 'aplicada', promo_tipos: NO_TYPES }),
    },
    { label: 'Sin promo', value: promo === undefined ? undefined : (promo?.sin_promo ?? null) },
  ];

  return (
    <section className={styles.strip} aria-label="Totales de publicaciones">
      <div className={styles.cards}>
        {cards.map((card) => {
          const shown = card.value === undefined ? '…' : card.value === null ? '–' : number.format(card.value);
          const spoken = card.value === undefined ? 'cargando' : card.value === null ? 'no disponible' : number.format(card.value);
          const content = (
            <>
              <span className={styles.itemLabel}>{card.label}</span>
              <span className={styles.value}>{shown}</span>
            </>
          );
          return (
            <div key={card.label} className={styles.card} role="group" aria-label={card.label}>
              {card.apply ? (
                <button
                  type="button"
                  className={styles.single}
                  aria-pressed={card.active}
                  aria-label={`${card.label}: ${spoken}`}
                  onClick={() => onApply(card.apply(card.active))}
                >
                  {content}
                </button>
              ) : (
                <div className={`${styles.single} ${styles.figureOnly}`}>{content}</div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
