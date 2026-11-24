import { useCallback, useEffect, useRef } from 'react';

export const RELOAD_MIN_INTERVAL_MS = 5_000;

/** Run the pending reload now, or remember it for when the page is visible again. */
async function run(s) {
  s.timer = null;
  if (document.hidden) {
    s.hiddenPending = true;
    return;
  }
  s.running = true;
  s.pending = false;
  s.last = Date.now();
  try {
    await s.reload();
  } finally {
    s.running = false;
  }
  if (s.pending) schedule(s);
}

/** One timer at most: at the end of the interval since the last reload (now when it already passed). */
function schedule(s) {
  if (s.timer) return;
  s.timer = setTimeout(() => run(s), Math.max(0, s.last + s.minIntervalMs - Date.now()));
}

function request(s) {
  if (document.hidden) {
    s.hiddenPending = true;
  } else if (s.running) {
    s.pending = true;
  } else {
    schedule(s);
  }
}

/**
 * useCoalescedReload - turn a burst of "something changed" events into at most one reload per interval.
 *
 * Every open "Envíos Flex" tab used to reload the whole label list on each SSE event, so a burst of webhooks became
 * a burst of full-list requests on the API (handoffs/drain-diagnostico.md). The returned function:
 * - reloads right away when no reload ran in the last `minIntervalMs`;
 * - otherwise schedules ONE trailing reload at the end of the interval, however many events arrive meanwhile;
 * - never overlaps reloads: an event during a reload runs one more after it, no sooner than the interval;
 * - while the page is hidden, reloads nothing and remembers the event: one reload runs when the page is visible again.
 *
 * @param {Function} reload - async function that reloads the data (it may still skip itself, e.g. while a modal is open)
 * @param {Object} [options]
 * @param {number} [options.minIntervalMs=RELOAD_MIN_INTERVAL_MS]
 * @returns {Function} call it on every change event
 */
export function useCoalescedReload(reload, { minIntervalMs = RELOAD_MIN_INTERVAL_MS } = {}) {
  const state = useRef(null);
  if (state.current === null) {
    state.current = { last: -Infinity, running: false, pending: false, timer: null, hiddenPending: false };
  }

  useEffect(() => {
    state.current.reload = reload;
    state.current.minIntervalMs = minIntervalMs;
  }, [reload, minIntervalMs]);

  useEffect(() => {
    const s = state.current;
    const onVisible = () => {
      if (document.hidden || !s.hiddenPending) return;
      s.hiddenPending = false;
      request(s);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      clearTimeout(s.timer);
      s.timer = null;
    };
  }, []);

  return useCallback(() => request(state.current), []);
}
