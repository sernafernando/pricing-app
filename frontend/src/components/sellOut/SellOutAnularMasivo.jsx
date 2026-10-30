import { useId, useState } from 'react';
import { sellOutAPI } from '../../services/sellOutAPI';
import { apiMessage } from '../sellIn/sellInFormat';
import SellOutCampanasTable from './SellOutCampanasTable';
import { ANULAR_MASIVO_MAX, resolverFiltradas, textoConfirmacion, textoResultado } from './sellOutSeleccion';
import panelStyles from '../sellIn/SellInPanel.module.css';
import styles from './SellOutAnularMasivo.module.css';

const MOTIVO_MAX = 500; // backend `SellOutAnularMasivoIn.motivo` (auditoria.comentario is VARCHAR(500))

/**
 * The sell-out campaigns list with bulk void (`POST /sell-out/campanas/anular`, `sell_out.gestionar`): row and page
 * checkboxes, "Seleccionar todo lo filtrado" (fail-closed, `resolverFiltradas`), a confirmation and the result. All or
 * nothing on the server: a refusal voids nothing and names each refused campaign. Without `puedeGestionar` it is the
 * plain table. The parent keys it by the filters, so a new search starts a new selection.
 */
export default function SellOutAnularMasivo({ campanas, total, filtros, puedeGestionar, selectedId, onSelect, onAnuladas }) {
  const id = useId();
  const [seleccion, setSeleccion] = useState(() => new Map()); // id → estado
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [busy, setBusy] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState(null); // { mensaje, rechazadas: [{ id, motivo }] }

  if (!puedeGestionar) return <SellOutCampanasTable campanas={campanas} selectedId={selectedId} onSelect={onSelect} />;

  const paginaSeleccionada = campanas.length > 0 && campanas.every((c) => seleccion.has(c.id));
  const cambiar = (siguiente) => {
    setSeleccion(siguiente);
    setResultado(null);
    setError(null);
    if (siguiente.size === 0) setConfirmando(false);
  };
  const alternar = (campana) => {
    const siguiente = new Map(seleccion);
    if (siguiente.has(campana.id)) siguiente.delete(campana.id);
    else siguiente.set(campana.id, campana.estado);
    cambiar(siguiente);
  };
  const alternarPagina = () => {
    const siguiente = new Map(seleccion);
    campanas.forEach((c) => (paginaSeleccionada ? siguiente.delete(c.id) : siguiente.set(c.id, c.estado)));
    cambiar(siguiente);
  };
  const seleccionarFiltradas = async () => {
    setBusy(true);
    try {
      cambiar(await resolverFiltradas(sellOutAPI.listar, filtros, total));
    } catch (err) {
      cambiar(new Map());
      setError({ mensaje: err.message, rechazadas: [] });
    } finally {
      setBusy(false);
    }
  };
  const anular = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellOutAPI.anularVarias([...seleccion.keys()], motivo);
      cambiar(new Map());
      setMotivo('');
      setResultado(textoResultado(data));
      onAnuladas();
    } catch (err) {
      setConfirmando(false);
      const rechazadas = err?.response?.data?.error?.rechazadas;
      setError({ mensaje: apiMessage(err, 'No se pudieron anular las campañas.'), rechazadas: rechazadas ?? [] });
    } finally {
      setBusy(false);
    }
  };

  const yaAnuladas = [...seleccion.values()].filter((estado) => estado === 'anulada').length;
  const demasiadas = seleccion.size > ANULAR_MASIVO_MAX;

  return (
    <>
      <div className={styles.bar}>
        {seleccion.size > 0 && (
          <span className={styles.count}>
            {seleccion.size === 1 ? '1 seleccionada' : `${seleccion.size} seleccionadas`}
          </span>
        )}
        <div className={styles.actions}>
          <button type="button" className="btn-tesla ghost sm" onClick={seleccionarFiltradas} disabled={busy}>
            {`Seleccionar todo lo filtrado (${total})`}
          </button>
          {seleccion.size > 0 && (
            <>
              <button type="button" className="btn-tesla outline sm" onClick={() => cambiar(new Map())} disabled={busy}>
                Limpiar selección
              </button>
              <button type="button" className="btn-tesla danger sm" onClick={() => setConfirmando(true)} disabled={busy || confirmando}>
                Anular seleccionados
              </button>
            </>
          )}
        </div>
      </div>
      {confirmando && (
        <section className={styles.confirm} aria-label="Confirmar anulación">
          <p>{textoConfirmacion(seleccion.size - yaAnuladas, yaAnuladas)}</p>
          <p className={panelStyles.hint}>
            El sell out que acreditaron deja de contar: se borran sus consumos y se recalculan las ventas que alcanzaban.
            Si alguna no se puede anular, no se anula ninguna.
          </p>
          {demasiadas && <p className={panelStyles.hint}>{`Se pueden anular hasta ${ANULAR_MASIVO_MAX} campañas por vez.`}</p>}
          <label className={panelStyles.field} htmlFor={`${id}-motivo`}>
            <span className={panelStyles.label}>Motivo (opcional)</span>
            <textarea
              id={`${id}-motivo`}
              className={panelStyles.textarea}
              maxLength={MOTIVO_MAX}
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
            />
          </label>
          <div className={panelStyles.confirmActions}>
            <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmando(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="button" className="btn-tesla danger sm" onClick={anular} disabled={busy || demasiadas}>
              Confirmar anulación
            </button>
          </div>
        </section>
      )}
      {resultado && (
        <div className={`${styles.message} ${styles.ok}`} role="status">
          {resultado}
        </div>
      )}
      {error && (
        <div className={`${styles.message} ${styles.error}`} role="alert">
          <span>{error.mensaje}</span>
          {error.rechazadas.length > 0 && (
            <ul className={styles.list}>
              {error.rechazadas.map((r) => (
                <li key={r.id}>{r.motivo}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <SellOutCampanasTable
        campanas={campanas}
        selectedId={selectedId}
        onSelect={onSelect}
        seleccion={seleccion}
        onToggle={alternar}
        paginaSeleccionada={paginaSeleccionada}
        onTogglePagina={alternarPagina}
      />
    </>
  );
}
