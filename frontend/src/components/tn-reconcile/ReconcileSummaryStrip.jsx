import styles from '../../pages/TiendaNubeReconcile.module.css';

// Summary strip cards (PR-10) — answer the operator's real question, not
// the raw verdict taxonomy. `targetSubTab` is what a click switches the
// verdict chips to; `filterId` is the extra predicate applied on top
// (`matchesSummaryFilter`), since "ready"/"bloqueados" are both a SPLIT of
// the single FALTA_PUBLICAR verdict that the existing chip set can't
// express on its own.
const SUMMARY_CARDS = [
  {
    id: 'ready',
    label: 'Listo para publicar',
    dot: 'summaryDotGreen',
    hint: 'sin bloqueos',
    targetSubTab: 'FALTA_PUBLICAR',
    countKey: 'readyToPublish',
  },
  {
    id: 'bloqueados',
    label: 'Bloqueados',
    dot: 'summaryDotRed',
    hint: 'faltan medidas o cotización',
    targetSubTab: 'FALTA_PUBLICAR',
    countKey: 'bloqueados',
  },
  {
    id: 'revision',
    label: 'Necesitan revisión',
    dot: 'summaryDotPurple',
    hint: 'duplicados y mal vinculados',
    targetSubTab: 'todos',
    countKey: 'necesitanRevision',
  },
  {
    id: 'total',
    label: 'Total del reporte',
    dot: 'summaryDotGrey',
    hint: 'filas comparadas',
    targetSubTab: 'todos',
    countKey: 'total',
  },
];

export default function ReconcileSummaryStrip({ summaryCounts, summaryFilterActive, summaryFilter, onSelectCard }) {
  return (
    <div className={styles.summaryStrip}>
      {SUMMARY_CARDS.map((card) => (
        <button
          key={card.id}
          type="button"
          className={`${styles.summaryCard} ${
            summaryFilterActive && summaryFilter === card.id ? styles.summaryCardActive : ''
          }`}
          onClick={() => onSelectCard(card)}
        >
          <span className={styles.summaryCardLabel}>
            <span className={`${styles.summaryDot} ${styles[card.dot]}`} aria-hidden="true" />
            {card.label}
          </span>
          <span className={styles.summaryValue}>{summaryCounts[card.countKey]}</span>
          <span className={styles.summaryHint}>{card.hint}</span>
        </button>
      ))}
    </div>
  );
}
