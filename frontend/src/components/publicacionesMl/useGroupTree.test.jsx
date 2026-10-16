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

  it("a late answer of the previous tree does not lift the new tree's guard for the same page", async () => {
    let settleOld;
    const old = new Promise((resolve) => {
      settleOld = resolve;
    });
    publicacionesMlAPI.groups.mockReset();
    publicacionesMlAPI.groups.mockReturnValueOnce(old).mockReturnValue(new Promise(() => {}));
    const { result, rerender } = renderHook(
      ({ filters }) => useGroupTree({ filters, familias: false, canSeeMargin: false }),
      { initialProps: { filters: FILTERS } },
    );
    rerender({ filters: { ...FILTERS, tiendas: ['57997'] } }); // the new tree asks for its roots while the old is pending
    await waitFor(() => expect(publicacionesMlAPI.groups).toHaveBeenCalledTimes(2));
    await act(async () => {
      settleOld({ data: groupsResponse('marca', BRAND_NODES) });
      await old;
    });
    act(() => result.current.loadMore('')); // the new roots are still pending: asking again must ask for nothing
    expect(publicacionesMlAPI.groups).toHaveBeenCalledTimes(2);
  });
});
