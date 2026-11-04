import { useEffect, useId, useRef, useState } from 'react';
import { FolderInput, X, XCircle } from 'lucide-react';
import { sellOutAPI } from '../../services/sellOutAPI';
import { apiMessage } from '../sellIn/sellInFormat';
import SellOutAsignarPrograma from './SellOutAsignarPrograma';
import SellOutCampanasTable from './SellOutCampanasTable';
import { ANULAR_MASIVO_MAX, errorDeSeleccion, resolverFiltradas, textoConfirmacion, textoResultado } from './sellOutSeleccion';
import panelStyles from '../sellIn/SellInPanel.module.css';
import styles from './SellOutAnularMasivo.module.css';

const MOTIVO_MAX = 500; // backend `SellOutAnularMasivoIn.motivo` (auditoria.comentario is VARCHAR(500))

/**
 * The sell-out campaigns list with bulk void (`POST /sell-out/campanas/anular`, `sell_out.gestionar`): row and page
 * checkboxes, "Seleccionar todo lo filtrado" (fail-closed, `resolverFiltradas`), a confirmation and the result. All or
 * nothing on the server: a refusal voids nothing and names each refused campaign. Without `puedeGestionar` it is the
 * plain table. The parent keys it by the filters, so a new search starts a new selection; `onAnuladas(ids)` gets the
 * voided ids. With a selection, its actions float at the bottom of the window (Stitch 5ee03d7d): «N seleccionadas»,
 * "Asignar a programa", "Anular seleccionadas" and × ("Limpiar selección").
 *
 * The same selection (rows, or "todo lo filtrado") feeds "Asignar a programa" (`SellOutAsignarPrograma`, with
 * `programas`); `onAsignadas()` runs after an assignment. `renderTabla(props)` draws the rows instead of the flat
 * table (the "Por programa" view); it gets `seleccion`, `onToggle` and `onAsignar(ids)` (opens "Asignar a programa"
 * with those campaigns) only with `puedeGestionar`. `onRenovar` (the
 * page passes it with `sell_out.gestionar`) gives each row "Renovar".
 */
export default function SellOutAnularMasivo({
  campanas,
  total,
  filtros,
  puedeGestionar,
  selectedId,
  onSelect,
  onRenovar,
  onAnuladas,
  programas = [],
  onAsignadas,
  renderTabla,
}) {
  const id = useId();
  const [seleccion, setSeleccion] = useState(() => new Map()); // id → estado
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [busy, setBusy] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState(null); // { mensaje, rechazadas: [{ id, motivo }] }
  const [asignando, setAsignando] = useState(null); // the campaign ids the assign dialog gets
  const confirmacion = useRef(null);
  // The floating bar opens the confirmation above the list: bring it into view (the list may be scrolled down).
  useEffect(() => {
    if (confirmando) confirmacion.current?.scrollIntoView?.({ block: 'nearest' });
  }, [confirmando]);

  if (!puedeGestionar) {
    return renderTabla ? (
      renderTabla({ selectedId, onSelect, onRenovar })
    ) : (
      <SellOutCampanasTable campanas={campanas} selectedId={selectedId} onSelect={onSelect} onRenovar={onRenovar} />
    );
  }

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
      setError({ mensaje: errorDeSeleccion(err), rechazadas: [] });
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
      onAnuladas(data.anuladas);
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
        <button type="button" className="btn-tesla ghost sm" onClick={seleccionarFiltradas} disabled={busy}>
          {`Seleccionar todo lo filtrado (${total})`}
        </button>
      </div>
      {seleccion.size > 0 && (
        <aside className={styles.flotante} aria-label="Acciones masivas de campañas">
          <span className={styles.count}>
            <span className={styles.punto} aria-hidden="true" />
            {seleccion.size === 1 ? '1 seleccionada' : `${seleccion.size} seleccionadas`}
          </span>
          <button type="button" className={styles.accion} onClick={() => setAsignando([...seleccion.keys()])} disabled={busy}>
            <FolderInput size={15} aria-hidden="true" /> Asignar a programa
          </button>
          <button
            type="button"
            className="btn-tesla danger sm"
            onClick={() => setConfirmando(true)}
            disabled={busy || confirmando}
          >
            <XCircle size={15} aria-hidden="true" /> Anular seleccionadas
          </button>
          <button
            type="button"
            className={styles.cerrar}
            onClick={() => cambiar(new Map())}
            disabled={busy}
            aria-label="Limpiar selección"
            title="Limpiar selección"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </aside>
      )}
      {confirmando && (
        <section ref={confirmacion} className={styles.confirm} aria-label="Confirmar anulación">
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
      {asignando && (
        <SellOutAsignarPrograma
          campanaIds={asignando}
          programas={programas}
          onClose={() => setAsignando(null)}
          onProgramaCreado={() => onAsignadas?.()}
          onAsignadas={(texto) => {
            setAsignando(null);
            cambiar(new Map());
            setResultado(texto);
            onAsignadas?.();
          }}
        />
      )}
      {renderTabla ? (
        renderTabla({ selectedId, onSelect, onRenovar, seleccion, onToggle: alternar, onAsignar: setAsignando })
      ) : (
        <SellOutCampanasTable
          campanas={campanas}
          selectedId={selectedId}
          onSelect={onSelect}
          onRenovar={onRenovar}
          seleccion={seleccion}
          onToggle={alternar}
          paginaSeleccionada={paginaSeleccionada}
          onTogglePagina={alternarPagina}
        />
      )}
    </>
  );
}
