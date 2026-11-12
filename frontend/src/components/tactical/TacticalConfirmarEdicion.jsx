/**
 * TacticalConfirmarEdicion — "¿Guardar los cambios?" before an edit replaces the tactical (S8): saving loads it again
 * as if from scratch, so what it already applied is recomputed, and a set `al_cobro` rate that a change of type,
 * currency or FX mode discards is named (D2). Same dialog behavior as TacticalDescartar: focus starts on "Seguir
 * editando", stays inside on Tab, Escape keeps editing.
 */
import { useFocoAtrapado } from '../sellOut/useFocoAtrapado';
import { dinero } from './tacticalLineas';
import styles from './TacticalDescartar.module.css';

const plural = (n, uno, varios) => (n === 1 ? uno : varios);

export default function TacticalConfirmarEdicion({ impacto, enviando, onSeguir, onGuardar }) {
  const foco = useFocoAtrapado();
  const montos = Object.entries(impacto.aplicado).map(([moneda, monto]) => dinero(moneda, monto));
  const aplico = montos.length > 0 || impacto.unidades > 0;
  return (
    <div className={styles.overlay}>
      <div
        ref={foco.ref}
        className={styles.dlg}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tactical-confirmar-edicion"
        onKeyDown={(e) => {
          if (e.key === 'Escape') onSeguir();
          else foco.onKeyDown(e);
        }}
      >
        <h3 id="tactical-confirmar-edicion">¿Guardar los cambios?</h3>
        <p>El tactical se vuelve a cargar con estos datos, como si lo crearas de cero.</p>
        {aplico && (
          <p>
            Ya aplicó {montos.join(' y ') || 'montos'} en {impacto.unidades.toLocaleString('es-AR')}{' '}
            {plural(impacto.unidades, 'unidad', 'unidades')}: se recalcula con los datos nuevos, también lo ya vendido.
          </p>
        )}
        {impacto.tcDescartado != null && (
          <p>
            <b>
              Se descarta el tipo de cambio al cobro cargado ({impacto.tcDescartado.toLocaleString('es-AR')}): vas a
              tener que cargarlo de nuevo.
            </b>
          </p>
        )}
        <div className={styles.dlgRow}>
          <button type="button" className={styles.ghost} data-foco-inicial onClick={onSeguir}>
            Seguir editando
          </button>
          <button type="button" className={styles.danger} onClick={onGuardar} disabled={enviando}>
            {enviando ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      </div>
    </div>
  );
}
