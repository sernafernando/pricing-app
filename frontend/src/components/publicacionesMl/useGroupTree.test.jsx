/** The tree's state hook (publicaciones-ml-vista P12a): one request per branch page, however fast the clicks. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useGroupTree from './useGroupTree';
import { publicacionesMlAPI } from '../../services/api';
import { BRAND_NODES, groupsResponse } from '../../test/visual/publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  publicacionesMlAPI: { items: vi.fn(), groups: vi.fn() },
}));

const FILTERS = {
  q: '', familia: '', evento_desde: '', estado: [], estado_excluir: [], tiendas: [], marcas: [], categorias: [],
  subcategorias: [], pms: [], tipo: [], vinculo: [], stock: [], evento: [], markup_neg: '', markup_min: '',
  markup_max: '', orden: '', dir: '', pagina: 1, limite: 50,
};

beforeEach(() => {
  publicacionesMlAPI.groups.mockReset();
  publicacionesMlAPI.groups.mockImplementation(({ path }) =>
    Promise.resolve({ data: groupsResponse(path ? 'categoria' : 'marca', BRAND_NODES) }),
  );
});

describe('useGroupTree', () => {
  it('asks once for a node opened twice before its answer (a double click)', async () => {
    const { result } = renderHook(() => useGroupTree({ filters: FILTERS, familias: false, canSeeMargin: false }));
    await waitFor(() => expect(result.current.rows.length).toBeGreaterThan(0));
    const row = result.current.rows[0];
    act(() => {
      result.current.toggle(row);
      result.current.toggle(row);
    });
    await waitFor(() => expect(publicacionesMlAPI.groups.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(publicacionesMlAPI.groups.mock.calls.filter(([params]) => params.path === row.node.key)).toHaveLength(1);
  });
});
