/**
 * TacticalEditar — the Editar dialog of the Tacticals tab (tacticals F1): the name, the note, the end date and each
 * line's caps, the only fields that are safe to change on live money. Lines, values and scope are not here (that is
 * Anular + Renovar). It sends only what changed (`PATCH /tacticals/{id}`); the server judges the dates against today
 * and the caps against what was already used, and its refusal shows inside the dialog. Same focus handling as the
 * other dialogs of Sell in / Sell out (`useFocoAtrapado`); Escape closes without saving.
 */
import { useState } from 'react';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { useFocoAtrapado } from '../sellOut/useFocoAtrapado';
import { cuerpoDeEdicion, problemaDeEdicion, valoresDeEdicion } from './tacticalEditar';
import { formatMontoTactical, formatUnidades } from './tacticalsFormat';
import styles from './tacticalDialogos.module.css';

const hoyISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export default function TacticalEditar({ tactical, onCerrar, onGuardado }) {
  const foco = useFocoAtrapado();
  const [valores, setValores] = useState(() => valoresDeEdicion(tactical));
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const titulo = `tactical-editar-${tactical.id}`;
  const desde = tactical.fecha_desde > hoyISO() ? tactical.fecha_desde : hoyISO();

  const cambiar = (cambio) => setValores((v) => ({ ...v, ...cambio }));
  const cambiarLinea = (linea, cambio) =>
    setValores((v) => ({ ...v, lineas: v.lineas.map((l) => (l.linea === linea ? { ...l, ...cambio } : l)) }));

  const guardar = async (e) => {
    e.preventDefault();
    const problema = problemaDeEdicion(valores);
    if (problema) {
      setError(problema);
      return;
    }
    const cuerpo = cuerpoDeEdicion(tactical, valores);
    if (Object.keys(cuerpo).length === 0) {
      onCerrar();
      return;
    }
    setEnviando(true);
    setError(null);
    try {
      await tacticalsAPI.editar(tactical.id, cuerpo);
      onGuardado();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo guardar el tactical.'));
      setEnviando(false);
    }
  };

  return (
    <div className={styles.overlay}>
      <form
        ref={foco.ref}
        className={styles.dlg}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titulo}
        onSubmit={guardar}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCerrar();
          else foco.onKeyDown(e);
        }}
      >
        <h3 id={titulo}>Editar {tactical.nombre}</h3>
        <p className={styles.ayuda}>
          Las líneas, los montos y el alcance no se editan: para cambiarlos, anulá el tactical y renovalo.
        </p>
        <label className={styles.campo}>
          <span>Nombre</span>
          <input
            data-foco-inicial
            className={styles.control}
            value={valores.nombre}
            maxLength={200}
            onChange={(e) => cambiar({ nombre: e.target.value })}
          />
        </label>
        <label className={styles.campo}>
          <span>Nota</span>
          <textarea className={styles.control} rows={2} value={valores.nota} onChange={(e) => cambiar({ nota: e.target.value })} />
        </label>
        <label className={styles.campo}>
          <span>Fecha hasta</span>
          <input
            type="date"
            className={styles.control}
            min={desde}
            value={valores.fechaHasta}
            onChange={(e) => cambiar({ fechaHasta: e.target.value })}
          />
        </label>

        <fieldset className={styles.lineas}>
          <legend>Topes por línea</legend>
          {valores.lineas.map((l) => (
            <div key={l.linea} className={styles.linea}>
              <div className={styles.lineaHead}>
                <strong>Línea {l.linea}</strong> · {l.titulo}
              </div>
              {l.admiteTopes ? (
                <div className={styles.topes}>
                  <label className={styles.tope}>
                    <span>Tope u.</span>
                    <input
                      className={styles.control}
                      inputMode="numeric"
                      aria-label={`Tope de unidades de la línea ${l.linea}`}
                      placeholder="Sin tope"
                      value={l.topeUnidades}
                      onChange={(e) => cambiarLinea(l.linea, { topeUnidades: e.target.value })}
                    />
                  </label>
                  <label className={styles.tope}>
                    <span>Tope {l.moneda}</span>
                    <input
                      className={styles.control}
                      inputMode="decimal"
                      aria-label={`Tope de monto de la línea ${l.linea}`}
                      placeholder="Sin tope"
                      value={l.topeMonto}
                      onChange={(e) => cambiarLinea(l.linea, { topeMonto: e.target.value })}
                    />
                  </label>
                </div>
              ) : (
                <div className={styles.nota}>Un monto total no lleva topes: el monto total es el tope.</div>
              )}
              <div className={styles.nota}>
                Ya usó {formatUnidades(l.usadas)} u · {formatMontoTactical(l.usado, l.moneda)}
              </div>
            </div>
          ))}
        </fieldset>

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}
        <div className={styles.dlgRow}>
          <button type="button" className={styles.ghost} onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className={styles.primary} disabled={enviando}>
            {enviando ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      </form>
    </div>
  );
}
