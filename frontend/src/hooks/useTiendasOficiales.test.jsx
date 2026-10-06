import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import api from '../services/api';
import { useTiendasOficiales } from './useTiendasOficiales';
import { useTiendasOficialesStore } from '../store/tiendasOficialesStore';

const STORES = [
  { store_id: 2645, nombre: 'TP-Link', clave: 'tplink', orden: 1, activa: false },
  { store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true },
  { store_id: 471846, nombre: 'TP-Link', clave: 'tplink', orden: 2, activa: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  useTiendasOficialesStore.setState({ tiendas: [], loaded: false, loading: false });
  api.get.mockImplementation((url) =>
    url === '/tiendas-oficiales' ? Promise.resolve({ data: STORES }) : Promise.resolve({ data: {} }),
  );
});

describe('useTiendasOficiales', () => {
  it('getLabel returns the admin-defined name once loaded', async () => {
    const { result } = renderHook(() => useTiendasOficiales());
    await waitFor(() => expect(result.current.getLabel(57997)).toBe('Gauss'));
    expect(result.current.getLabel('471846')).toBe('TP-Link');
  });

  it('renders an unknown id as "Tienda <id>"', async () => {
    const { result } = renderHook(() => useTiendasOficiales());
    await waitFor(() => expect(result.current.getLabel(57997)).toBe('Gauss'));
    expect(result.current.getLabel(999)).toBe('Tienda 999');
    expect(result.current.getLabel('999')).toBe('Tienda 999');
  });

  it('keeps null/undefined as null so callers render their own "Sin tienda"', async () => {
    const { result } = renderHook(() => useTiendasOficiales());
    await waitFor(() => expect(result.current.tiendas.length).toBe(3));
    expect(result.current.getLabel(null)).toBeNull();
    expect(result.current.getLabel(undefined)).toBeNull();
  });

  it('exposes only active stores, ordered by `orden`, in `activas`', async () => {
    const { result } = renderHook(() => useTiendasOficiales());
    await waitFor(() => expect(result.current.activas.length).toBe(2));
    expect(result.current.activas.map((t) => t.store_id)).toEqual([57997, 471846]);
    // An inactive store still has a name (its history keeps rendering).
    expect(result.current.getLabel(2645)).toBe('TP-Link');
  });

  it('fetches once for many consumers', async () => {
    const a = renderHook(() => useTiendasOficiales());
    const b = renderHook(() => useTiendasOficiales());
    await waitFor(() => expect(a.result.current.tiendas.length).toBe(3));
    await waitFor(() => expect(b.result.current.tiendas.length).toBe(3));
    expect(api.get.mock.calls.filter(([url]) => url === '/tiendas-oficiales')).toHaveLength(1);
  });

  it('falls back to "Tienda <id>" when the request fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useTiendasOficiales());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.getLabel(57997)).toBe('Tienda 57997');
  });

  it('reload refetches (used by the admin panel after saving)', async () => {
    const { result } = renderHook(() => useTiendasOficiales());
    await waitFor(() => expect(result.current.tiendas.length).toBe(3));
    api.get.mockResolvedValue({ data: [{ store_id: 1, nombre: 'Nueva', clave: null, orden: 0, activa: true }] });
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.getLabel(1)).toBe('Nueva');
  });
});
