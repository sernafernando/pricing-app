/**
 * useListOffsets: the offsets the list's clásica cells apply (Productos' "markup con offsets"), with the Mercado
 * Libre channel and the USD rate the Precios tab uses.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useListOffsets } from './useListOffsets';
import { offsetsGananciaAPI, preciosAPI } from '../services/api';

vi.mock('../services/api', () => ({
  offsetsGananciaAPI: { vigentes: vi.fn(), grupoFiltros: vi.fn() },
  preciosAPI: { tipoCambioActual: vi.fn() },
}));

// Lets every pending read settle (and its state update land) before asserting what the hook ended with.
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

const OFFSET = { id: 1, tipo_offset: 'porcentaje_costo', porcentaje: 10, marca: 'TP-LINK' };

beforeEach(() => {
  vi.clearAllMocks();
  offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSET] });
  preciosAPI.tipoCambioActual.mockResolvedValue({ data: { venta: 1200 } });
});

describe('useListOffsets', () => {
  it('reads the current offsets and the USD rate, for the Mercado Libre channel', async () => {
    const { result } = renderHook(() => useListOffsets(true));
    await waitFor(() => expect(result.current?.tipoCambio).toBe(1200));
    expect(result.current).toMatchObject({ offsets: [OFFSET], grupoFiltros: {}, canal: 'ml' });
  });

  it('keeps the same object across renders until the offsets or the rate change', async () => {
    const { result, rerender } = renderHook(() => useListOffsets(true));
    await waitFor(() => expect(result.current?.tipoCambio).toBe(1200));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it('reads nothing when disabled (no margin permission, no prices on show)', () => {
    const { result } = renderHook(() => useListOffsets(false));
    expect(result.current).toBeNull();
    expect(offsetsGananciaAPI.vigentes).not.toHaveBeenCalled();
    expect(preciosAPI.tipoCambioActual).not.toHaveBeenCalled();
  });

  it('with no current offset there is nothing to apply, and no rate is read', async () => {
    offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
    const { result } = renderHook(() => useListOffsets(true));
    await settle();
    expect(offsetsGananciaAPI.vigentes).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
    expect(preciosAPI.tipoCambioActual).not.toHaveBeenCalled();
  });

  it('a failed offsets read leaves the cells without the line, never with a guess', async () => {
    offsetsGananciaAPI.vigentes.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useListOffsets(true));
    await settle();
    expect(offsetsGananciaAPI.vigentes).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
    expect(preciosAPI.tipoCambioActual).not.toHaveBeenCalled();
  });
});
