import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import ModalTesla from '../ModalTesla';
import api from '../../services/api';
import { LogisticaChip } from './ResultadoDeshacerMasivo';
import { plural } from './plural';
import styles from './DeshacerMasivo.module.css';

// Overwrite guard of the bulk assignment: some selected labels already have another logistics
// ('A designar' and empty count as without). Overwrite them all, or change only the ones without.
export default function SobrescribirLogisticaModal({ shippingIds, logistica, sobrescribiria, onClose, onAsignado }) {
  const [asignando, setAsignando] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState(null);

  const asignar = async (soloSinLogistica) => {
    setAsignando(soloSinLogistica ? 'solo' : 'todas');
    setError(null);
    try {
      const { data } = await api.put('/etiquetas-envio/asignar-masivo', {
        shipping_ids: shippingIds,
        logistica_id: logistica.id,
        solo_sin_logistica: soloSinLogistica,
      });
      if (soloSinLogistica) setResultado(data);
      onAsignado?.(data, { soloSinLogistica });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'No se pudo asignar la logística.');
    } finally {
      setAsignando(null);
    }
  };

  const title = (
    <span className={styles.titulo}>
      <span className={styles.tituloIconoAviso} aria-hidden="true">
        <AlertTriangle size={18} />
      </span>
      <span>Etiquetas con otra logística</span>
    </span>
  );

  const footer = (
    <div className={styles.acciones}>
      <button type="button" className={styles.btnSecundario} onClick={onClose} disabled={Boolean(asignando)}>
        {resultado ? 'Cerrar' : 'Cancelar'}
      </button>
      {!resultado && (
        <>
          <button
            type="button"
            className={styles.btnAviso}
            onClick={() => asignar(false)}
            disabled={Boolean(asignando)}
          >
            {asignando === 'todas' && <Loader2 size={14} className={styles.spin} />}
            Sobrescribir todas
          </button>
          <button
            type="button"
            className={styles.btnPrimario}
            onClick={() => asignar(true)}
            disabled={Boolean(asignando)}
          >
            {asignando === 'solo' && <Loader2 size={14} className={styles.spin} />}
            Solo las sin logística
          </button>
        </>
      )}
    </div>
  );

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      closeOnOverlay={false}
      closeOnEsc={false}
      title={title}
      footer={footer}
      size="md"
      className={styles.modal}
      bodyClassName={styles.cuerpo}
    >
      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
      {resultado ? (
        <div className={styles.resultado} role="status">
          <div className={styles.resumenOk}>
            <CheckCircle2 size={16} aria-hidden="true" />
            {resultado.actualizadas === 1
              ? `1 etiqueta pasó a ${logistica.nombre}.`
              : `${resultado.actualizadas} etiquetas pasaron a ${logistica.nombre}.`}
          </div>
          {resultado.salteadas > 0 && (
            <div className={styles.resumenAviso}>
              <AlertTriangle size={16} aria-hidden="true" />
              {resultado.salteadas === 1
                ? '1 se salteó porque ya tenía otra logística.'
                : `${resultado.salteadas} se saltearon porque ya tenían otra logística.`}
            </div>
          )}
        </div>
      ) : (
        <>
          <p className={styles.texto}>
            {sobrescribiria} de las {plural(shippingIds.length, 'etiqueta', 'etiquetas')} ya{' '}
            {sobrescribiria === 1 ? 'tiene' : 'tienen'} otra logística. ¿Asignar{' '}
            <LogisticaChip logistica={logistica} /> igual?
          </p>
          <p className={styles.textoSecundario}>
            «Solo las sin logística» cambia las vacías y las que están en «A designar»; las demás quedan como están.
          </p>
        </>
      )}
    </ModalTesla>
  );
}
