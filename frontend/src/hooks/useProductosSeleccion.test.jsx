/**
 * Painting one product (`PATCH /productos/{id}/color`): the backend reads the team layer from the QUERY string
 * (`?equipo_id=`, docs/color-teams-frontend-contract.md). Sent in the body it was ignored and every single paint on a
 * team layer landed on the global one.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import api from '../services/api';
import { useProductosSeleccion } from './useProductosSeleccion';

vi.mock('../services/api', () => ({ default: { patch: vi.fn(), post: vi.fn() } }));

function setup(equipoActivoId) {
  const setProductos = vi.fn();
  const { result } = renderHook(() =>
    useProductosSeleccion({
      productos: [{ item_id: 1, color_marcado: null }],
      setProductos,
      cargarStats: vi.fn(),
      showToast: vi.fn(),
      equipoActivoId,
    }),
  );
  return { result, setProductos };
}

describe('useProductosSeleccion: painting one product', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.patch.mockResolvedValue({ data: {} });
  });

  it.each(['cambiarColorProducto', 'cambiarColorRapido'])('%s sends the team layer as ?equipo_id=', async (fn) => {
    const { result } = setup(7);
    await act(() => result.current[fn](1, 'rojo'));
    expect(api.patch).toHaveBeenCalledWith('/productos/1/color', { color: 'rojo' }, { params: { equipo_id: 7 } });
  });

  it.each(['cambiarColorProducto', 'cambiarColorRapido'])('%s on the global layer sends no equipo_id', async (fn) => {
    const { result, setProductos } = setup(null);
    await act(() => result.current[fn](1, 'verde'));
    expect(api.patch).toHaveBeenCalledWith('/productos/1/color', { color: 'verde' }, { params: {} });
    expect(setProductos).toHaveBeenCalled();
  });
});
