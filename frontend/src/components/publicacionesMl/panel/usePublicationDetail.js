import { useEffect, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { readDetail } from './detailModel';

const LOADING = { itemId: null, raw: null, error: null };

/**
 * Loads the detail of `itemId` for the side panel. Every request starts from
 * "loading" -- a publication's earlier answer is never shown while its next one
 * is on the way, and the previous publication's data is never shown under the
 * new one -- and an answer that arrives after the selection moved on is dropped.
 * `reload` asks again (the retry button).
 */
export function usePublicationDetail(itemId, { canSeeMargin }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState(LOADING);

  useEffect(() => {
    let current = true;
    setState(LOADING);
    publicacionesMlAPI
      .detail(itemId)
      .then((response) => {
        if (current) setState({ itemId, raw: response.data, error: null });
      })
      .catch((error) => {
        if (current) setState({ itemId, raw: null, error });
      });
    return () => {
      current = false;
    };
  }, [itemId, attempt]);

  const reload = () => setAttempt((n) => n + 1);
  if (state.itemId !== itemId) return { status: 'loading', detail: null, error: null, reload };
  if (state.error) return { status: 'error', detail: null, error: state.error, reload };
  return { status: 'ready', detail: readDetail(state.raw, { canSeeMargin }), error: null, reload };
}
