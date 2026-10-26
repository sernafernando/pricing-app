import { useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { publicacionesMlAPI } from '../../../services/api';
import styles from './panel.module.css';

// What each current status offers: only an active publication is paused and only a paused one activated.
const ACTIONS = {
  active: { target: 'paused', label: 'Pausar', Icon: Pause, question: '¿Pausar la publicación en Mercado Libre?' },
  paused: { target: 'active', label: 'Activar', Icon: Play, question: '¿Activar la publicación en Mercado Libre?' },
};

const DONE = { paused: 'Publicación pausada en Mercado Libre.', active: 'Publicación activada en Mercado Libre.' };
const UNCHANGED = { paused: 'La publicación ya estaba pausada.', active: 'La publicación ya estaba activa.' };

/** What to tell the operator when the write did not go through. */
function describeError(error) {
  const status = error?.response?.status;
  if (status === 403) return 'No tenés permiso para pausar o activar publicaciones.';
  // 409 not eligible, 422 refused by ML, 503 nothing reached ML: the server says why.
  return error?.response?.data?.message ?? 'No se pudo cambiar el estado. Probá de nuevo.';
}

function isDeleted(detail) {
  return detail.row.gone === true || detail.subStatus.includes('deleted');
}

/**
 * "Pausar" / "Activar" for one publication, after a confirmation. Shown only with `ml_publicaciones.pausar`
 * (`detail.canChangeStatus`; the server enforces it too) on an active or paused publication that is not deleted.
 * After a write the button stays hidden: the stored status catches up in seconds, and until then it would offer
 * the old action. Mount it with `key={itemId}`.
 *
 * @param {object} props
 * @param {object} props.detail The read detail (`detailModel`).
 * @param {string} props.itemId
 * @param {() => void} [props.onChanged] Re-reads the panel and the list after a write that may have landed.
 */
export default function StatusAction({ detail, itemId, onChanged }) {
  const [state, setState] = useState({ status: 'idle', message: null });
  const action = ACTIONS[detail.row.status];
  if (!detail.canChangeStatus || !action || isDeleted(detail)) return null;

  const send = async () => {
    if (state.status === 'sending') return;
    setState({ status: 'sending', message: null });
    try {
      const { data } = await publicacionesMlAPI.setItemStatus(itemId, action.target);
      const message =
        data?.status === 'unchanged'
          ? UNCHANGED[action.target]
          : data?.status === 'submitted'
            ? DONE[action.target]
            : (data?.message ?? 'Cambio enviado a Mercado Libre.');
      setState({ status: 'done', message });
      onChanged?.();
    } catch (error) {
      setState({ status: 'error', message: describeError(error) });
    }
  };

  if (state.status === 'done') {
    return (
      <div className={styles.feedback} role="status">
        <span>{state.message}</span>
        <span>El estado se actualiza en unos segundos.</span>
      </div>
    );
  }

  const { Icon } = action;
  return (
    <div className={styles.resync}>
      {state.status === 'confirming' || state.status === 'sending' ? (
        <div className={styles.statusConfirm}>
          <span>{action.question}</span>
          <button type="button" className="btn-tesla primary sm" onClick={send} disabled={state.status === 'sending'}>
            Confirmar
          </button>
          <button
            type="button"
            className="btn-tesla outline sm"
            onClick={() => setState({ status: 'idle', message: null })}
            disabled={state.status === 'sending'}
          >
            Cancelar
          </button>
        </div>
      ) : (
        <button type="button" className="btn-tesla outline sm" onClick={() => setState({ status: 'confirming', message: null })}>
          <Icon size={14} aria-hidden="true" />
          {action.label}
        </button>
      )}
      {state.status === 'error' && (
        <div className={styles.feedback} role="alert">
          {state.message}
        </div>
      )}
    </div>
  );
}
