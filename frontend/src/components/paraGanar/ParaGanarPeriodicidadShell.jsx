import { CalendarClock } from 'lucide-react';
import styles from '../../pages/ParaGanarAdvisor.module.css';

/**
 * P1 shell for Gestionar periodicidad — EAN subscription UI arrives in P2/P3.
 */
export default function ParaGanarPeriodicidadShell() {
  return (
    <section className={styles.periodicidadShell} aria-label="Gestionar periodicidad">
      <div className={styles.emptyState}>
        <CalendarClock className={styles.periodicidadShellIcon} size={32} aria-hidden />
        <p className={styles.emptyTitle}>Gestionar periodicidad</p>
        <p className={styles.emptyBody}>
          Acá vas a suscribir EANs a la revisión periódica (todo el EAN, MLAs
          elegidos, o reglas por lista / tipo / tienda). Lo no suscripto se
          sigue consultando a mano desde Advisor. El alta de suscripciones
          llega en el próximo slice.
        </p>
      </div>
    </section>
  );
}
