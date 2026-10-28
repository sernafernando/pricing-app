import { useState, useEffect, useCallback } from 'react';
import { History, ArrowRight, Loader2 } from 'lucide-react';
import ModalTesla from '../ModalTesla';
import api from '../../services/api';
import styles from './HistorialLogisticaModal.module.css';

const ORIGEN_CLASS = {
  asignar: styles.origenAsignar,
  masivo: styles.origenMasivo,
  pistoleado: styles.origenPistoleado,
  manual: styles.origenManual,
  deshacer: styles.origenDeshacer,
};

const pad = (n) => String(n).padStart(2, '0');

// dd/mm HH:MM in the browser's local time.
const formatFecha = (isoString) => {
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

export default function HistorialLogisticaModal({ shippingId, onClose }) {
  const [historial, setHistorial] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [errorCarga, setErrorCarga] = useState(false);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const { data } = await api.get(`/etiquetas-envio/${shippingId}/logistica/historial`);
      setHistorial(data);
      setErrorCarga(false);
    } catch {
      setErrorCarga(true);
    } finally {
      setCargando(false);
    }
  }, [shippingId]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const cambios = historial?.cambios ?? [];
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
    <div className={styles.pie}>
      <button type="button" className={styles.btnSecundario} onClick={onClose}>
        Cerrar
      </button>
    </div>
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
                  <ArrowRight size={14} className={styles.flecha} aria-label="a" />
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
