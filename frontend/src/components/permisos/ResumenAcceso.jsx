import { AlertTriangle, Ban, MonitorCheck, SlidersHorizontal } from 'lucide-react';
import styles from './ResumenAcceso.module.css';

/**
 * KPI strip above the screen list. Pure renderer: `resumen` comes from
 * `resumenAcceso(vista)` and `overrides` from `contarOverrides(...)`, the same
 * view the list renders, so the numbers always match the rows below.
 */
export default function ResumenAcceso({ resumen, overrides }) {
  return (
    <section className={styles.strip} aria-label="Resumen de acceso">
      <Kpi nombre="Pantallas accesibles" icono={MonitorCheck} sub="Incluye las públicas">
        {`${resumen.accesibles} / ${resumen.total}`}
      </Kpi>
      <Kpi nombre="Sin acceso" icono={Ban} tono="danger" sub="Pantallas que no puede abrir">
        {resumen.sinAcceso}
      </Kpi>
      <Kpi nombre="Condicionales" icono={AlertTriangle} tono="warning" sub="Tiene el permiso pero no ve datos">
        {resumen.condicionales}
      </Kpi>
      <Kpi nombre="Overrides" icono={SlidersHorizontal} sub="Agregados / quitados a mano">
        <span className={styles.agregados}>+{overrides.agregados}</span>
        <span className={styles.separador} aria-hidden="true">/</span>
        <span className={styles.quitados}>−{overrides.quitados}</span>
      </Kpi>
    </section>
  );
}

function Kpi({ nombre, icono: Icono, tono, sub, children }) {
  return (
    <div role="group" aria-label={nombre} className={`${styles.card} ${tono ? styles[tono] : ''}`}>
      <span className={styles.label}>
        {nombre}
        <Icono size={14} aria-hidden="true" />
      </span>
      <span className={styles.value}>{children}</span>
      <span className={styles.sub}>{sub}</span>
    </div>
  );
}
