import { createContext, useContext, useEffect, useRef, useCallback } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';

const SSEContext = createContext(null);

const API_BASE = import.meta.env.VITE_API_URL;

// Backoff config
const BACKOFF_BASE_MS = 1000;
const BACKOFF_CAP_MS = 16000;
const BACKOFF_STABLE_RESET_MS = 30000;
const JITTER_MAX_MS = 1000;

// Degradation: 3 failures in 60s → polling fallback
const FAILURE_WINDOW_MS = 60000;
const FAILURE_THRESHOLD = 3;

const isSSEEnabled = () => localStorage.getItem('sse_enabled') !== 'false';
const isDebug = () => localStorage.getItem('sse_debug') === 'true';

const debugLog = (...args) => {
  if (isDebug()) {
    console.log('[SSE]', ...args);
  }
};

// eslint-disable-next-line react-refresh/only-export-components
export const useSSE = () => {
  const context = useContext(SSEContext);
  if (!context) {
    throw new Error('useSSE must be used within SSEProvider');
  }
  return context;
};

/**
 * SSEProvider - manages a single multiplexed SSE connection for the app.
 *
 * Opens a connection when authenticated & sse_enabled !== 'false'.
 * Dispatches events to per-channel subscribers.
 * Auto-reconnects with exponential backoff.
 * Pauses on tab hidden, resumes on tab visible.
 * Degrades to polling fallback after 3 failures in 60s.
 */
export function SSEProvider({ children }) {
  // Map<channel, Set<callback>>
  const subscribersRef = useRef(new Map());
  const controllerRef = useRef(null);
  const retryStateRef = useRef({
    count: 0,
    failures: [],
    degraded: false,
  });
  const lastEventIdRef = useRef(null);
  const connectedAtRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const isConnectingRef = useRef(false);

  const getToken = useCallback(() => localStorage.getItem('token'), []);

  const getActiveChannels = useCallback(() => {
    return Array.from(subscribersRef.current.keys());
  }, []);

  const connect = useCallback(() => {
    const token = getToken();
    if (!token || !isSSEEnabled()) {
      debugLog('Skipping connection: no token or SSE disabled');
      return;
    }

    const channels = getActiveChannels();
    if (channels.length === 0) {
      debugLog('Skipping connection: no active channels');
      return;
    }

    // Abort existing connection
    if (controllerRef.current) {
      controllerRef.current.abort();
      controllerRef.current = null;
    }

    if (isConnectingRef.current) return;
    isConnectingRef.current = true;

    const controller = new AbortController();
    controllerRef.current = controller;

    const url = `${API_BASE}/sse/stream?channels=${channels.join(',')}`;
    const headers = { Authorization: `Bearer ${token}` };
    if (lastEventIdRef.current) {
      headers['Last-Event-ID'] = lastEventIdRef.current;
    }

    debugLog('Connecting to', url, 'channels:', channels);

    fetchEventSource(url, {
      method: 'GET',
      headers,
      signal: controller.signal,
      openWhenHidden: false,

      onopen: async (response) => {
        isConnectingRef.current = false;
        if (response.ok) {
          debugLog('Connection opened, status:', response.status);
          connectedAtRef.current = Date.now();

          // Reset backoff after stable connection
          if (retryStateRef.current.count > 0) {
            debugLog('Resetting backoff after successful connection');
          }
          retryStateRef.current.count = 0;

          // If we were degraded, check if we should recover
          if (retryStateRef.current.degraded) {
            retryStateRef.current.degraded = false;
            retryStateRef.current.failures = [];
            debugLog('SSE recovered from degraded mode');
          }
        } else {
          debugLog('Connection failed, status:', response.status);
          throw new Error(`SSE connection failed: ${response.status}`);
        }
      },

      onmessage: (event) => {
        if (event.id) {
          lastEventIdRef.current = event.id;
        }

        // Skip heartbeat comments (they come as empty events or comments)
        if (!event.data) return;

        try {
          const parsed = JSON.parse(event.data);
          const channel = parsed.channel;

          debugLog('Event received:', channel, parsed.data);

          const callbacks = subscribersRef.current.get(channel);
          if (callbacks) {
            callbacks.forEach((cb) => {
              try {
                cb(parsed);
              } catch (err) {
                console.error('[SSE] Subscriber callback error:', err);
              }
            });
          }
        } catch (err) {
          debugLog('Failed to parse event data:', event.data, err);
        }
      },

      onerror: (err) => {
        isConnectingRef.current = false;

        // If manually aborted (tab hidden, disconnect), don't count as failure
        if (controller.signal.aborted) {
          debugLog('Connection aborted (intentional)');
          return; // Don't retry — reconnect is handled by visibility handler
        }

        debugLog('Connection error:', err);

        // Track failure for degradation detection
        const now = Date.now();
        retryStateRef.current.failures.push(now);
        // Keep only failures within the window
        retryStateRef.current.failures = retryStateRef.current.failures.filter(
          (t) => now - t < FAILURE_WINDOW_MS
        );

        // Check degradation threshold
        if (retryStateRef.current.failures.length >= FAILURE_THRESHOLD) {
          retryStateRef.current.degraded = true;
          debugLog('Entering degraded mode (polling fallback) after', FAILURE_THRESHOLD, 'failures');
          // Stop retrying — components will detect degraded mode and fall back to polling
          throw new Error('SSE degraded'); // This tells fetchEventSource to stop
        }

        // Exponential backoff
        retryStateRef.current.count += 1;
        const backoff = Math.min(
          BACKOFF_BASE_MS * Math.pow(2, retryStateRef.current.count - 1),
          BACKOFF_CAP_MS
        );
        const jitter = Math.random() * JITTER_MAX_MS;
        const delay = backoff + jitter;

        debugLog(`Reconnecting in ${Math.round(delay)}ms (attempt ${retryStateRef.current.count})`);

        // Clear existing timer
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
        }

        reconnectTimerRef.current = setTimeout(() => {
          connect();
        }, delay);

        // Throw to stop fetchEventSource's built-in retry
        throw new Error('Manual retry');
      },

      onclose: () => {
        isConnectingRef.current = false;
        debugLog('Connection closed by server');

        // Auto-reconnect unless degraded or aborted
        if (!controller.signal.aborted && !retryStateRef.current.degraded) {
          retryStateRef.current.count += 1;
          const backoff = Math.min(
            BACKOFF_BASE_MS * Math.pow(2, retryStateRef.current.count - 1),
            BACKOFF_CAP_MS
          );
          const jitter = Math.random() * JITTER_MAX_MS;
          const delay = backoff + jitter;

          debugLog(`Server closed, reconnecting in ${Math.round(delay)}ms`);

          if (reconnectTimerRef.current) {
            clearTimeout(reconnectTimerRef.current);
          }

          reconnectTimerRef.current = setTimeout(() => {
            connect();
          }, delay);
        }
      },
    }).catch(() => {
      // fetchEventSource rejects when we throw in onerror/onclose
      // This is expected — we handle retry ourselves
      isConnectingRef.current = false;
    });
  }, [getToken, getActiveChannels]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (controllerRef.current) {
      controllerRef.current.abort();
      controllerRef.current = null;
    }
    isConnectingRef.current = false;
  }, []);

  // Tab visibility management
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        debugLog('Tab hidden — closing SSE connection');
        disconnect();
      } else {
        debugLog('Tab visible — reconnecting SSE');
        // Immediate reconnect on tab visible (no backoff, no failure count)
        connect();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [connect, disconnect]);

  // Backoff reset after stable connection
  useEffect(() => {
    const interval = setInterval(() => {
      if (
        connectedAtRef.current &&
        Date.now() - connectedAtRef.current > BACKOFF_STABLE_RESET_MS &&
        retryStateRef.current.count > 0
      ) {
        retryStateRef.current.count = 0;
        debugLog('Backoff reset after stable connection');
      }
    }, BACKOFF_STABLE_RESET_MS);

    return () => clearInterval(interval);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  const subscribe = useCallback(
    (channel, callback) => {
      if (!subscribersRef.current.has(channel)) {
        subscribersRef.current.set(channel, new Set());
      }
      subscribersRef.current.get(channel).add(callback);

      const hadConnection = controllerRef.current !== null;
      const channelCount = subscribersRef.current.size;

      debugLog('Subscribe:', channel, `(${channelCount} channels total)`);

      // If this is the first subscriber or a new channel was added, reconnect
      // to include the new channel in the SSE connection
      if (!hadConnection || channelCount > 0) {
        // Small delay to batch multiple subscribe calls on mount
        setTimeout(() => connect(), 0);
      }

      return () => {
        const subs = subscribersRef.current.get(channel);
        if (subs) {
          subs.delete(callback);
          if (subs.size === 0) {
            subscribersRef.current.delete(channel);
            debugLog('Unsubscribe: channel removed:', channel);

            // If no channels left, disconnect
            if (subscribersRef.current.size === 0) {
              disconnect();
            }
          }
        }
      };
    },
    [connect, disconnect]
  );

  const isDegraded = useCallback(() => {
    return retryStateRef.current.degraded;
  }, []);

  return (
    <SSEContext.Provider value={{ subscribe, isDegraded }}>
      {children}
    </SSEContext.Provider>
  );
}
