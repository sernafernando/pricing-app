/**
 * useListPrices (S11): Productos' prices of the products on show, asked to Productos' own listing by id
 * (`GET /productos?item_ids=`), so every figure is the one Productos shows.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import useListPrices from './useListPrices';
import { productosAPI } from '../../services/api';

vi.mock('../../services/api', () => ({ productosAPI: { listar: vi.fn() } }));

const listed = (...products) => ({ data: { productos: products, total: products.length } });

beforeEach(() => {
  vi.clearAllMocks();
  productosAPI.listar.mockResolvedValue(listed({ item_id: 7, precio_lista_ml: 1000 }, { item_id: 9, precio_lista_ml: 2000 }));
});

describe('useListPrices', () => {
  it('asks the listing once for the distinct products on show, and keys the answer by product', async () => {
    const { result } = renderHook(() => useListPrices([9, 7, null, 9], true));
    await waitFor(() => expect(result.current.byId.get(7)).toEqual({ item_id: 7, precio_lista_ml: 1000 }));
    expect(productosAPI.listar).toHaveBeenCalledTimes(1);
    expect(productosAPI.listar).toHaveBeenCalledWith({ item_ids: '7,9', page: 1, page_size: 2 });
    expect(result.current.byId.get(9).precio_lista_ml).toBe(2000);
    expect(result.current.loading).toBe(false);
  });

  it('splits a long page (Todos) into requests of at most 200 products, under the listing cap, and merges them', async () => {
    const ids = Array.from({ length: 450 }, (_, n) => n + 1);
    productosAPI.listar.mockImplementation(({ item_ids }) =>
      Promise.resolve(listed(...item_ids.split(',').map((id) => ({ item_id: Number(id), precio_lista_ml: Number(id) * 10 })))),
    );
    const { result } = renderHook(() => useListPrices(ids, true));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const sizes = productosAPI.listar.mock.calls.map(([params]) => params.item_ids.split(',').length);
    expect(sizes).toEqual([200, 200, 50]);
    expect(productosAPI.listar.mock.calls.map(([params]) => params.page_size)).toEqual([200, 200, 50]);
    expect(result.current.byId.size).toBe(450);
    expect(result.current.byId.get(450).precio_lista_ml).toBe(4500);
  });

  it('one failed part of a long page leaves no prices and says so', async () => {
    const ids = Array.from({ length: 250 }, (_, n) => n + 1);
    productosAPI.listar.mockResolvedValueOnce(listed({ item_id: 1, precio_lista_ml: 10 }));
    productosAPI.listar.mockRejectedValueOnce(new Error('HTTP 500'));
    const { result } = renderHook(() => useListPrices(ids, true));
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.byId.size).toBe(0);
  });

  it('asks nothing when disabled or with no product on show', () => {
    renderHook(() => useListPrices([7], false));
    renderHook(() => useListPrices([null], true));
    expect(productosAPI.listar).not.toHaveBeenCalled();
  });

  it('does not ask again for the same products in another order', async () => {
    const { result, rerender } = renderHook(({ ids }) => useListPrices(ids, true), { initialProps: { ids: [7, 9] } });
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ ids: [9, 7] });
    expect(productosAPI.listar).toHaveBeenCalledTimes(1);
  });

  it('drops a late answer about the products it showed before', async () => {
    let first;
    productosAPI.listar.mockReturnValueOnce(new Promise((resolve) => (first = resolve)));
    productosAPI.listar.mockResolvedValueOnce(listed({ item_id: 9, precio_lista_ml: 2000 }));
    const { result, rerender } = renderHook(({ ids }) => useListPrices(ids, true), { initialProps: { ids: [7] } });
    rerender({ ids: [9] });
    await waitFor(() => expect(result.current.byId.get(9)?.precio_lista_ml).toBe(2000));
    first(listed({ item_id: 7, precio_lista_ml: 1000 }));
    await Promise.resolve();
    expect(result.current.byId.has(7)).toBe(false);
  });

  it('a failed request leaves no prices and says so, never stale ones', async () => {
    productosAPI.listar.mockRejectedValue(new Error('HTTP 500'));
    const { result } = renderHook(() => useListPrices([7], true));
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.byId.size).toBe(0);
    expect(result.current.loading).toBe(false);
  });

  it('keeps the same answer object between renders while nothing changed, so the columns are not rebuilt', async () => {
    const { result, rerender } = renderHook(({ ids }) => useListPrices(ids, true), { initialProps: { ids: [7] } });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const first = result.current;
    rerender({ ids: [7] });
    expect(result.current).toBe(first);
  });

  it("reads them again when the page's list is reloaded (`version`: a panel or bulk write changed prices)", async () => {
    const { result, rerender } = renderHook(({ version }) => useListPrices([7], true, version), { initialProps: { version: 0 } });
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ version: 0 });
    expect(productosAPI.listar).toHaveBeenCalledTimes(1);
    productosAPI.listar.mockResolvedValueOnce(listed({ item_id: 7, precio_lista_ml: 1800 }));
    rerender({ version: 1 });
    // The shown prices stay until the new ones arrive.
    expect(result.current.byId.get(7)?.precio_lista_ml).toBe(1000);
    expect(result.current.loading).toBe(false);
    await waitFor(() => expect(result.current.byId.get(7)?.precio_lista_ml).toBe(1800));
    expect(productosAPI.listar).toHaveBeenCalledTimes(2);
  });
});
