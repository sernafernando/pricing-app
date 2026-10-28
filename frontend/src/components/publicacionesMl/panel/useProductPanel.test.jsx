/**
 * useProductPanel: what the product panel asks for one product row of the Producto view. Its summary is that row of
 * `/view/products` under the page's filters, its publications the same `/view/items` pages opening the row asks, and
 * an answer about a product the panel no longer shows never lands.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import useProductPanel from './useProductPanel';
import { publicacionesMlAPI } from '../../../services/api';
import { PRODUCT_ROWS, productsResponse } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
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
  pagina: 3,
  limite: 50,
  sel: '',
};
const [PRODUCT, , WITHOUT_PRODUCT] = PRODUCT_ROWS;

const itemsPage = (ids, total) => ({ data: { items: ids.map((item_id) => ({ item_id })), total } });
const ids = (from, count) => Array.from({ length: count }, (_, i) => `MLA${from + i}`);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const setup = (productKey, filters = FILTERS) =>
  renderHook(({ filters: f, productKey: key }) => useProductPanel(f, key), { initialProps: { filters, productKey } });

beforeEach(() => {
  publicacionesMlAPI.products.mockReset();
  publicacionesMlAPI.items.mockReset();
});

describe('useProductPanel', () => {
  it("asks the product's row under the page's filters, one row from the start, then its publications", async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([PRODUCT]) });
    publicacionesMlAPI.items.mockResolvedValue(itemsPage(['MLA1', 'MLA2'], 2));
    const { result } = setup(PRODUCT.key);

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(publicacionesMlAPI.products).toHaveBeenCalledTimes(1);
    const asked = publicacionesMlAPI.products.mock.calls[0][0];
    expect(asked).toMatchObject({ estado: 'active', producto: PRODUCT.key, limit: 1, offset: 0 });
    expect(asked).not.toHaveProperty('sin_producto');
    expect(result.current.summary).toMatchObject({ key: PRODUCT.key, label: PRODUCT.descripcion, count: PRODUCT.publications_count });
    expect(publicacionesMlAPI.items).toHaveBeenCalledWith({ estado: 'active', ...PRODUCT.params, limit: 100, offset: 0 });
    expect(result.current.items.map((row) => row.item_id)).toEqual(['MLA1', 'MLA2']);
    expect(result.current.hasMore).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('asks the "Sin producto" row with sin_producto, never a producto id', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([WITHOUT_PRODUCT]) });
    publicacionesMlAPI.items.mockResolvedValue(itemsPage(['MLA9'], 1));
    const { result } = setup(WITHOUT_PRODUCT.key);

    await waitFor(() => expect(result.current.loading).toBe(false));
    const asked = publicacionesMlAPI.products.mock.calls[0][0];
    expect(asked).toMatchObject({ sin_producto: true, limit: 1, offset: 0 });
    expect(asked).not.toHaveProperty('producto');
    expect(publicacionesMlAPI.items).toHaveBeenCalledWith(expect.objectContaining({ sin_producto: 'true', offset: 0 }));
  });

  it('pages the publications 100 at a time and "loadMore" asks from where it is', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([PRODUCT]) });
    publicacionesMlAPI.items
      .mockResolvedValueOnce(itemsPage(ids(0, 100), 150))
      .mockResolvedValueOnce(itemsPage(ids(100, 50), 150));
    const { result } = setup(PRODUCT.key);

    await waitFor(() => expect(result.current.items).toHaveLength(100));
    expect(result.current.hasMore).toBe(true);
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.items).toHaveLength(150));
    expect(publicacionesMlAPI.items).toHaveBeenLastCalledWith(expect.objectContaining({ ...PRODUCT.params, limit: 100, offset: 100 }));
    expect(result.current.hasMore).toBe(false);
  });

  it('two "loadMore" calls in the same tick ask for the next page once', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([PRODUCT]) });
    publicacionesMlAPI.items
      .mockResolvedValueOnce(itemsPage(ids(0, 100), 150))
      .mockResolvedValueOnce(itemsPage(ids(100, 50), 150));
    const { result } = setup(PRODUCT.key);

    await waitFor(() => expect(result.current.items).toHaveLength(100));
    act(() => {
      result.current.loadMore();
      result.current.loadMore();
    });
    await waitFor(() => expect(result.current.items).toHaveLength(150));
    expect(publicacionesMlAPI.items).toHaveBeenCalledTimes(2);
  });

  it("drops a late answer about the product it showed before", async () => {
    const old = deferred();
    publicacionesMlAPI.products.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ data: productsResponse([WITHOUT_PRODUCT]) });
    publicacionesMlAPI.items.mockResolvedValue(itemsPage(['MLA9'], 1));
    const { result, rerender } = setup(PRODUCT.key);

    rerender({ filters: FILTERS, productKey: WITHOUT_PRODUCT.key });
    await waitFor(() => expect(result.current.summary?.key).toBe(WITHOUT_PRODUCT.key));
    await act(async () => old.resolve({ data: productsResponse([PRODUCT]) }));
    expect(result.current.summary.key).toBe(WITHOUT_PRODUCT.key);
    expect(publicacionesMlAPI.items).toHaveBeenCalledTimes(1);
  });

  it('a filter change asks again; a change of the selection does not', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([PRODUCT]) });
    publicacionesMlAPI.items.mockResolvedValue(itemsPage(['MLA1'], 1));
    const { result, rerender } = setup(PRODUCT.key);
    await waitFor(() => expect(result.current.loading).toBe(false));

    rerender({ filters: { ...FILTERS, sel: 'MLA1' }, productKey: PRODUCT.key });
    expect(publicacionesMlAPI.products).toHaveBeenCalledTimes(1);
    rerender({ filters: { ...FILTERS, estado: ['paused'] }, productKey: PRODUCT.key });
    await waitFor(() => expect(publicacionesMlAPI.products).toHaveBeenCalledTimes(2));
    expect(publicacionesMlAPI.products.mock.calls[1][0]).toMatchObject({ estado: 'paused', producto: PRODUCT.key });
  });

  it('keeps the error of a failed request, and reload asks again', async () => {
    const failure = new Error('boom');
    publicacionesMlAPI.products.mockRejectedValueOnce(failure).mockResolvedValueOnce({ data: productsResponse([PRODUCT]) });
    publicacionesMlAPI.items.mockResolvedValue(itemsPage(['MLA1'], 1));
    const { result } = setup(PRODUCT.key);

    await waitFor(() => expect(result.current.error).toBe(failure));
    expect(result.current.loading).toBe(false);
    expect(result.current.summary).toBeNull();
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.summary?.key).toBe(PRODUCT.key));
    expect(result.current.error).toBeNull();
  });

  it('keeps the error of a failed page of publications', async () => {
    const failure = new Error('items down');
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([PRODUCT]) });
    publicacionesMlAPI.items.mockRejectedValue(failure);
    const { result } = setup(PRODUCT.key);

    await waitFor(() => expect(result.current.error).toBe(failure));
    expect(result.current.loading).toBe(false);
    expect(result.current.summary?.key).toBe(PRODUCT.key);
  });

  it('asks nothing without a product, and no publications for a product the filters leave out', async () => {
    const { result } = setup('');
    expect(result.current).toMatchObject({ summary: null, items: [], loading: false, error: null, hasMore: false });
    expect(publicacionesMlAPI.products).not.toHaveBeenCalled();

    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([]) });
    const other = setup('777');
    await waitFor(() => expect(other.result.current.loading).toBe(false));
    expect(other.result.current.summary).toBeNull();
    expect(publicacionesMlAPI.items).not.toHaveBeenCalled();
  });
});

describe("a Sin MLA product (Productos' Sin MLA)", () => {
  it('asks its row as one product among the products without MLA, which the backend takes as a product filter', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([PRODUCT], { total: 1 }) });
    publicacionesMlAPI.items.mockResolvedValue(itemsPage([], 0));
    setup(PRODUCT.key, { ...FILTERS, estado: [], mla: 'sin_mla' });
    await waitFor(() => expect(publicacionesMlAPI.products).toHaveBeenCalled());
    expect(publicacionesMlAPI.products.mock.calls[0][0]).toEqual({
      con_mla: false,
      producto: PRODUCT.key,
      orden: 'titulo',
      dir: 'asc',
      limit: 1,
      offset: 0,
    });
  });
});
