import { useCallback, useEffect, useMemo, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import { readDetail } from './detailModel';

/**
 * Loads the detail of `itemId` for the side panel. A new `itemId` starts from
 * "loading" at once -- the previous publication's data is never shown under the
 * new one -- and an answer that arrives after the selection moved on is dropped.
 * `reload` asks again (the retry button).
 */
export function usePublicationDetail(itemId, { canSeeMargin }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ itemId: null, raw: null, error: null });

  useEffect(() => {
    let current = true;
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

  const answered = state.itemId === itemId;
  const detail = useMemo(
    () => (answered && state.raw ? readDetail(state.raw, { canSeeMargin }) : null),
    [answered, state.raw, canSeeMargin],
  );
  const reload = useCallback(() => {
    setState({ itemId: null, raw: null, error: null });
    setAttempt((n) => n + 1);
  }, []);

  if (!answered) return { status: 'loading', detail: null, error: null, reload };
  if (state.error) return { status: 'error', detail: null, error: state.error, reload };
  return { status: 'ready', detail, error: null, reload };
}
