import { useEffect, useId, useState } from 'react';
import { AlertCircle, ChevronDown, ChevronRight, Info, Sparkles, X } from 'lucide-react';
import { StatusPill } from '../kit';
import { sellOutProgramasAPI } from '../../services/sellOutAPI';
import { apiMessage } from '../sellIn/sellInFormat';
import { claveSugerencia, fechasDe, nombreNormalizado, plural, textoActivas, textoAsignadas } from './sellOutProgramas';
import styles from './SellOutSugerencias.module.css';

/** Suggestions per request: the endpoint's maximum (`page_size` le=200). */
const SUGERENCIAS_PAGE_SIZE = 200;

/** The suggestion's campaigns by name (ignoring case and spaces) and state, in the first spelling, with how many. */
function porNombre(campanas) {
  const grupos = new Map();
  campanas.forEach((c) => {
    const clave = `${nombreNormalizado(c.nombre)}|${c.estado}`;
    const grupo = grupos.get(clave) ?? { nombre: c.nombre, estado: c.estado, cuantas: 0 };
    grupo.cuantas += 1;
    grupos.set(clave, grupo);
  });
  return [...grupos.values()];
}

function Tarjeta({ sugerencia, onDescartar, onCreado }) {
  const id = useId();
  const [nombre, setNombre] = useState(sugerencia.base);
  const [abierta, setAbierta] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const activas = sugerencia.campanas.filter((c) => c.estado === 'activa').length;
  const fechas = fechasDe(sugerencia.fecha_desde, sugerencia.fecha_hasta);
  const Chevron = abierta ? ChevronDown : ChevronRight;

  const crear = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data: programa } = await sellOutProgramasAPI.crear({ nombre: nombre.trim() });
      const { data } = await sellOutProgramasAPI.asignar(
        sugerencia.campanas.map((c) => c.id),
        programa.id,
      );
      onCreado(textoAsignadas(data, programa.nombre));
    } catch (err) {
      setError(apiMessage(err, 'No se pudo crear el programa.'));
      setBusy(false);
    }
  };

  return (
    <section className={styles.tarjeta} role="group" aria-label={`Sugerencia del ${fechas.replace(' – ', ' al ')}`}>
      <div className={styles.encabezado}>
        <input
          className={styles.nombre}
          aria-label="Nombre del programa"
          maxLength={200}
          value={nombre}
          onChange={(e) => setNombre(e.target.value)}
          disabled={busy}
        />
        {activas > 0 && <StatusPill tone="success">{textoActivas(activas)}</StatusPill>}
      </div>
      <p className={styles.meta}>
        {`${fechas} · ${plural(sugerencia.campanas.length, 'campaña', 'campañas')} · ${plural(sugerencia.nombres, 'nombre', 'nombres')}`}
      </p>
      <button
        type="button"
        className={styles.alternar}
        aria-expanded={abierta}
        aria-controls={`${id}-campanas`}
        onClick={() => setAbierta((a) => !a)}
      >
        <Chevron size={14} aria-hidden="true" /> Ver campañas
      </button>
      {abierta && (
        <ul id={`${id}-campanas`} className={styles.campanas}>
          {porNombre(sugerencia.campanas).map((g) => (
            <li key={`${g.nombre}|${g.estado}`}>
              <span>{g.cuantas > 1 ? `${g.nombre} (×${g.cuantas})` : g.nombre}</span>
              <StatusPill tone={g.estado === 'activa' ? 'success' : 'danger'}>{g.estado === 'activa' ? 'Activa' : 'Anulada'}</StatusPill>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className={styles.error} role="alert">
          <AlertCircle size={14} aria-hidden="true" /> {error}
        </p>
      )}
      <div className={styles.acciones}>
        <button type="button" className="btn-tesla outline sm" onClick={onDescartar} disabled={busy}>
          Descartar
        </button>
        <button type="button" className="btn-tesla primary sm" onClick={crear} disabled={busy || nombre.trim() === ''}>
          Crear programa y asignar
        </button>
      </div>
    </section>
  );
}

/**
 * "Sugerencias de programa" (Stitch programas/drawer), only with `sell_out.gestionar` (the parent renders it only
 * then): the banner «N sugerencias de programa: …» when there are any, and the drawer with one card per suggestion
 * (`GET /sell-out/programas/sugerencias`, campaigns without a program sharing their exact dates). A card's name
 * starts as the API's `base`, editable; "Crear programa y asignar" creates it and assigns the card's campaigns
 * (a 409 duplicate name shows on the card), then `onCambio()` refreshes the list, the groups and, through `version`,
 * the suggestions. "Descartar" hides a card for this session (`descartadas`, kept by the page; nothing is stored).
 */
export default function SellOutSugerencias({ version, descartadas, onDescartar, onCambio }) {
  const tituloId = useId();
  const [sugerencias, setSugerencias] = useState([]);
  const [abierto, setAbierto] = useState(false);
  const [aviso, setAviso] = useState(null);
  useEffect(() => {
    let activo = true;
    sellOutProgramasAPI
      .sugerencias({ page: 1, page_size: SUGERENCIAS_PAGE_SIZE })
      .then(({ data }) => activo && setSugerencias(data?.items ?? []))
      .catch(() => activo && setSugerencias([]));
    return () => {
      activo = false;
    };
  }, [version]);

  const visibles = sugerencias.filter((s) => !descartadas.has(claveSugerencia(s)));
  return (
    <>
      {visibles.length > 0 && (
        <div className={styles.banner}>
          <Info size={16} aria-hidden="true" />
          <span>{`${plural(visibles.length, 'sugerencia', 'sugerencias')} de programa: campañas sin programa con las mismas fechas`}</span>
          <button type="button" className="btn-tesla primary sm" onClick={() => setAbierto(true)}>
            Ver sugerencias
          </button>
        </div>
      )}
      {abierto && (
        <div className={`modal-overlay-tesla ${styles.fondo}`}>
          <aside className={styles.drawer} role="dialog" aria-modal="true" aria-labelledby={tituloId}>
            <header className={styles.cabecera}>
              <Sparkles size={18} aria-hidden="true" />
              <h2 id={tituloId}>Sugerencias de programa</h2>
              <button
                type="button"
                className="btn-close-tesla"
                onClick={() => {
                  setAbierto(false);
                  setAviso(null);
                }}
                aria-label="Cerrar sugerencias"
              >
                <X size={14} />
              </button>
            </header>
            <div className={styles.cuerpo}>
              {aviso && (
                <div className={styles.ok} role="status">
                  {aviso}
                </div>
              )}
              {visibles.length === 0 && <p className={styles.vacio}>No quedan sugerencias.</p>}
              {visibles.map((s) => (
                <Tarjeta
                  key={claveSugerencia(s)}
                  sugerencia={s}
                  onDescartar={() => onDescartar(claveSugerencia(s))}
                  onCreado={(texto) => {
                    setAviso(texto);
                    onCambio();
                  }}
                />
              ))}
              <p className={styles.nota}>
                Las sugerencias agrupan campañas sin programa con exactamente las mismas fechas. No se aplica nada hasta que lo
                confirmes.
              </p>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
