import { AlertTriangle, Ban, MonitorCheck, SlidersHorizontal } from 'lucide-react';
import styles from './ResumenAcceso.module.css';

/**
 * KPI strip above the screen list. Pure renderer: `resumen` comes from
 * `resumenAcceso(vista)` and `overrides` from `contarOverrides(...)`, the same
 * view the list renders, counted over every screen regardless of search or filters.
 */
export default function ResumenAcceso({ resumen, overrides }) {
  return (
    <section className={styles.strip} aria-label="Resumen de acceso">
      <Kpi nombre="Pantallas accesibles" icono={<MonitorCheck size={14} aria-hidden="true" />} sub="Incluye las públicas">
        {`${resumen.accesibles} / ${resumen.total}`}
      </Kpi>
      <Kpi nombre="Sin acceso" icono={<Ban size={14} aria-hidden="true" />} tono="danger" sub="Pantallas que no puede abrir">
        {resumen.sinAcceso}
      </Kpi>
      <Kpi nombre="Condicionales" icono={<AlertTriangle size={14} aria-hidden="true" />} tono="warning" sub="Tiene el permiso pero no ve datos">
        {resumen.condicionales}
      </Kpi>
      <Kpi nombre="Overrides" icono={<SlidersHorizontal size={14} aria-hidden="true" />} sub="Agregados / quitados a mano">
        <span className={styles.agregados}>+{overrides.agregados}</span>
        <span className={styles.separador} aria-hidden="true">/</span>
        <span className={styles.quitados}>−{overrides.quitados}</span>
      </Kpi>
    </section>
  );
}

function Kpi({ nombre, icono, tono, sub, children }) {
  return (
    <div role="group" aria-label={nombre} className={`${styles.card} ${tono ? styles[tono] : ''}`}>
      <span className={styles.label}>
        {nombre}
        {icono}
      </span>
      <span className={styles.value}>{children}</span>
      <span className={styles.sub}>{sub}</span>
    </div>
  );
}
