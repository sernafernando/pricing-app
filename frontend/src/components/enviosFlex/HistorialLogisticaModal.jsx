import { useState, useEffect } from 'react';
import { History, ArrowRight, Undo2, Check, CircleHelp, Info, Loader2 } from 'lucide-react';
import ModalTesla from '../ModalTesla';
import api from '../../services/api';
import styles from './HistorialLogisticaModal.module.css';

const ORIGEN_CLASS = {
  asignar: styles.origenAsignar,
  masivo: styles.origenMasivo,
  pistoleado: styles.origenPistoleado,
  deshacer: styles.origenDeshacer,
};

const pad = (n) => String(n).padStart(2, '0');

// dd/mm HH:MM in the browser's local time.
const formatFecha = (isoString) => {
  if (!isoString) return '—';
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return '—';
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const nombreLogistica = (logistica) => logistica?.nombre || 'Sin asignar';

// Neutral chip with a dot in the logística's own color (gray when unassigned).
function LogisticaChip({ logistica }) {
  return (
    <span className={styles.chip}>
      <span
        className={`${styles.dot} ${logistica ? '' : styles.dotSinAsignar}`}
        style={logistica?.color ? { background: logistica.color } : undefined}
        aria-hidden="true"
      />
      {nombreLogistica(logistica)}
    </span>
  );
}

const autorDe = (cambio) => {
  const partes = [];
  if (cambio.usuario_nombre) partes.push(cambio.usuario_nombre);
  if (cambio.operador_nombre) partes.push(`Op. ${cambio.operador_nombre}`);
  return partes.length ? partes.join(' · ') : '—';
};

export default function HistorialLogisticaModal({
  shippingId,
  puedeDeshacer = false,
  operadorId = null,
  onClose,
  onDeshecho,
}) {
  const [historial, setHistorial] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [errorCarga, setErrorCarga] = useState(false);
  // Bumped to reload the history after an undo attempt.
  const [recarga, setRecarga] = useState(0);
  const [confirmando, setConfirmando] = useState(false);
  const [deshaciendo, setDeshaciendo] = useState(false);
  const [errorDeshacer, setErrorDeshacer] = useState(null);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    api
      .get(`/etiquetas-envio/${shippingId}/logistica/historial`)
      .then(({ data }) => {
        if (!vigente) return;
        setHistorial(data);
        setErrorCarga(false);
      })
      .catch(() => {
        if (vigente) setErrorCarga(true);
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [shippingId, recarga]);

  const confirmarDeshacer = async () => {
    setDeshaciendo(true);
    setErrorDeshacer(null);
    try {
      const { data } = await api.post(`/etiquetas-envio/${shippingId}/logistica/deshacer`, {
        operador_id: operadorId,
      });
      onDeshecho?.({ logistica_id: data.logistica_id });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setErrorDeshacer(typeof detail === 'string' ? detail : 'No se pudo deshacer el cambio.');
    } finally {
      // Either way, show the current history: the label may have changed under us.
      setConfirmando(false);
      setDeshaciendo(false);
      setRecarga((n) => n + 1);
    }
  };

  const cambios = historial?.cambios ?? [];
  const sePuedeDeshacer = Boolean(historial?.puede_deshacer);
  let motivoDeshabilitado;
  if (historial && !sePuedeDeshacer) {
    motivoDeshabilitado = cambios.length === 0
      ? 'No hay un cambio para deshacer'
      : 'El último cambio no se puede deshacer';
  }

  const title = (
    <span className={styles.titulo}>
      <span className={styles.tituloIcono} aria-hidden="true">
        <History size={18} />
      </span>
      <span>Historial de logística</span>
      <span className={styles.envioChip}>Envío {shippingId}</span>
    </span>
  );

  const subtitle = historial ? (
    <span className={styles.actual}>
      <span>Logística actual:</span>
      <LogisticaChip logistica={historial.logistica_actual} />
    </span>
  ) : null;

  const footer = (
    <>
      {confirmando && historial && (
        <div className={styles.confirmar} role="group" aria-label="Confirmar deshacer">
          <CircleHelp size={18} className={styles.confirmarIcono} aria-hidden="true" />
          <span className={styles.confirmarTexto}>
            ¿Volver a <LogisticaChip logistica={historial.deshacer_a} />? La etiqueta deja{' '}
            {nombreLogistica(historial.logistica_actual)}.
          </span>
          <div className={styles.confirmarAcciones}>
            <button
              type="button"
              className={styles.btnSecundario}
              onClick={() => setConfirmando(false)}
              disabled={deshaciendo}
            >
              Cancelar
            </button>
            <button
              type="button"
              className={styles.btnConfirmar}
              onClick={confirmarDeshacer}
              disabled={deshaciendo}
            >
              {deshaciendo ? <Loader2 size={14} className={styles.spin} /> : <Check size={14} />}
              Confirmar
            </button>
          </div>
        </div>
      )}
      <div className={styles.pie}>
        {puedeDeshacer && historial && (
          <span className={styles.pista}>
            <Info size={14} aria-hidden="true" />
            {motivoDeshabilitado ?? 'Deshacer vuelve a la logística anterior al último cambio.'}
          </span>
        )}
        <div className={styles.pieAcciones}>
          <button type="button" className={styles.btnSecundario} onClick={onClose}>
            Cerrar
          </button>
          {puedeDeshacer && (
            <button
              type="button"
              className={styles.btnPrimario}
              onClick={() => {
                setErrorDeshacer(null);
                setConfirmando(true);
              }}
              disabled={!sePuedeDeshacer || cargando || deshaciendo || confirmando}
              title={motivoDeshabilitado}
            >
              <Undo2 size={16} />
              Deshacer último cambio
            </button>
          )}
        </div>
      </div>
    </>
  );

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title={title}
      subtitle={subtitle}
      footer={footer}
      size="lg"
      className={styles.modal}
      bodyClassName={styles.cuerpo}
    >
      {errorDeshacer && (
        <div className={styles.error} role="alert">
          {errorDeshacer}
        </div>
      )}

      {cargando && !historial && (
        <div className={styles.estado}>
          <Loader2 size={16} className={styles.spin} /> Cargando historial…
        </div>
      )}

      {errorCarga && !historial && (
        <div className={styles.error} role="alert">
          No se pudo cargar el historial de logística.
        </div>
      )}

      {historial && cambios.length === 0 && (
        <div className={styles.estado}>Sin cambios de logística registrados.</div>
      )}

      {cambios.length > 0 && (
        <>
          <div className={styles.encabezado}>
            <span>Fecha / hora y cambio</span>
            <span>Origen y autor</span>
          </div>
          <ul className={styles.lista}>
            {cambios.map((cambio) => (
              <li key={cambio.id} className={styles.fila}>
                <span className={styles.fecha}>{formatFecha(cambio.cambiado_en)}</span>
                <span className={styles.transicion}>
                  <LogisticaChip logistica={cambio.anterior} />
                  <ArrowRight size={14} className={styles.flecha} aria-hidden="true" />
                  <LogisticaChip logistica={cambio.nueva} />
                  {cambio.origen && (
                    <span className={`${styles.origen} ${ORIGEN_CLASS[cambio.origen] || ''}`}>
                      {cambio.origen.toUpperCase()}
                    </span>
                  )}
                </span>
                <span className={styles.autor}>{autorDe(cambio)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </ModalTesla>
  );
}
