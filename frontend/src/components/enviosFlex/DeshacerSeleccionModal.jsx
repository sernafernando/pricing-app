import { useState } from 'react';
import { Undo2, Loader2 } from 'lucide-react';
import ModalTesla from '../ModalTesla';
import api from '../../services/api';
import ResultadoDeshacerMasivo from './ResultadoDeshacerMasivo';
import { plural } from './plural';
import styles from './DeshacerMasivo.module.css';

// Undo the last logistics change of every selected label (same rule as the single undo of the history modal).
export default function DeshacerSeleccionModal({ shippingIds, operadorId = null, onClose, onListo }) {
  const [deshaciendo, setDeshaciendo] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState(null);

  const cantidad = plural(shippingIds.length, 'etiqueta', 'etiquetas');

  const deshacer = async () => {
    setDeshaciendo(true);
    setError(null);
    try {
      const { data } = await api.post('/etiquetas-envio/deshacer-logistica-masivo', {
        shipping_ids: shippingIds,
        operador_id: operadorId,
      });
      setResultado(data);
      onListo?.(data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'No se pudieron deshacer los cambios.');
    } finally {
      setDeshaciendo(false);
    }
  };

  const title = (
    <span className={styles.titulo}>
      <span className={styles.tituloIcono} aria-hidden="true">
        <Undo2 size={18} />
      </span>
      <span>Deshacer último cambio de logística</span>
    </span>
  );

  const footer = (
    <div className={styles.acciones}>
      <button type="button" className={styles.btnSecundario} onClick={onClose} disabled={deshaciendo}>
        {resultado ? 'Cerrar' : 'Cancelar'}
      </button>
      {!resultado && (
        <button type="button" className={styles.btnPrimario} onClick={deshacer} disabled={deshaciendo}>
          {deshaciendo ? <Loader2 size={14} className={styles.spin} /> : <Undo2 size={14} />}
          Deshacer {cantidad}
        </button>
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
        <ResultadoDeshacerMasivo resultado={resultado} />
      ) : (
        <>
          <p className={styles.texto}>
            {shippingIds.length === 1
              ? 'La etiqueta seleccionada vuelve'
              : `Cada una de las ${cantidad} seleccionadas vuelve`}{' '}
            a la logística que tenía antes de su último cambio.
          </p>
          <p className={styles.textoSecundario}>
            Las que no se pueden deshacer (sin cambios, cambiadas sin registro o con la logística anterior inactiva)
            se saltean y se informan.
          </p>
        </>
      )}
    </ModalTesla>
  );
}
