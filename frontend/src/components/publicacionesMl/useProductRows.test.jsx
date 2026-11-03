/**
 * useProductRows: what the Producto view's pager and in-flight guard say while lists change under them. A new list
 * never shows the previous list's total (loading or failed), and a late answer of an old list never lifts the guard
 * of the same page in the new one.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import useProductRows from './useProductRows';
import { ALL_ROWS } from '../../hooks/usePublicacionesMLFilters';
import { publicacionesMlAPI } from '../../services/api';
import { productsResponse } from '../../test/visual/publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  publicacionesMlAPI: { items: vi.fn(), products: vi.fn() },
}));

const FILTERS = {
  q: '',
  familia: '',
  evento_desde: '',
  estado: ['active'],
  estado_excluir: [],
  tiendas: [],
  marcas: [],
  categorias: [],
  subcategorias: [],
  pms: [],
  tipo: [],
  vinculo: [],
  stock: [],
  evento: [],
  markup_neg: '',
  markup_min: '',
  markup_max: '',
  orden: '',
  dir: '',
  pagina: 1,
  limite: 50,
  sel: '',
};
const PAUSED = { ...FILTERS, estado: ['paused'] };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const setup = () =>
  renderHook(({ filters }) => useProductRows({ filters, pageSize: 50, canSeeSales: true, canSeeMargin: true }), {
    initialProps: { filters: FILTERS },
  });

beforeEach(() => {
  publicacionesMlAPI.products.mockReset();
  publicacionesMlAPI.items.mockReset();
});

describe('the pager total', () => {
  it('is not the previous list while the new one loads', async () => {
    publicacionesMlAPI.products.mockResolvedValueOnce({ data: productsResponse(undefined, { total: 120, mla_count: 400 }) });
    const { result, rerender } = setup();
    await waitFor(() => expect(result.current.total).toBe(120));
    publicacionesMlAPI.products.mockReturnValueOnce(new Promise(() => {}));
    rerender({ filters: PAUSED });
    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.total).toBe(0);
    expect(result.current.mlaCount).toBe(0);
  });

  it('is not the previous list when the new one fails: the error row shows instead', async () => {
    publicacionesMlAPI.products.mockResolvedValueOnce({ data: productsResponse(undefined, { total: 120 }) });
    const { result, rerender } = setup();
    await waitFor(() => expect(result.current.total).toBe(120));
    publicacionesMlAPI.products.mockRejectedValueOnce(Object.assign(new Error('boom'), { response: { status: 503 } }));
    rerender({ filters: PAUSED });
    await waitFor(() => expect(result.current.rows.some((row) => row.type === 'state' && row.state === 'error')).toBe(true));
    expect(result.current.total).toBe(0);
  });
});

describe("the Sin MLA count (Productos' card)", () => {
  it('is what /products says, and unknown when it says nothing (a publication filter is on)', async () => {
    publicacionesMlAPI.products.mockResolvedValueOnce({ data: productsResponse(undefined, { sin_mla_count: 42 }) });
    const { result, rerender } = setup();
    await waitFor(() => expect(result.current.sinMlaCount).toBe(42));
    publicacionesMlAPI.products.mockResolvedValueOnce({ data: productsResponse(undefined, { total: 3 }) });
    rerender({ filters: PAUSED });
    await waitFor(() => expect(result.current.total).toBe(3));
    expect(result.current.sinMlaCount).toBeNull();
  });
});

describe('the in-flight guard', () => {
  it("a late answer of the previous list does not lift the new list's guard for the same page", async () => {
    const old = deferred();
    publicacionesMlAPI.products.mockReturnValueOnce(old.promise).mockReturnValue(new Promise(() => {}));
    const { result, rerender } = setup();
    rerender({ filters: PAUSED }); // the new list asks for the same page ('' at 0) while the old one is pending
    await waitFor(() => expect(publicacionesMlAPI.products).toHaveBeenCalledTimes(2));
    await act(async () => {
      old.resolve({ data: productsResponse() });
      await old.promise;
    });
    act(() => result.current.loadMore('')); // the new page is still pending: asking again must ask for nothing
    expect(publicacionesMlAPI.products).toHaveBeenCalledTimes(2);
  });
});

describe('"Todos" in parts of 500 (filtros S4)', () => {
  // A part of the products: 500 asked, 3 answered, out of 1200; each part's rows are its own.
  const part = (offset, prefix = 'p') =>
    [0, 1, 2].map((i) => ({ key: `${prefix}${offset + i}`, descripcion: `Producto ${offset + i}`, publications_count: 1, params: {} }));
  const answer = (params) => Promise.resolve({ data: productsResponse(part(params.offset), { total: 1200, mla_count: 1500 }) });
  const setupAll = (pageSize = ALL_ROWS) =>
    renderHook(({ filters }) => useProductRows({ filters, pageSize, canSeeSales: true, canSeeMargin: true }), {
      initialProps: { filters: { ...FILTERS, limite: pageSize } },
    });
  const productCalls = () => publicacionesMlAPI.products.mock.calls.map(([params]) => params);
  const labels = (result) => result.current.rows.filter((row) => row.type === 'node').map((row) => row.node.key);

  it('asks 500 at offset 0, the next parts on loadMoreProducts with the same params, appended, until the total', async () => {
    publicacionesMlAPI.products.mockImplementation(answer);
    const { result } = setupAll();
    await waitFor(() => expect(result.current.total).toBe(1200));
    const [first] = productCalls();
    expect(first).toMatchObject({ estado: 'active', orden: 'facturado_30d', dir: 'desc', limit: 500, offset: 0 });
    act(() => result.current.loadMoreProducts());
    await waitFor(() => expect(labels(result)).toEqual(['p0', 'p1', 'p2', 'p500', 'p501', 'p502']));
    act(() => result.current.loadMoreProducts());
    await waitFor(() => expect(labels(result)).toHaveLength(9));
    expect(productCalls()).toEqual([first, { ...first, offset: 500 }, { ...first, offset: 1000, limit: 200 }]);
    // The pager keeps the first part's figures; past the total nothing more is asked.
    expect(result.current.total).toBe(1200);
    expect(result.current.mlaCount).toBe(1500);
    act(() => result.current.loadMoreProducts());
    expect(publicacionesMlAPI.products).toHaveBeenCalledTimes(3);
  });

  it('a filter change starts again at offset 0, and a part of the previous list is never appended', async () => {
    const stale = deferred();
    publicacionesMlAPI.products.mockImplementation((params) =>
      params.estado === 'active' && params.offset === 500 ? stale.promise : answer(params),
    );
    const { result, rerender } = setupAll();
    await waitFor(() => expect(result.current.total).toBe(1200));
    act(() => result.current.loadMoreProducts());
    rerender({ filters: { ...PAUSED, limite: ALL_ROWS } });
    await waitFor(() => expect(productCalls().at(-1)).toMatchObject({ estado: 'paused', limit: 500, offset: 0 }));
    await waitFor(() => expect(labels(result)).toEqual(['p0', 'p1', 'p2']));
    await act(async () => {
      stale.resolve({ data: productsResponse(part(500, 'old'), { total: 1200 }) });
      await stale.promise;
    });
    expect(labels(result)).toEqual(['p0', 'p1', 'p2']);
  });

  it('a page of 50 is one request of 50: loadMoreProducts asks nothing', async () => {
    publicacionesMlAPI.products.mockImplementation(answer);
    const { result } = setupAll(50);
    await waitFor(() => expect(result.current.total).toBe(1200));
    act(() => result.current.loadMoreProducts());
    expect(productCalls()).toEqual([expect.objectContaining({ limit: 50, offset: 0 })]);
  });
});
