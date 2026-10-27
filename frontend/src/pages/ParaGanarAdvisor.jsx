import { Target } from 'lucide-react';
import styles from './ParaGanarAdvisor.module.css';

/**
 * PARA GANAR advisor shell — empty canvas for iterative UX/logic.
 * Intent source: docs/para-ganar-pro-source-map.md (emulate & improve, not a port).
 * Unit of work: MLA (sync pairs as one row when applicable).
 */
export default function ParaGanarAdvisor() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Target className={styles.headerIcon} size={28} aria-hidden />
          <div>
            <h1 className={styles.title}>PARA GANAR</h1>
            <p className={styles.subtitle}>
              Advisor de precios por publicación — sugerencias según criterios (WIP)
            </p>
          </div>
        </div>
      </header>

      <section className={styles.toolbar} aria-label="Filtros de sugerencias">
        <button type="button" className={`${styles.chip} ${styles.chipActive}`} disabled>
          Pendientes
        </button>
        <button type="button" className={styles.chip} disabled>
          Aceptadas
        </button>
        <button type="button" className={styles.chip} disabled>
          Descartadas
        </button>
        <span className={styles.toolbarHint}>Filtros listos para conectar</span>
      </section>

      <div className={styles.layout}>
        <section className={styles.queue} aria-label="Cola de sugerencias">
          <div className={styles.panelTitle}>Cola (MLA)</div>
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>Sin sugerencias todavía</p>
            <p className={styles.emptyBody}>
              Acá va a vivir la lista filtrable de publicaciones con sugerencia.
              Empezamos vacío a propósito para ir armando layout y criterios juntos.
            </p>
          </div>
        </section>

        <aside className={styles.detail} aria-label="Detalle de sugerencia">
          <div className={styles.panelTitle}>Detalle</div>
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>Seleccioná un MLA</p>
            <p className={styles.emptyBody}>
              Catálogo usado, referente, markup, promoción sugerida (PREMIUM / SMART) y
              override del operador van a aparecer acá.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
