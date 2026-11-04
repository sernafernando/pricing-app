import { useCallback, useEffect, useId, useState } from 'react';
import { AlertCircle, AlertTriangle, ArrowRight, Ban, CalendarDays, Copy, Info, RefreshCw, X } from 'lucide-react';
import { StatusPill } from '../kit';
import { sellOutProgramasAPI } from '../../services/sellOutAPI';
import { apiMessage } from '../sellIn/sellInFormat';
import { RESPALDOS_DE_FOCO, fechasDe, plural, textoRenovado, trimestreDe } from './sellOutProgramas';
import { useFocoAtrapado } from './useFocoAtrapado';
import styles from './SellOutRenovarPrograma.module.css';

const ANULADA = 'anulada, no se renueva'; // `renovacion_programa.ANULADA`

function Periodo({ titulo, desde, hasta, destino = false }) {
  const Icono = destino ? RefreshCw : CalendarDays;
  return (
    <div className={destino ? `${styles.periodo} ${styles.destino}` : styles.periodo}>
      <Icono size={16} aria-hidden="true" />
      <div>
        <div className={styles.periodoTitulo}>{titulo}</div>
        <div className={styles.mono}>{fechasDe(desde, hasta)}</div>
      </div>
    </div>
  );
}

/**
 * "Renovar programa «nombre»" (Stitch 26104b54, owner-approved without the "LOTE" badge and with the SOURCE
 * campaign's id): reads the preview (`GET /sell-out/programas/{id}/renovacion`) and shows the source period → the
 * target quarter, "Se crearán N" (current name → new name, the target dates and the source id), "Se omiten N" (voided
 * or already renewed, with why), and the campaigns of the other quarter left for a later pass. "Renovar N campañas"
 * creates them all or none (`POST /renovar` with the previewed ids). A 409 (the preview changed meanwhile) shows why
 * and reads the preview again; any other refusal shows inline and the dialog stays open. `onRenovado(texto)` gets the
 * result line. The focus stays inside while it is open (`useFocoAtrapado`).
 */
export default function SellOutRenovarPrograma({ programa, onClose, onRenovado }) {
  const id = useId();
  const foco = useFocoAtrapado(RESPALDOS_DE_FOCO);
  const [previa, setPrevia] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const leer = useCallback(() => {
    let activo = true;
    sellOutProgramasAPI
      .renovacion(programa.id)
      .then(({ data }) => activo && setPrevia(data))
      .catch((err) => activo && setError(apiMessage(err, 'No se pudo leer la renovación del programa.')));
    return () => {
      activo = false;
    };
  }, [programa.id]);
  useEffect(leer, [leer]);

  const renovar = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellOutProgramasAPI.renovar(
        programa.id,
        previa.renovar.map((r) => r.campana_id),
      );
      onRenovado(textoRenovado(data.creadas.length, previa.programa, previa.fecha_desde));
    } catch (err) {
      setError(apiMessage(err, 'No se pudo renovar el programa.'));
      if (err?.response?.status === 409) leer();
      setBusy(false);
    }
  };

  const cantidad = previa?.renovar.length ?? 0;
  const afuera = previa?.quedan_afuera ?? [];

  return (
    <div className="modal-overlay-tesla">
      <div
        ref={foco.ref}
        onKeyDown={foco.onKeyDown}
        className="modal-tesla md"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-titulo`}
      >
        <div className="modal-header-tesla">
          <div className={styles.cabecera}>
            <span className={styles.icono} aria-hidden="true">
              <RefreshCw size={18} />
            </span>
            <div>
              <h2 id={`${id}-titulo`} className="modal-title-tesla">
                {`Renovar programa «${programa.nombre}»`}
              </h2>
              {previa?.fecha_desde && (
                <p className={styles.subtitulo}>
                  {`Renueva las campañas de ${trimestreDe(previa.periodo_desde)} al trimestre ${trimestreDe(previa.fecha_desde)} (${fechasDe(previa.fecha_desde, previa.fecha_hasta)}).`}
                </p>
              )}
            </div>
          </div>
          <button type="button" className="btn-close-tesla" onClick={onClose} aria-label="Cerrar" disabled={busy}>
            <X size={14} />
          </button>
        </div>
        <div className="modal-body-tesla">
          {error && (
            <p className={styles.error} role="alert">
              <AlertCircle size={14} aria-hidden="true" /> {error}
            </p>
          )}
          {!previa && !error && <p className={styles.vacio}>Leyendo la renovación…</p>}
          {previa?.fecha_desde && (
            <div className={styles.periodos} role="group" aria-label="Períodos">
              <Periodo titulo={trimestreDe(previa.periodo_desde)} desde={previa.periodo_desde} hasta={previa.periodo_hasta} />
              <ArrowRight size={18} aria-hidden="true" className={styles.flecha} />
              <Periodo titulo={trimestreDe(previa.fecha_desde)} desde={previa.fecha_desde} hasta={previa.fecha_hasta} destino />
            </div>
          )}
          {previa && cantidad === 0 && <p className={styles.vacio}>No hay campañas para renovar en este programa.</p>}
          {cantidad > 0 && (
            <section className={styles.seccion}>
              <h3 id={`${id}-crear`} className={styles.seccionTitulo}>
                Se crearán <span className={styles.cuenta}>{cantidad}</span>
              </h3>
              <ul className={styles.lista} aria-labelledby={`${id}-crear`}>
                {previa.renovar.map((r) => (
                  <li key={r.campana_id} className={styles.fila}>
                    <span className={styles.secundario}>{r.nombre}</span>
                    <ArrowRight size={14} aria-hidden="true" className={styles.flecha} />
                    <strong>{r.nombre_nuevo}</strong>
                    <span className={styles.mono}>{`· ${fechasDe(previa.fecha_desde, previa.fecha_hasta)}`}</span>
                    <span className={styles.idChip}>{`ID #${r.campana_id}`}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {previa?.omitidas.length > 0 && (
            <section className={styles.seccion}>
              <h3 id={`${id}-omitidas`} className={styles.seccionTitulo}>
                Se omiten <span className={`${styles.cuenta} ${styles.cuentaNeutra}`}>{previa.omitidas.length}</span>
              </h3>
              <ul className={`${styles.lista} ${styles.omitidas}`} aria-labelledby={`${id}-omitidas`}>
                {previa.omitidas.map((o) => {
                  const anulada = o.motivo === ANULADA;
                  const Icono = anulada ? Ban : Copy;
                  return (
                    <li key={o.campana_id} className={styles.fila}>
                      <Icono size={15} aria-hidden="true" className={anulada ? styles.iconoAnulada : styles.secundario} />
                      <span className={`${styles.secundario} ${styles.motivo}`}>{`${o.nombre} — ${o.motivo}`}</span>
                      <span className={styles.badge}>
                        <StatusPill tone={anulada ? 'danger' : 'neutral'}>{anulada ? 'Campaña anulada' : 'Copia existente'}</StatusPill>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
          {afuera.length > 0 && (
            <p className={styles.afuera}>
              <AlertTriangle size={16} aria-hidden="true" />
              <span>
                {`Quedan afuera de esta renovación ${plural(afuera.length, 'campaña activa', 'campañas activas')} sin renovar de ${trimestreDe(afuera[0].fecha_hasta)}: `}
                <strong>{afuera.map((a) => a.nombre).join(', ')}</strong>
                {'. Se renuevan en una próxima pasada.'}
              </span>
            </p>
          )}
          {cantidad > 0 && (
            <p className={styles.nota}>
              <Info size={14} aria-hidden="true" />
              Se crea todo o nada. Cada campaña nueva queda en el mismo programa y se puede editar después.
            </p>
          )}
        </div>
        <div className={`modal-footer-tesla ${styles.pie}`}>
          {cantidad > 0 && (
            <span className={styles.listas}>
              <span className={styles.punto} aria-hidden="true" />
              {`${plural(cantidad, 'campaña lista', 'campañas listas')} para renovar`}
            </span>
          )}
          <button type="button" className="btn-tesla outline sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button
            type="button"
            className="btn-tesla primary sm"
            onClick={renovar}
            disabled={busy || cantidad === 0}
          >
            <RefreshCw size={14} aria-hidden="true" /> {cantidad > 0 ? `Renovar ${plural(cantidad, 'campaña', 'campañas')}` : 'Renovar'}
          </button>
        </div>
      </div>
    </div>
  );
}
