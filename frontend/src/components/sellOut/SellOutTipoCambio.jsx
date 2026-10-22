import { useId, useState } from 'react';
import { sellOutAPI } from '../../services/sellOutAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import { apiMessage, formatNumero } from '../sellIn/sellInFormat';
import styles from '../sellIn/SellInPanel.module.css';

/**
 * The payment rate of a USD `al_cobro` sell-out campaign (`POST /sell-out/campanas/{id}/tipo-cambio`, T8c).
 * Until it is set, ARS amounts are estimated with the day's BNA rate. It can be set, and changed, also after
 * the campaign ended; the campaign is recalculated by itself. `onDefinido` gets the campaign as stored.
 * `busy` / `onBusyChange` are the panel's: one request at a time across the whole panel.
 */
export default function SellOutTipoCambio({ campana, onDefinido, busy = false, onBusyChange = () => {} }) {
  const id = useId();
  const [valor, setValor] = useState('');
  const [error, setError] = useState(null);
  const definido = campana.tipo_cambio != null;

  const definir = async () => {
    if (!(Number(valor) > 0)) {
      setError('El tipo de cambio tiene que ser mayor a 0.');
      return;
    }
    onBusyChange(true);
    setError(null);
    try {
      const { data } = await sellOutAPI.definirTipoCambio(campana.id, valor.trim());
      setValor('');
      onDefinido(data);
    } catch (err) {
      setError(apiMessage(err, 'No se pudo definir el tipo de cambio.'));
    } finally {
      onBusyChange(false);
    }
  };

  return (
    <section className={styles.section} aria-label="Tipo de cambio de cobro">
      <h3>Tipo de cambio de cobro</h3>
      <p className={styles.hint}>
        {definido
          ? `Definido: ${formatNumero(campana.tipo_cambio)}${campana.tc_definido_en ? ` (el ${formatDateOnly(campana.tc_definido_en)})` : ''}.`
          : 'Sin definir: hasta que la marca pague, los montos en pesos se estiman con el dólar BNA del día.'}
      </p>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <div className={styles.grid2}>
        <label className={styles.field} htmlFor={`${id}-tc`}>
          <span className={styles.label}>Valor del tipo de cambio</span>
          <input
            id={`${id}-tc`}
            type="number"
            min="0"
            step="0.000001"
            className={styles.input}
            value={valor}
            onChange={(e) => setValor(e.target.value)}
          />
        </label>
        <div className={styles.field}>
          <span className={styles.label}>&nbsp;</span>
          <button type="button" className="btn-tesla outline sm" onClick={definir} disabled={busy}>
            {definido ? 'Cambiar tipo de cambio' : 'Definir tipo de cambio'}
          </button>
        </div>
      </div>
    </section>
  );
}
