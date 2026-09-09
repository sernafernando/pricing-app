/**
 * Unit tests for useProductosData — request-generation (desync) guard.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useProductosData } from './useProductosData';

vi.mock('../services/api', () => {
  const productosAPI = {
    listar: vi.fn(),
    statsDinamicos: vi.fn(),
    marcas: vi.fn().mockResolvedValue({ data: { marcas: [] } }),
    subcategorias: vi.fn().mockResolvedValue({ data: { categorias: [] } }),
    obtenerMarcasPorPMs: vi.fn(),
    obtenerSubcategoriasPorPMs: vi.fn(),
  };
  const api = {
    get: vi.fn().mockResolvedValue({ data: {} }),
  };
  return { productosAPI, default: api };
});

import { productosAPI } from '../services/api';

const EMPTY_FILTERS = {
  debouncedSearch: '',
  filtroStock: '',
  filtroPrecio: '',
  marcasSeleccionadas: [],
  subcategoriasSeleccionadas: [],
  filtroRebate: '',
  filtroOferta: '',
  filtroWebTransf: '',
  filtroTiendaNube: '',
  filtroMarkupClasica: '',
  filtroMarkupRebate: '',
  filtroMarkupOferta: '',
  filtroMarkupWebTransf: '',
  filtroOutOfCards: '',
  coloresSeleccionados: [],
  pmsSeleccionados: [],
  filtrosAuditoria: { usuarios: [], tipos_accion: [], fecha_desde: '', fecha_hasta: '' },
};

function makeStableProps() {
  return {
    construirFiltrosParams: vi.fn(() => ({})),
    page: 1,
    pageSize: 50,
    ordenColumnas: [],
    filters: EMPTY_FILTERS,
    showToast: vi.fn(),
  };
}

async function drainPending(resolvers, payload) {
  const pending = resolvers.splice(0, resolvers.length);
  await act(async () => {
    for (const resolve of pending) {
      resolve(payload);
    }
  });
}

describe('useProductosData — request-generation desync guard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    productosAPI.listar.mockResolvedValue({
      data: { productos: [{ item_id: 'A' }], total: 1 },
    });
    productosAPI.statsDinamicos.mockResolvedValue({
      data: { total_productos: 1 },
    });
  });

  it('ignores a stale listar response that resolves after a newer one', async () => {
    const resolvers = [];
    productosAPI.listar.mockImplementation(() =>
      new Promise((resolve) => {
        resolvers.push(resolve);
      }),
    );

    const props = makeStableProps();
    const { result } = renderHook(() => useProductosData(props));

    await waitFor(() => expect(resolvers.length).toBeGreaterThan(0));
    await drainPending(resolvers, {
      data: { productos: [{ item_id: 'INIT' }], total: 1 },
    });
    await waitFor(() => {
      expect(result.current.productos).toEqual([{ item_id: 'INIT' }]);
    });

    await act(async () => {
      result.current.cargarProductos();
    });
    await waitFor(() => expect(resolvers.length).toBe(1));
    const staleResolve = resolvers[0];

    await act(async () => {
      result.current.cargarProductos();
    });
    await waitFor(() => expect(resolvers.length).toBe(2));
    const freshResolve = resolvers[1];

    await act(async () => {
      freshResolve({
        data: {
          productos: [{ item_id: 'FILTERED' }],
          total: 18,
        },
      });
    });
    await waitFor(() => {
      expect(result.current.totalProductos).toBe(18);
      expect(result.current.productos).toEqual([{ item_id: 'FILTERED' }]);
    });

    await act(async () => {
      staleResolve({
        data: {
          productos: Array.from({ length: 50 }, (_, i) => ({ item_id: `WIDE_${i}` })),
          total: 4291,
        },
      });
      await Promise.resolve();
    });

    expect(result.current.totalProductos).toBe(18);
    expect(result.current.productos).toEqual([{ item_id: 'FILTERED' }]);
  });

  it('ignores a stale statsDinamicos response that resolves after a newer one', async () => {
    const resolvers = [];
    productosAPI.statsDinamicos.mockImplementation(() =>
      new Promise((resolve) => {
        resolvers.push(resolve);
      }),
    );

    const props = makeStableProps();
    const { result } = renderHook(() => useProductosData(props));

    await waitFor(() => expect(resolvers.length).toBeGreaterThan(0));
    await drainPending(resolvers, { data: { total_productos: 1 } });
    await waitFor(() => {
      expect(result.current.stats?.total_productos).toBe(1);
    });

    await act(async () => {
      result.current.cargarStats();
    });
    await waitFor(() => expect(resolvers.length).toBe(1));
    const staleResolve = resolvers[0];

    await act(async () => {
      result.current.cargarStats();
    });
    await waitFor(() => expect(resolvers.length).toBe(2));
    const freshResolve = resolvers[1];

    await act(async () => {
      freshResolve({ data: { total_productos: 18 } });
    });
    await waitFor(() => {
      expect(result.current.stats?.total_productos).toBe(18);
    });

    await act(async () => {
      staleResolve({ data: { total_productos: 4291 } });
      await Promise.resolve();
    });

    expect(result.current.stats?.total_productos).toBe(18);
  });
});
