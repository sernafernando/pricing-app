import { useEffect, useRef } from 'react';
import { useSSE } from '../contexts/SSEContext';

/**
 * useSSEChannel - subscribe to an SSE channel with automatic cleanup.
 *
 * @param {string} channel - Channel name (e.g., 'etiquetas:changed')
 * @param {Function} callback - Called when an event arrives on this channel.
 *   Receives the parsed event data: { channel, data, timestamp }
 * @param {Object} [options]
 * @param {boolean} [options.enabled=true] - Set to false to skip subscription
 *
 * Usage:
 *   useSSEChannel('etiquetas:changed', () => {
 *     cargarDatos(); // silent reload, no loading spinner
 *   });
 *
 *   useSSEChannel('notificaciones:updated', fetchNotificaciones);
 */
export function useSSEChannel(channel, callback, options = {}) {
  const { enabled = true } = options;
  const { subscribe } = useSSE();
  const callbackRef = useRef(callback);

  // Keep callback ref fresh without re-subscribing
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled || !channel) return;

    const unsubscribe = subscribe(channel, (event) => {
      callbackRef.current(event);
    });

    return unsubscribe;
  }, [channel, enabled, subscribe]);
}
