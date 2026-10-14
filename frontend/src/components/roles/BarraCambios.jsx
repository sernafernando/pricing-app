import styles from './MatrizRoles.module.css';

/**
 * Sticky bar shown while the matrix has unsaved cells. `bloqueado` disables both
 * buttons without the Guardando... label (a role change is in flight, not a save).
 */
export default function BarraCambios({ cantidad, guardando, bloqueado = false, onDescartar, onGuardar }) {
  if (cantidad === 0) return null;

  return (
    <section className={styles.barra} aria-label="Cambios pendientes">
      <span className={styles.barraTexto}>
        {cantidad === 1 ? '1 cambio pendiente' : `${cantidad} cambios pendientes`}
      </span>
      <div className={styles.barraAcciones}>
        <button type="button" className="btn-tesla ghost sm" onClick={onDescartar} disabled={guardando || bloqueado}>
          Descartar
        </button>
        <button type="button" className="btn-tesla outline-subtle-success sm" onClick={onGuardar} disabled={guardando || bloqueado}>
          {guardando ? 'Guardando...' : 'Guardar'}
        </button>
      </div>
    </section>
  );
}
