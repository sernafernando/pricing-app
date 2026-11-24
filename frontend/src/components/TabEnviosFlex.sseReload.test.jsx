/**
 * "Envíos Flex" reloads its label list at most once per few seconds on a burst of SSE events, instead of once per
 * event (handoffs/drain-diagnostico.md: every open tab used to fetch the whole list on every webhook).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import api from '../services/api';
import { RELOAD_MIN_INTERVAL_MS } from '../hooks/useCoalescedReload';
import TabEnviosFlex from './TabEnviosFlex';

const canales = {};

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('../contexts/PermisosContext', () => ({ usePermisos: () => ({ tienePermiso: () => true }) }));
vi.mock('../contexts/SSEContext', () => ({ useSSE: () => ({ isDegraded: () => false, subscribe: () => () => {} }) }));
vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: (canal, callback) => {
    canales[canal] = callback;
  },
}));
vi.mock('./MapaEnviosFlex', () => ({ default: () => null }));
vi.mock('./CalendarioEnvios', () => ({ default: () => null }));

/** Calls that fetch the label list itself (not its lotes, stats or check-updates). */
const listados = () => api.get.mock.calls.filter(([url]) => /^\/etiquetas-envio\?/.test(url)).length;

async function advance(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  // jsdom has no ResizeObserver; the list's virtualizer only needs it to exist.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  api.get.mockResolvedValue({ data: [] });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('TabEnviosFlex SSE reload', () => {
  it('turns a burst of webhooks and label changes into one immediate and one trailing reload', async () => {
    render(<TabEnviosFlex />);
    await waitFor(() => expect(listados()).toBeGreaterThan(0));
    const inicial = listados();

    for (let i = 0; i < 10; i += 1) {
      act(() => canales[i % 2 ? 'etiquetas:changed' : 'shipments:webhook']());
      await advance(100);
    }
    await advance(RELOAD_MIN_INTERVAL_MS * 3);

    expect(listados() - inicial).toBe(2);
  });
});
