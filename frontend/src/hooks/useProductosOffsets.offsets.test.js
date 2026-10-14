/**
 * Productos' "markup con offsets" must not change when its logic moves to
 * utils/offsetsGanancia.js: same endpoints, same filters, same figure.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import api from '../services/api';
import { useProductosOffsets } from './useProductosOffsets';

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

const OFFSETS = [
  { id: 1, marca: 'TP-LINK', tipo_offset: 'porcentaje_costo', porcentaje: 10, grupo_id: null },
  { id: 2, grupo_id: 3, tipo_offset: 'monto_por_unidad', monto: 1, moneda: 'USD' },
  { id: 3, marca: 'TP-LINK', tipo_offset: 'monto_fijo', monto: 999999 },
  { id: 4, marca: 'TP-LINK', tipo_offset: 'porcentaje_costo', porcentaje: 50, max_unidades: 5 },
];

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url) => {
    if (url === '/offsets-ganancia') return Promise.resolve({ data: OFFSETS });
    if (url === '/tipo-cambio-hoy') return Promise.resolve({ data: { tipo_cambio: 1000 } });
    if (url === '/offset-grupos/3/filtros') return Promise.resolve({ data: [{ categoria: 'ROUTERS' }] });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
});

describe('useProductosOffsets.calcularMarkupConOffset', () => {
  it('reads the current offsets and applies the uncapped ones to the markup', async () => {
    const { result } = renderHook(() => useProductosOffsets());
    await waitFor(() => expect(result.current.offsetGrupoFiltros).toEqual({ 3: [{ categoria: 'ROUTERS' }] }));
    expect(api.get).toHaveBeenCalledWith('/offsets-ganancia', { params: { solo_vigentes: true } });
    expect(result.current.tipoCambioUSD).toBe(1000);
    expect(result.current.offsetsVigentes.map((o) => o.id)).toEqual([1, 2]);

    const producto = { item_id: 1, marca: 'TP-LINK', categoria: 'ROUTERS', moneda_costo: 'ARS', costo: 10000, markup: 20 };
    // descuento = 1000 (10%) + 1000 (USD 1) -> costo ajustado 8000; 12000 / 8000 - 1 = 50%
    expect(result.current.calcularMarkupConOffset(producto)).toBe(50);
    expect(result.current.calcularMarkupConOffset({ ...producto, markup: null })).toBeNull();
    expect(result.current.calcularMarkupConOffset({ ...producto, marca: 'OTRA', categoria: 'OTRA' })).toBeNull();
  });

  it('is null until the offsets are read', () => {
    api.get.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useProductosOffsets());
    expect(result.current.calcularMarkupConOffset({ marca: 'TP-LINK', costo: 100, markup: 10 })).toBeNull();
  });
});
