import { useId, useState } from 'react';
import { AlertCircle, Info, X } from 'lucide-react';
import { sellOutProgramasAPI } from '../../services/sellOutAPI';
import { apiMessage } from '../sellIn/sellInFormat';
import panelStyles from '../sellIn/SellInPanel.module.css';
import { RESPALDOS_DE_FOCO } from './sellOutProgramas';
import { useFocoAtrapado } from './useFocoAtrapado';
import styles from './SellOutAsignarPrograma.module.css';

/** What an edit sends: only the fields that changed (`PATCH` changes only the fields sent). */
function cambios(programa, nombre, descripcion) {
  const body = {};
  if (nombre !== programa.nombre) body.nombre = nombre;
  if (descripcion !== (programa.descripcion ?? null)) body.descripcion = descripcion;
  return body;
}

/**
 * "Nuevo programa" (`POST /sell-out/programas`) or, with `programa`, "Editar programa" (`PATCH /{id}`, only the
 * fields that changed). The API's refusals (a taken name) show inline and the dialog stays open. `onGuardado(programa)`
 * gets the saved program; with nothing changed an edit just closes.
 */
export default function SellOutProgramaDialog({ programa, onClose, onGuardado }) {
  const id = useId();
  const foco = useFocoAtrapado(RESPALDOS_DE_FOCO);
  const [nombre, setNombre] = useState(programa?.nombre ?? '');
  const [descripcion, setDescripcion] = useState(programa?.descripcion ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nombreLimpio = nombre.trim();
  const titulo = programa ? 'Editar programa' : 'Nuevo programa';

  const guardar = async () => {
    const descripcionLimpia = descripcion.trim() || null;
    setBusy(true);
    setError(null);
    try {
      if (programa) {
        const body = cambios(programa, nombreLimpio, descripcionLimpia);
        if (Object.keys(body).length === 0) {
          onClose();
          return;
        }
        const { data } = await sellOutProgramasAPI.editar(programa.id, body);
        onGuardado({ ...programa, ...data, ...body });
      } else {
        const { data } = await sellOutProgramasAPI.crear({ nombre: nombreLimpio, descripcion: descripcionLimpia });
        onGuardado(data);
      }
    } catch (err) {
      setError(apiMessage(err, 'No se pudo guardar el programa.'));
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay-tesla">
      <div
        ref={foco.ref}
        onKeyDown={foco.onKeyDown}
        className="modal-tesla sm"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-titulo`}
      >
        <div className="modal-header-tesla">
          <h2 id={`${id}-titulo`} className="modal-title-tesla">
            {titulo}
          </h2>
          <button type="button" className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={busy}>
            <X size={14} />
          </button>
        </div>
        <div className="modal-body-tesla">
          <div className={styles.opcion}>
            <label className={styles.radio} htmlFor={`${id}-nombre`}>
              Nombre
            </label>
            <input
              id={`${id}-nombre`}
              className={panelStyles.input}
              maxLength={200}
              value={nombre}
              data-foco-inicial
              onChange={(e) => setNombre(e.target.value)}
            />
            <label className={styles.radio} htmlFor={`${id}-descripcion`}>
              Descripción (opcional)
            </label>
            <input
              id={`${id}-descripcion`}
              className={panelStyles.input}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
            />
            {error && (
              <p className={styles.error} role="alert">
                <AlertCircle size={14} aria-hidden="true" /> {error}
              </p>
            )}
          </div>
          <p className="modal-alert info">
            <Info size={14} aria-hidden="true" />
            {' Las campañas se suman desde Campañas, con «Asignar a programa» o con las sugerencias.'}
          </p>
        </div>
        <div className="modal-footer-tesla">
          <button type="button" className="btn-tesla outline sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button type="button" className="btn-tesla primary sm" onClick={guardar} disabled={busy || nombreLimpio === ''}>
            {programa ? 'Guardar' : 'Crear programa'}
          </button>
        </div>
      </div>
    </div>
  );
}
