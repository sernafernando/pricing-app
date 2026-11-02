import { useId, useState } from 'react';
import { AlertCircle, Info, X } from 'lucide-react';
import { sellOutProgramasAPI } from '../../services/sellOutAPI';
import { apiMessage } from '../sellIn/sellInFormat';
import panelStyles from '../sellIn/SellInPanel.module.css';
import { plural, textoAsignadas } from './sellOutProgramas';
import { ASIGNAR_MAX } from './sellOutSeleccion';
import { useFocoAtrapado } from './useFocoAtrapado';
import styles from './SellOutAsignarPrograma.module.css';

/**
 * "Asignar a programa (N campañas)" (Stitch programas/modal): to an active program, or to a new one it creates first
 * (`POST /sell-out/programas`, then `POST /asignar`). The API's refusals (an archived program, a duplicate name,
 * unknown campaigns) show inline and the dialog stays open. Above `ASIGNAR_MAX` campaigns «Asignar» is disabled. Closes only with X or "Cancelar". `onProgramaCreado()` runs right after a create. `onAsignadas(texto)`
 * gets the result line. The focus stays inside while it is open and goes back to the button that opened it
 * (`useFocoAtrapado`).
 */
export default function SellOutAsignarPrograma({ campanaIds, programas, onClose, onAsignadas, onProgramaCreado }) {
  const id = useId();
  const foco = useFocoAtrapado();
  const activos = programas.filter((p) => p.estado === 'activo');
  const [modo, setModo] = useState(activos.length > 0 ? 'existente' : 'nuevo');
  const [programaId, setProgramaId] = useState('');
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [creado, setCreado] = useState(null); // a program created on a try whose assignment then failed
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nombreLimpio = nombre.trim();
  // Checked before anything is sent, so a new program is never created for an assignment the API would refuse.
  const demasiadas = campanaIds.length > ASIGNAR_MAX;
  const listo = !demasiadas && (modo === 'existente' ? programaId !== '' : nombreLimpio !== '');

  const asignar = async () => {
    setBusy(true);
    setError(null);
    try {
      let destino;
      if (modo === 'existente') {
        destino = activos.find((p) => String(p.id) === programaId);
      } else if (creado && creado.nombre === nombreLimpio) {
        destino = creado;
      } else {
        const { data } = await sellOutProgramasAPI.crear({ nombre: nombreLimpio, descripcion: descripcion.trim() || null });
        destino = data;
        setCreado(data);
        onProgramaCreado?.(); // the page's filter and this select see it, whatever the assignment does
      }
      const { data } = await sellOutProgramasAPI.asignar(campanaIds, destino.id);
      onAsignadas(textoAsignadas(data, destino.nombre));
    } catch (err) {
      setError(apiMessage(err, 'No se pudo asignar el programa.'));
      setBusy(false);
    }
  };

  const errorEn = (enModo) =>
    error &&
    modo === enModo && (
      <p className={styles.error} role="alert">
        <AlertCircle size={14} aria-hidden="true" /> {error}
      </p>
    );
  const titulo = `Asignar a programa (${plural(campanaIds.length, 'campaña', 'campañas')})`;

  return (
    <div className="modal-overlay-tesla">
      <div ref={foco.ref} onKeyDown={foco.onKeyDown} className="modal-tesla sm" role="dialog" aria-modal="true" aria-labelledby={`${id}-titulo`}>
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
            <label className={styles.radio}>
              <input
                type="radio"
                name={`${id}-modo`}
                checked={modo === 'existente'}
                data-foco-inicial={modo === 'existente' || undefined}
                onChange={() => setModo('existente')}
                disabled={activos.length === 0}
              />
              Programa existente
            </label>
            <label className={styles.srOnly} htmlFor={`${id}-programa`}>
              Programa
            </label>
            <select
              id={`${id}-programa`}
              className={panelStyles.select}
              value={programaId}
              onChange={(e) => setProgramaId(e.target.value)}
              disabled={modo !== 'existente'}
            >
              <option value="">Elegí un programa</option>
              {activos.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.nombre}
                </option>
              ))}
            </select>
            {errorEn('existente')}
          </div>
          <div className={styles.opcion}>
            <label className={styles.radio}>
              <input
                type="radio"
                name={`${id}-modo`}
                checked={modo === 'nuevo'}
                data-foco-inicial={modo === 'nuevo' || undefined}
                onChange={() => setModo('nuevo')}
              />
              Programa nuevo
            </label>
            <label className={styles.srOnly} htmlFor={`${id}-nombre`}>
              Nombre
            </label>
            <input
              id={`${id}-nombre`}
              className={panelStyles.input}
              placeholder="Nombre"
              maxLength={200}
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              disabled={modo !== 'nuevo'}
            />
            <label className={styles.srOnly} htmlFor={`${id}-descripcion`}>
              Descripción (opcional)
            </label>
            <input
              id={`${id}-descripcion`}
              className={panelStyles.input}
              placeholder="Descripción (opcional)"
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              disabled={modo !== 'nuevo'}
            />
            {errorEn('nuevo')}
          </div>
          {demasiadas && (
            <p className="modal-alert warning" role="alert">{`Se pueden asignar hasta ${ASIGNAR_MAX} campañas por vez.`}</p>
          )}
          <p className="modal-alert info">
            <Info size={14} aria-hidden="true" /> Asignar un programa no cambia la plata de las campañas: solo las agrupa.
          </p>
        </div>
        <div className="modal-footer-tesla">
          <button type="button" className="btn-tesla outline sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button type="button" className="btn-tesla primary sm" onClick={asignar} disabled={busy || !listo}>
            Asignar
          </button>
        </div>
      </div>
    </div>
  );
}
