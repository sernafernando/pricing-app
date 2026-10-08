import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { publicacionesMlAPI } from '../../../services/api';
import { timeAgo } from '../../../utils/ventasMlFormat';
import { label } from './labels';
import styles from './panel.module.css';

// What a resync asks for: the item's own data plus the Full replenishment report.
const RESYNC_RESOURCES = ['bundle', 'replenishment'];

const RESOURCE_NAMES = {
  core: 'Datos',
  sale_price: 'Precio de oferta',
  stock: 'Stock',
  replenishment: 'Reposición',
};
// The resources the store may not collect, in the words of the message about them.
const MISSING_NAMES = { replenishment: 'reposición de Full', stock: 'stock', sale_price: 'precio de oferta' };

/** What to tell the operator when the resync request fails. */
function describeError(error) {
  const status = error?.response?.status;
  if (status === 403) return 'No tenés permiso para resincronizar.';
  if (status === 422) return 'El pedido de resincronización no es válido.';
  return 'No se pudo pedir la resincronización. Probá de nuevo.';
}

function Freshness({ entries }) {
  if (entries.length === 0) return null;
  return (
    <ul className={styles.freshness} aria-label="Actualización de los datos">
      {entries.map((entry) => {
        const ago = timeAgo(entry.fetched_at);
        return (
          <li key={entry.resource} title={entry.last_checked_at ? `Última verificación: ${entry.last_checked_at}` : undefined}>
            <span className={styles.freshnessName}>{label(RESOURCE_NAMES, entry.resource)}</span>{' '}
            <span>{ago ?? 'sin datos'}</span>
            {entry.state && entry.state !== 'ok' && <span className={styles.freshnessState}> ({entry.state})</span>}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Footer of the panel: how fresh each resource is, and "Resincronizar" for who
 * may manage the store. Mount it with `key={itemId}` so one publication's
 * feedback is never shown under the next.
 *
 * @param {object} props
 * @param {object} props.detail The read detail (`detailModel`).
 * @param {string} props.itemId
 * @param {boolean} props.canManage `ml_ops.gestionar`; the server enforces it too.
 */
export default function PanelFooter({ detail, itemId, canManage }) {
  const [state, setState] = useState({ status: 'idle', result: null, error: null });
  const canResync = canManage && detail.canResync;

  const resync = async () => {
    if (state.status === 'sending') return;
    // The freshness above is untouched on a failure: nothing was resynced.
    setState({ status: 'sending', result: null, error: null });
    try {
      const response = await publicacionesMlAPI.enqueue({ item_ids: [itemId], resources: RESYNC_RESOURCES });
      setState({ status: 'done', result: response.data, error: null });
    } catch (error) {
      setState({ status: 'error', result: null, error });
    }
  };

  const missing = state.result?.missing_from_bundle_resources ?? [];
  return (
    <footer className={styles.footer}>
      <Freshness entries={detail.freshness} />
      {canResync && (
        <div className={styles.resync}>
          <button type="button" className="btn-tesla outline sm" onClick={resync} disabled={state.status === 'sending'}>
            <RefreshCw size={14} aria-hidden="true" />
            Resincronizar
          </button>
          {state.status === 'done' && (
            <div className={styles.feedback} role="status">
              <span>Resincronización pedida. Los datos se actualizan en unos minutos.</span>
              {state.result.note && <span>{state.result.note}</span>}
              {missing.length > 0 && (
                <span>No habilitado en la sincronización: {missing.map((name) => label(MISSING_NAMES, name)).join(', ')}.</span>
              )}
            </div>
          )}
          {state.status === 'error' && (
            <div className={styles.feedback} role="alert">
              {describeError(state.error)}
            </div>
          )}
        </div>
      )}
    </footer>
  );
}
