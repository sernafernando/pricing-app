/**
 * useProductRows: what the Producto view's pager and in-flight guard say while lists change under them. A new list
 * never shows the previous list's total (loading or failed), and a late answer of an old list never lifts the guard
 * of the same page in the new one.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import useProductRows from './useProductRows';
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
