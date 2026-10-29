import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import api from '../services/api';
import useParaGanarAlcanceOpciones, {
  mergeStringOptions,
  mergeRowOptions,
} from './useParaGanarAlcanceOpciones';

vi.mock('../services/api', () => ({
  default: { get: vi.fn() },
}));

const BASE_PROPS = {
  marcas: [],
  subcategorias: [],
  pms: [],
  tiposPublicacion: [],
  pricelists: [],
  tiendas: [],
  ean: '',
  catalogProductId: '',
};

describe('mergeStringOptions / mergeRowOptions', () => {
  it('keeps selected strings that left the cascade universe', () => {
    expect(mergeStringOptions(['B'], ['A', 'B'])).toEqual(['A', 'B']);
  });

  it('keeps selected row ids that left the cascade universe', () => {
    expect(mergeRowOptions([{ id: 2, nombre: 'Dos' }], [1, 2])).toEqual([
      { id: 1, nombre: '1' },
      { id: 2, nombre: 'Dos' },
    ]);
  });
});

describe('useParaGanarAlcanceOpciones', () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it('does not clear selections when the cascade returns an empty facet', async () => {
    api.get.mockResolvedValue({
      data: {
        marcas: [],
        subcategorias: [],
        pms: [],
        tipos_publicacion: [],
        listas_precios: [],
      },
    });

    const { result } = renderHook((props) => useParaGanarAlcanceOpciones(props), {
      initialProps: {
        ...BASE_PROPS,
        marcas: ['TP-Link'],
        subcategorias: [9],
        tiposPublicacion: ['clasica'],
        pricelists: [4],
      },
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.opciones.marcas).toEqual(['TP-Link']);
    expect(result.current.opciones.subcategorias).toEqual([{ id: 9, nombre: '9' }]);
    expect(result.current.opciones.tipos_publicacion).toEqual([
      { id: 'clasica', nombre: 'clasica' },
    ]);
    expect(result.current.opciones.listas_precios).toEqual([{ id: 4, nombre: '4' }]);
    expect(api.get).toHaveBeenCalledWith(
      '/para-ganar/alcance-opciones',
      expect.objectContaining({
        params: expect.objectContaining({
          marcas: 'TP-Link',
          tipos_publicacion: 'clasica',
          pricelists: '4',
        }),
      }),
    );
  });

  it('retry reloads facets without mutating caller state', async () => {
    api.get.mockResolvedValue({
      data: {
        marcas: ['A'],
        subcategorias: [],
        pms: [],
        tipos_publicacion: [],
        listas_precios: [],
      },
    });
    const { result } = renderHook((props) => useParaGanarAlcanceOpciones(props), {
      initialProps: { ...BASE_PROPS },
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.opciones.marcas).toEqual(['A']);

    api.get.mockResolvedValue({
      data: {
        marcas: ['B'],
        subcategorias: [],
        pms: [],
        tipos_publicacion: [],
        listas_precios: [],
      },
    });
    await act(async () => {
      result.current.retry();
    });
    await waitFor(() => expect(result.current.opciones.marcas).toEqual(['B']));
  });
});
