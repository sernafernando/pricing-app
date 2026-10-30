import { useState } from 'react';
import { resultadoDeAnulacion } from './sellInAnularMasivo';
import styles from './SellInAnularMasivo.module.css';

/**
 * The bulk void bar of a sell-in list: "N seleccionados", "Seleccionar todo lo filtrado (N)" and "Anular
 * seleccionados", which opens a confirmation pane saying how many records are voided and what is reversed
 * (`revierte`). A refused set (409) voids nothing and lists each refused record with its reason.
 */
export default function SellInAnularMasivo({ sustantivo, seleccionados, total, revierte, onSeleccionarFiltrado, onLimpiar, anular, onHecho }) {
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null); // { mensaje, rechazadas }
  const n = seleccionados.length;
  const nombre = n === 1 ? sustantivo.singular : sustantivo.plural;

  const seleccionarFiltrado = async () => {
    setError(null);
    try {
      await onSeleccionarFiltrado();
    } catch (err) {
      setError({ mensaje: err.message, rechazadas: [] });
    }
  };

  const confirmar = async () => {
    setEnviando(true);
    setError(null);
    try {
      const { data } = await anular(seleccionados, motivo);
      setConfirmando(false);
      setMotivo('');
      onHecho(resultadoDeAnulacion(data, sustantivo));
    } catch (err) {
      const data = err?.response?.status === 409 ? err.response.data : null;
      setError(data?.mensaje ? { mensaje: data.mensaje, rechazadas: data.rechazadas ?? [] } : { mensaje: `No se pudieron anular las ${sustantivo.plural}.`, rechazadas: [] });
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        {n > 0 && <span className={styles.count}>{`${n} seleccionados`}</span>}
        {total > 0 && (
          <button type="button" className="btn-tesla ghost sm" onClick={seleccionarFiltrado}>
            {`Seleccionar todo lo filtrado (${total})`}
          </button>
        )}
        {n > 0 && (
          <>
            <button type="button" className="btn-tesla ghost sm" onClick={onLimpiar}>
              Limpiar selección
            </button>
            <button type="button" className="btn-tesla danger sm" onClick={() => setConfirmando(true)} disabled={confirmando}>
              Anular seleccionados
            </button>
          </>
        )}
      </div>
      {confirmando && n > 0 && (
        <div role="dialog" aria-label={`Anular ${n} ${nombre}`} className={styles.confirm}>
          <p>{`Se van a anular ${n} ${nombre}. ${revierte}`}</p>
          <p className={styles.hint}>Se anula todo o nada: si alguna no se puede anular, no se anula ninguna. Las ya anuladas se saltean.</p>
          <label className={styles.field}>
            <span>Motivo (opcional)</span>
            <input type="text" maxLength={500} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </label>
          <div className={styles.actions}>
            <button type="button" className="btn-tesla ghost sm" onClick={() => setConfirmando(false)} disabled={enviando}>
              Cancelar
            </button>
            <button type="button" className="btn-tesla danger sm" onClick={confirmar} disabled={enviando}>
              {enviando ? 'Anulando…' : `Sí, anular ${n}`}
            </button>
          </div>
        </div>
      )}
      {error && (
        <div role="alert" className={styles.error}>
          <p>{error.mensaje}</p>
          {error.rechazadas.length > 0 && (
            <ul>
              {error.rechazadas.map((r) => (
                <li key={r.id}>{`#${r.id}: ${r.motivo}`}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
