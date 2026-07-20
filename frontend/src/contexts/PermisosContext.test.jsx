import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { PermisosProvider, usePermisos } from './PermisosContext';
import { useAuthStore } from '../store/authStore';
import api from '../services/api';

// The global setup stubs PermisosContext and authStore for page tests; here we
// test the REAL provider against the real zustand store, so undo those stubs.
vi.unmock('./PermisosContext');
vi.unmock('../store/authStore');

vi.mock('../services/api', () => ({
  default: { get: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
  authAPI: { login: vi.fn(), me: vi.fn() },
}));

function wrapper({ children }) {
  return <PermisosProvider>{children}</PermisosProvider>;
}

const permisosResponse = (permisos, rol = 'ADMIN') => ({
  data: { permisos, rol, usuario_id: 1 },
});

describe('PermisosContext — silent refetch on token rotation', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'token-inicial');
    useAuthStore.setState({ token: 'token-inicial' });
    api.get.mockReset();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('initial load is blocking: loading=true until permisos arrive', async () => {
    api.get.mockResolvedValue(permisosResponse(['productos.ver']));

    const { result } = renderHook(() => usePermisos(), { wrapper });

    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.initialized).toBe(true);
    expect(result.current.tienePermiso('productos.ver')).toBe(true);
  });

  it('token rotation refetches WITHOUT flipping loading (no page unmount)', async () => {
    api.get.mockResolvedValue(permisosResponse(['productos.ver']));

    const { result } = renderHook(() => usePermisos(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Hold the refetch in-flight so we can observe intermediate state
    let resolveRefetch;
    api.get.mockReturnValue(
      new Promise((resolve) => {
        resolveRefetch = resolve;
      })
    );

    // Simulate the proactive token refresh (~every 24 min)
    act(() => {
      localStorage.setItem('token', 'token-rotado');
      useAuthStore.setState({ token: 'token-rotado' });
    });

    // While the refetch is in flight, the app must stay mounted:
    // loading stays false and the old permisos remain usable.
    expect(result.current.loading).toBe(false);
    expect(result.current.initialized).toBe(true);
    expect(result.current.tienePermiso('productos.ver')).toBe(true);

    await act(async () => {
      resolveRefetch(permisosResponse(['productos.ver', 'tienda.ver'], 'PM'));
    });

    await waitFor(() =>
      expect(result.current.tienePermiso('tienda.ver')).toBe(true)
    );
    expect(result.current.loading).toBe(false);
  });

  it('failed background refetch keeps the previous permisos (no error screen)', async () => {
    vi.useFakeTimers();
    try {
      api.get.mockResolvedValue(permisosResponse(['productos.ver']));

      const { result } = renderHook(() => usePermisos(), { wrapper });
      await act(async () => {
        await vi.runAllTimersAsync();
      });
      expect(result.current.loading).toBe(false);

      // Backend restarting mid-deploy: every retry fails
      api.get.mockRejectedValue(new Error('502 Bad Gateway'));

      act(() => {
        localStorage.setItem('token', 'token-rotado');
        useAuthStore.setState({ token: 'token-rotado' });
      });
      await act(async () => {
        await vi.runAllTimersAsync(); // exhaust the 0/400/1200ms retry backoff
      });

      // Stale permisos beat a blank/error screen mid-work
      expect(result.current.loading).toBe(false);
      expect(result.current.initialized).toBe(true);
      expect(result.current.error).toBe(null);
      expect(result.current.tienePermiso('productos.ver')).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('failed FIRST load still surfaces the error state (retry screen)', async () => {
    vi.useFakeTimers();
    try {
      api.get.mockRejectedValue(new Error('network down'));

      const { result } = renderHook(() => usePermisos(), { wrapper });
      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.loading).toBe(false);
      expect(result.current.initialized).toBe(false);
      expect(result.current.error).not.toBe(null);
    } finally {
      vi.useRealTimers();
    }
  });
});
