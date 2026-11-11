/**
 * TacticalCobranza — the Cobranza box that opens under a tactical row (handoffs/tactical-cobranza-tarea.md S3): Fecha
 * de cobro (the only required field), Medio (Nota de crédito → Número de NC, Fondo en distribuidor → Distribuidor,
 * Otro → Detalle) and Observaciones. Guardar saves the record (`PUT /tacticals/{id}/cobranza`) and the row reads
 * "Cobrado"; on a collected tactical, Deshacer cobro deletes it and the row is "Pendiente" again. `onGuardado` runs
 * after either, `onCerrar` on Cancelar or Escape. The server's refusal shows inside the box.
 */
import { useState } from 'react';
import { SegmentedControl } from '../kit';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { DETALLE_DE_MEDIO, MEDIOS, cuerpoDeCobranza, problemaDeCobranza, valoresDeCobranza } from './tacticalCobranza';
import dialogos from './tacticalDialogos.module.css';
import styles from './TacticalCobranza.module.css';

export default function TacticalCobranza({ tactical, onGuardado, onCerrar }) {
  const [valores, setValores] = useState(() => valoresDeCobranza(tactical.cobranza));
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const cambiar = (cambio) => setValores((v) => ({ ...v, ...cambio }));
  const detalle = DETALLE_DE_MEDIO[valores.medio];
  const id = `tactical-${tactical.id}-cobranza`;

  const enviar = async (llamada, mensaje) => {
    setEnviando(true);
    setError(null);
    try {
      await llamada();
      onGuardado();
    } catch (err) {
      setError(apiErrorMessage(err, mensaje));
      setEnviando(false);
    }
  };

  const guardar = (e) => {
    e.preventDefault();
    const problema = problemaDeCobranza(valores);
    if (problema) {
      setError(problema);
      return;
    }
    enviar(() => tacticalsAPI.cobrar(tactical.id, cuerpoDeCobranza(valores)), 'No se pudo guardar la cobranza.');
  };

  return (
    <form
      className={styles.caja}
      aria-label={`Cobranza de ${tactical.nombre}`}
      noValidate
      onSubmit={guardar}
      onKeyDown={(e) => e.key === 'Escape' && onCerrar()}
    >
      <p className={styles.titulo}>Cobranza</p>
      <div className={styles.fila}>
        <label className={dialogos.campo} htmlFor={`${id}-fecha`}>
          <span>Fecha de cobro *</span>
          <input
            id={`${id}-fecha`}
            type="date"
            className={dialogos.control}
            required
            value={valores.fecha}
            onChange={(e) => cambiar({ fecha: e.target.value })}
          />
        </label>
        <div className={dialogos.campo}>
          <span>Medio</span>
          <SegmentedControl label="Medio" options={MEDIOS} value={valores.medio} onChange={(medio) => cambiar({ medio })} />
        </div>
        {detalle && (
          <label className={`${dialogos.campo} ${styles.detalle}`} htmlFor={`${id}-detalle`}>
            <span>{detalle.label}</span>
            <input
              id={`${id}-detalle`}
              className={dialogos.control}
              maxLength={detalle.max}
              value={valores[detalle.campo]}
              onChange={(e) => cambiar({ [detalle.campo]: e.target.value })}
            />
          </label>
        )}
      </div>
      <label className={dialogos.campo} htmlFor={`${id}-observaciones`}>
        <span>Observaciones</span>
        <textarea
          id={`${id}-observaciones`}
          className={dialogos.control}
          rows={2}
          maxLength={2000}
          value={valores.observaciones}
          onChange={(e) => cambiar({ observaciones: e.target.value })}
        />
      </label>
      {error && (
        <div className={dialogos.error} role="alert">
          {error}
        </div>
      )}
      <div className={dialogos.dlgRow}>
        {tactical.cobranza && (
          <button
            type="button"
            className={`${dialogos.danger} ${styles.deshacer}`}
            disabled={enviando}
            onClick={() => enviar(() => tacticalsAPI.deshacerCobro(tactical.id), 'No se pudo deshacer el cobro.')}
          >
            Deshacer cobro
          </button>
        )}
        <button type="button" className={dialogos.ghost} onClick={onCerrar}>
          Cancelar
        </button>
        <button type="submit" className={dialogos.primary} disabled={enviando}>
          {enviando ? 'Guardando…' : 'Guardar'}
        </button>
      </div>
    </form>
  );
}
