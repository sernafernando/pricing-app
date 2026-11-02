import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import useRowSelection, { productKey, publicationKey } from './useRowSelection';

// Publication rows: id N is the publication `MLA<N>` of product N * 100; a null id is a row that cannot be checked.
const row = (id) => (id == null ? { key: null, productId: null, itemId: null } : { key: publicationKey(`MLA${id}`), productId: id * 100, itemId: `MLA${id}` });
const setup = (order = [10, 20, 30, 40]) =>
  renderHook(({ ids }) => useRowSelection(ids.map(row)), { initialProps: { ids: order } });
const key = (id) => publicationKey(`MLA${id}`);
const checked = (result) => [...result.current.checked.keys()].map((k) => Number(k.slice(5))).sort((a, b) => a - b);

describe('useRowSelection (S12d, Productos useProductosSeleccion; seleccion-por-publicacion S1)', () => {
  it('a plain toggle checks and unchecks one publication', () => {
    const { result } = setup();
    act(() => result.current.onToggle(row(20)));
    expect(checked(result)).toEqual([20]);
    act(() => result.current.onToggle(row(20)));
    expect(checked(result)).toEqual([]);
  });

  it('Shift checks every row between the last one toggled and this one, in the rows order', () => {
    const { result } = setup();
    act(() => result.current.onToggle(row(40)));
    act(() => result.current.onToggle(row(20), true));
    expect(checked(result)).toEqual([20, 30, 40]);
  });

  it('Shift with nothing toggled before is a plain toggle', () => {
    const { result } = setup();
    act(() => result.current.onToggle(row(30), true));
    expect(checked(result)).toEqual([30]);
  });

  it('Shift from a row that is no longer on show is a plain toggle', () => {
    const { result, rerender } = setup();
    act(() => result.current.onToggle(row(10)));
    rerender({ ids: [20, 30, 40] });
    act(() => result.current.onToggle(row(40), true));
    expect(checked(result)).toEqual([10, 40]);
  });

  it('a row repeated on the page counts once in the range', () => {
    const { result } = setup([10, 20, 10, 30]);
    act(() => result.current.onToggle(row(10)));
    act(() => result.current.onToggle(row(30), true));
    expect(checked(result)).toEqual([10, 20, 30]);
  });

  it('extendTo (Shift+arrows) checks the range from the last row toggled, or just this one, and never unchecks', () => {
    const { result, rerender } = setup();
    act(() => result.current.onToggle(row(10)));
    act(() => result.current.extendTo(key(30)));
    expect(checked(result)).toEqual([10, 20, 30]);
    // The range start went off the page (another filter): the product moved to is checked, the checked one stays.
    rerender({ ids: [50, 60, 70] });
    act(() => result.current.onToggle(row(60)));
    rerender({ ids: [30, 40] });
    act(() => result.current.extendTo(key(30)));
    expect(checked(result)).toEqual([10, 20, 30, 60]);
    act(() => result.current.extendTo(key(40)));
    expect(checked(result)).toEqual([10, 20, 30, 40, 60]);
  });

  it('selecting the page checks every row on show and keeps the ones checked elsewhere', () => {
    const { result, rerender } = setup([1, 2]);
    act(() => result.current.onToggle(row(1)));
    rerender({ ids: [10, 20, null] });
    expect(result.current.pageState).toBe('none');
    act(() => result.current.togglePage());
    expect(checked(result)).toEqual([1, 10, 20]);
    expect(result.current.pageState).toBe('all');
  });

  it('with the whole page checked, selecting the page unchecks it and keeps the rest', () => {
    const { result, rerender } = setup([1, 2]);
    act(() => result.current.onToggle(row(1)));
    rerender({ ids: [10, 20] });
    act(() => result.current.onToggle(row(10)));
    expect(result.current.pageState).toBe('some');
    act(() => result.current.togglePage());
    act(() => result.current.togglePage());
    expect(checked(result)).toEqual([1]);
  });

  it('counts the checked rows that are not on show', () => {
    const { result, rerender } = setup([10, 20]);
    act(() => result.current.togglePage());
    expect(result.current.offPageCount).toBe(0);
    rerender({ ids: [20, 30] });
    expect(result.current.offPageCount).toBe(1);
  });

  it('a page with no checkable row has nothing to select', () => {
    const { result } = setup([null, null]);
    expect(result.current.pageState).toBe('empty');
    act(() => result.current.togglePage());
    expect(checked(result)).toEqual([]);
  });

  it('clear unchecks everything and forgets the range start', () => {
    const { result } = setup();
    act(() => result.current.onToggle(row(10)));
    act(() => result.current.clear());
    act(() => result.current.onToggle(row(30), true));
    expect(checked(result)).toEqual([30]);
  });

  it('the products behind the checked rows count once each, and the publications are listed', () => {
    const order = [
      { key: publicationKey('MLA1'), productId: 7, itemId: 'MLA1' },
      { key: publicationKey('MLA2'), productId: 7, itemId: 'MLA2' },
      { key: publicationKey('MLA3'), productId: null, itemId: 'MLA3' },
      { key: productKey(8), productId: 8, itemId: null },
    ];
    const { result } = renderHook(() => useRowSelection(order));
    act(() => result.current.togglePage());
    expect([...result.current.productIds].sort()).toEqual([7, 8]);
    expect(result.current.itemIds).toEqual(['MLA1', 'MLA2', 'MLA3']);
    act(() => result.current.onToggle(order[0]));
    expect([...result.current.productIds].sort()).toEqual([7, 8]);
    expect(result.current.itemIds).toEqual(['MLA2', 'MLA3']);
  });

  it('a checked row keeps its product and publication once it is off the page', () => {
    const { result, rerender } = setup([10]);
    act(() => result.current.onToggle(row(10)));
    rerender({ ids: [20] });
    expect([...result.current.productIds]).toEqual([1000]);
    expect(result.current.itemIds).toEqual(['MLA10']);
  });

  it('a checked row on show reads its product from the page, so a relinked publication resolves to its new product', () => {
    const { result, rerender } = renderHook(({ order }) => useRowSelection(order), {
      initialProps: { order: [{ key: key(10), productId: 4101, itemId: 'MLA10' }] },
    });
    act(() => result.current.onToggle({ key: key(10), productId: 4101, itemId: 'MLA10' }));
    rerender({ order: [{ key: key(10), productId: 4102, itemId: 'MLA10' }] });
    expect([...result.current.productIds]).toEqual([4102]);
    rerender({ order: [{ key: key(10), productId: null, itemId: 'MLA10' }] });
    expect([...result.current.productIds]).toEqual([]);
    expect(result.current.itemIds).toEqual(['MLA10']);
  });

  it('a product row with no product has no key, and selecting the page leaves it unchecked', () => {
    expect(productKey(null)).toBeNull();
    const { result } = setup([10, null]);
    act(() => result.current.togglePage());
    expect([...result.current.checked.keys()]).toEqual([key(10)]);
    expect(result.current.pageState).toBe('all');
  });
});
