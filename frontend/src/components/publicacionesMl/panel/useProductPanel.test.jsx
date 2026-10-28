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
/** The list's pages, in order; the escapes' counts (`limit: 1`) find nothing. */
const listPages = (...pages) => {
  const queue = [...pages];
  publicacionesMlAPI.items.mockImplementation((params) => Promise.resolve(params.limit === 1 ? itemsPage([], 0) : queue.shift()));
};
const listCalls = () => publicacionesMlAPI.items.mock.calls.filter(([params]) => params.limit !== 1);

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
    listPages(itemsPage(ids(0, 100), 150), itemsPage(ids(100, 50), 150));
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
    listPages(itemsPage(ids(0, 100), 150), itemsPage(ids(100, 50), 150));
    const { result } = setup(PRODUCT.key);

    await waitFor(() => expect(result.current.items).toHaveLength(100));
    act(() => {
      result.current.loadMore();
      result.current.loadMore();
    });
    await waitFor(() => expect(result.current.items).toHaveLength(150));
    expect(listCalls()).toHaveLength(2);
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
    expect(listCalls()).toHaveLength(1);
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

/**
 * The panel's escapes, Productos' own: "ver todos" lists the product's publications without the page's filters and
 * "Ver eliminadas" adds the deleted ones (`estado=gone`), each count asked as a `total` with `limit: 1`.
 */
describe('ver todos and Ver eliminadas', () => {
  // A filter that is not `estado`, so each of the four scopes is its own request.
  const FILTERED = { ...FILTERS, q: 'archer', estado: [] };
  const NONE = { ...FILTERS, estado: [] };
  const scopeOf = (params) => `${params.q ? 'filtered' : 'all'}${params.estado === 'gone' ? 'Gone' : ''}`;

  /** Serves `/view/items` by scope: `ids` per scope, its `total` the length of its ids. */
  function serve(byScope) {
    publicacionesMlAPI.items.mockImplementation((params) => {
      const all = byScope[scopeOf(params)] ?? [];
      const page = params.limit === 1 ? all.slice(0, 1) : all.slice(params.offset, params.offset + params.limit);
      return Promise.resolve(itemsPage(page, all.length));
    });
  }

  const counts = () => publicacionesMlAPI.items.mock.calls.map(([params]) => params).filter((params) => params.limit === 1);

  beforeEach(() => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([PRODUCT]) });
  });

  it('counts what the filters hide: all the live ones minus the filtered ones, with limit 1', async () => {
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2', 'MLA3'], filteredGone: [], allGone: [] });
    const { result } = setup(PRODUCT.key, FILTERED);

    await waitFor(() => expect(result.current.hiddenCount).toBe(2));
    expect(counts()).toContainEqual({ ...PRODUCT.params, limit: 1, offset: 0 });
    expect(result.current.verTodos).toBe(false);
  });

  it('"ver todos" lists the publications with only the product params', async () => {
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2', 'MLA3'], filteredGone: [], allGone: [] });
    const { result } = setup(PRODUCT.key, FILTERED);
    await waitFor(() => expect(result.current.hiddenCount).toBe(2));

    act(() => result.current.showAll());
    await waitFor(() => expect(result.current.items.map((row) => row.item_id)).toEqual(['MLA1', 'MLA2', 'MLA3']));
    expect(publicacionesMlAPI.items).toHaveBeenLastCalledWith({ ...PRODUCT.params, limit: 100, offset: 0 });
    expect(result.current.verTodos).toBe(true);
    expect(result.current.hiddenCount).toBe(0);
  });

  it('counts the deleted ones of the scope and "Ver eliminadas" adds them after the live ones', async () => {
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2'], filteredGone: ['MLA8'], allGone: ['MLA8', 'MLA9'] });
    const { result } = setup(PRODUCT.key, FILTERED);
    await waitFor(() => expect(result.current.deletedCount).toBe(1));
    expect(counts()).toContainEqual({ q: 'archer', estado: 'gone', ...PRODUCT.params, limit: 1, offset: 0 });

    act(() => result.current.toggleDeleted());
    await waitFor(() => expect(result.current.items.map((row) => row.item_id)).toEqual(['MLA1', 'MLA8']));
    expect(publicacionesMlAPI.items).toHaveBeenLastCalledWith({ q: 'archer', estado: 'gone', ...PRODUCT.params, limit: 100, offset: 0 });
    expect(result.current.showDeleted).toBe(true);
    expect(result.current.hasMore).toBe(false);

    act(() => result.current.toggleDeleted());
    await waitFor(() => expect(result.current.items.map((row) => row.item_id)).toEqual(['MLA1']));
  });

  it('with "Ver eliminadas" on, both counts of "ver todos" take the deleted ones in', async () => {
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2'], filteredGone: ['MLA8'], allGone: ['MLA8', 'MLA9', 'MLA10'] });
    const { result } = setup(PRODUCT.key, FILTERED);
    await waitFor(() => expect(result.current.hiddenCount).toBe(1));

    act(() => result.current.toggleDeleted());
    await waitFor(() => expect(result.current.hiddenCount).toBe(3));
  });

  it('under "ver todos" the deleted count is that of the product without the filters', async () => {
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2'], filteredGone: [], allGone: ['MLA8', 'MLA9'] });
    const { result } = setup(PRODUCT.key, FILTERED);
    await waitFor(() => expect(result.current.hiddenCount).toBe(1));
    expect(result.current.deletedCount).toBe(0);

    act(() => result.current.showAll());
    await waitFor(() => expect(result.current.deletedCount).toBe(2));
  });

  it('says when the scope has only deleted ones', async () => {
    serve({ all: [], allGone: ['MLA8'] });
    const { result } = setup(PRODUCT.key, NONE);
    await waitFor(() => expect(result.current.onlyDeleted).toBe(true));
    expect(result.current.deletedCount).toBe(1);

    act(() => result.current.toggleDeleted());
    await waitFor(() => expect(result.current.items.map((row) => row.item_id)).toEqual(['MLA8']));
    expect(result.current.onlyDeleted).toBe(false);
  });

  it('with no filter and nothing deleted asks the same list and offers nothing', async () => {
    serve({ all: ['MLA1', 'MLA2'], allGone: [] });
    const { result } = setup(PRODUCT.key, NONE);
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await waitFor(() => expect(counts()).toHaveLength(1));

    expect(publicacionesMlAPI.items.mock.calls[0][0]).toEqual({ ...PRODUCT.params, limit: 100, offset: 0 });
    expect(counts()).toEqual([{ estado: 'gone', ...PRODUCT.params, limit: 1, offset: 0 }]);
    expect(result.current).toMatchObject({ hiddenCount: 0, deletedCount: 0, onlyDeleted: false, verTodos: false, showDeleted: false });
  });

  it('a new product or a new filter set turns both escapes off', async () => {
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2'], filteredGone: ['MLA8'], allGone: ['MLA8'] });
    const { result, rerender } = setup(PRODUCT.key, FILTERED);
    await waitFor(() => expect(result.current.hiddenCount).toBe(1));
    act(() => result.current.showAll());
    act(() => result.current.toggleDeleted());
    await waitFor(() => expect(result.current.items).toHaveLength(3));

    rerender({ filters: { ...FILTERED, q: 'router' }, productKey: PRODUCT.key });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current).toMatchObject({ verTodos: false, showDeleted: false });

    act(() => result.current.showAll());
    rerender({ filters: { ...FILTERED, q: 'router' }, productKey: WITHOUT_PRODUCT.key });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.verTodos).toBe(false);
  });

  it("drops the list and the counts asked before a toggle or for another product", async () => {
    const lateList = deferred();
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2'], filteredGone: [], allGone: [] });
    publicacionesMlAPI.items.mockReturnValueOnce(lateList.promise);
    const { result, rerender } = setup(PRODUCT.key, FILTERED);
    await waitFor(() => expect(result.current.summary?.key).toBe(PRODUCT.key));

    act(() => result.current.showAll());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await act(async () => lateList.resolve(itemsPage(['MLA1'], 1)));
    expect(result.current.items.map((row) => row.item_id)).toEqual(['MLA1', 'MLA2']);

    // The next filter set asks its count of the publications without filters, which answers only after another one.
    const oldCount = deferred();
    serve({ filtered: ['MLA1'], all: ['MLA1', 'MLA2'], filteredGone: [], allGone: [] });
    const answer = publicacionesMlAPI.items.getMockImplementation();
    let held = false;
    publicacionesMlAPI.items.mockImplementation((params) => {
      if (!held && params.limit === 1 && !params.q && !params.estado) {
        held = true;
        return oldCount.promise;
      }
      return answer(params);
    });
    rerender({ filters: { ...FILTERED, q: 'router' }, productKey: PRODUCT.key });
    await waitFor(() => expect(held).toBe(true));
    rerender({ filters: { ...FILTERED, q: 'otro' }, productKey: PRODUCT.key });
    await waitFor(() => expect(result.current.hiddenCount).toBe(1));
    await act(async () => oldCount.resolve(itemsPage(['MLA1'], 0)));
    expect(result.current.hiddenCount).toBe(1);
  });
});
