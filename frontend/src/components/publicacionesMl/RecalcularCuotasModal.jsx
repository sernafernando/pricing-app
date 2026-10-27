import { useState } from 'react';
import api from '../../services/api';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import ModalTesla, { ModalFooterButtons } from '../ModalTesla';
import styles from './RecalcularCuotasModal.module.css';

const LISTAS = { web: 'Web', pvp: 'PVP' };
const plural = (n, one, many) => (n === 1 ? one : many);

/**
 * Productos' "Recalcular Cuotas Web/PVP" over Publicaciones ML's product set: `recalcular-cuotas-masivo` with an
 * explicit `item_ids` set. It recomputes the 3/6/9/12 cuotas from each product's stored base price and never
 * changes that price. Asks for an in-app confirmation first; a failed run keeps the dialog open with the reason.
 */
export default function RecalcularCuotasModal({ listaTipo, itemIds, itemIdsNota, onClose, onSuccess, showToast }) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const lista = LISTAS[listaTipo];
  const n = itemIds.length;

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const { data } = await api.post('/productos/recalcular-cuotas-masivo', { lista_tipo: listaTipo, item_ids: itemIds });
      const errores = data.errores > 0 ? ` (${data.errores} con errores)` : '';
      showToast(
        `Cuotas ${listaTipo.toUpperCase()} recalculadas: ${data.procesados} ${plural(data.procesados, 'producto', 'productos')}${errores}`,
        data.errores > 0 ? 'warning' : 'success',
      );
      onSuccess?.();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudieron recalcular las cuotas'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <ModalTesla
      isOpen
      onClose={running ? () => {} : onClose}
      title={`Recalcular cuotas ${lista}`}
      size="sm"
      footer={
        <ModalFooterButtons onCancel={onClose} onConfirm={run} confirmText="Confirmar" confirmLoading={running} />
      }
    >
      <p className={styles.message}>
        Recalcula las cuotas 3, 6, 9 y 12 de {n} {plural(n, 'producto', 'productos')} desde su precio {lista} actual.
        No cambia el precio {lista}. Los productos sin precio {lista} quedan igual.
      </p>
      {itemIdsNota && <p className={styles.note}>{itemIdsNota}</p>}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </ModalTesla>
  );
}
