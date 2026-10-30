import { useEffect, useState } from 'react';
import { ANULAR_MASIVO_MAX, generoDe, resultadoDeAnulacion } from './sellInAnularMasivo';
import styles from './SellInAnularMasivo.module.css';

/**
 * The bulk void bar of a sell-in list: "N seleccionados", "Seleccionar todo lo filtrado (N)" and "Anular
 * seleccionados", which opens a confirmation pane saying how many records are voided and what is reversed
 * (`revierte`). A refused set (409, or 422 for unknown ids) voids nothing and lists each refused record with its reason. `onHecho(mensaje,
 * data)` gets what happened and the API's answer (`anuladas`, `ya_anuladas`). `total` is how many of the filtered
 * records can be voided; `nota` says why the rest cannot (purchases a bonus generated).
 */
export default function SellInAnularMasivo({ sustantivo, seleccionados, total, nota, revierte, onSeleccionarFiltrado, onLimpiar, anular, onHecho }) {
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null); // { mensaje, rechazadas }
  const n = seleccionados.length;
  const nombre = n === 1 ? sustantivo.singular : sustantivo.plural;
  const g = generoDe(sustantivo);

  // An emptied selection (other filters, "Limpiar selección") closes the confirmation, so it never reopens by itself,
  // and drops an old refusal.
  useEffect(() => {
    if (n === 0) {
      setConfirmando(false);
      // A void that went through empties the selection itself: its warning is about what was done, so it stays.
      setError((actual) => (actual?.trasAnular ? actual : null));
    }
  }, [n]);

  const abrirConfirmacion = () => {
    if (n > ANULAR_MASIVO_MAX) {
      setError({ mensaje: `Son ${n}: se pueden anular hasta ${ANULAR_MASIVO_MAX} por vez.`, rechazadas: [] });
      return;
    }
    setError(null);
    setConfirmando(true);
  };

  const seleccionarFiltrado = async () => {
    setError(null);
    try {
      await onSeleccionarFiltrado();
    } catch (err) {
      // Our own refusals (`resolverIdsFiltrados`, filters that changed) explain themselves; a failed request does not.
      const deRed = err?.isAxiosError || err?.response;
      setError({ mensaje: deRed ? 'No se pudo leer la lista para seleccionar todo lo filtrado.' : err.message, rechazadas: [] });
    }
  };

  const confirmar = async () => {
    setEnviando(true);
    setError(null);
    let data;
    try {
      ({ data } = await anular(seleccionados, motivo));
    } catch (err) {
      // 409: one refused by its guard, or another writer in the way (retry); 422: ids that do not exist.
      const rechazo = [409, 422].includes(err?.response?.status) ? err.response.data : null;
      setError(rechazo?.mensaje ? { mensaje: rechazo.mensaje, rechazadas: rechazo.rechazadas ?? [] } : { mensaje: `No se pudieron anular ${g.los} ${sustantivo.plural}.`, rechazadas: [] });
      return;
    } finally {
      setEnviando(false);
    }
    setConfirmando(false);
    setMotivo('');
    // The void already went through: a failure from here on is the page's, never "could not void".
    try {
      onHecho(resultadoDeAnulacion(data, sustantivo), data);
    } catch {
      setError({ mensaje: 'Se anularon, pero la pantalla no se pudo actualizar. Recargá la página.', rechazadas: [], trasAnular: true });
    }
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        {n > 0 && <span className={styles.count}>{n === 1 ? '1 seleccionado' : `${n} seleccionados`}</span>}
        {total > 0 && (
          <button type="button" className="btn-tesla ghost sm" onClick={seleccionarFiltrado}>
            {`Seleccionar todo lo filtrado (${total})`}
          </button>
        )}
        {nota && <span className={styles.nota}>{nota}</span>}
        {n > 0 && (
          <>
            <button
              type="button"
              className="btn-tesla ghost sm"
              onClick={() => {
                setError(null);
                onLimpiar();
              }}
            >
              Limpiar selección
            </button>
            <button type="button" className="btn-tesla danger sm" onClick={abrirConfirmacion} disabled={confirmando}>
              Anular seleccionados
            </button>
          </>
        )}
      </div>
      {confirmando && n > 0 && (
        <div role="dialog" aria-label={`Anular ${n} ${nombre}`} className={styles.confirm}>
          <p>{`Se van a anular ${n} ${nombre}. ${revierte}`}</p>
          <p className={styles.hint}>{`Se anula todo o nada: si ${g.alguno} no se puede anular, no se anula ${g.ninguno}. ${g.los === 'las' ? 'Las' : 'Los'} ya anulad${g.o}s se saltean.`}</p>
          <label className={styles.field}>
            <span>Motivo (opcional)</span>
            <input type="text" maxLength={500} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </label>
          <div className={styles.actions}>
            <button
              type="button"
              className="btn-tesla ghost sm"
              onClick={() => {
                setConfirmando(false);
                setError(null);
              }}
              disabled={enviando}
            >
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
