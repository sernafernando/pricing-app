import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import useProductSelection from './useProductSelection';

const setup = (order = [10, 20, 30, 40]) => renderHook(({ ids }) => useProductSelection(ids), { initialProps: { ids: order } });
const checked = (result) => [...result.current.checked].sort((a, b) => a - b);

describe('useProductSelection (S12d, Productos useProductosSeleccion)', () => {
  it('a plain toggle checks and unchecks one product', () => {
    const { result } = setup();
    act(() => result.current.onToggle(20));
    expect(checked(result)).toEqual([20]);
    act(() => result.current.onToggle(20));
    expect(checked(result)).toEqual([]);
  });

  it('Shift checks every product between the last one toggled and this one, in the rows order', () => {
    const { result } = setup();
    act(() => result.current.onToggle(40));
    act(() => result.current.onToggle(20, true));
    expect(checked(result)).toEqual([20, 30, 40]);
  });

  it('Shift with nothing toggled before is a plain toggle', () => {
    const { result } = setup();
    act(() => result.current.onToggle(30, true));
    expect(checked(result)).toEqual([30]);
  });

  it('Shift from a product that is no longer on show is a plain toggle', () => {
    const { result, rerender } = setup();
    act(() => result.current.onToggle(10));
    rerender({ ids: [20, 30, 40] });
    act(() => result.current.onToggle(40, true));
    expect(checked(result)).toEqual([10, 40]);
  });

  it('a product repeated on the page (two publications of it) counts once in the range', () => {
    const { result } = setup([10, 20, 10, 30]);
    act(() => result.current.onToggle(10));
    act(() => result.current.onToggle(30, true));
    expect(checked(result)).toEqual([10, 20, 30]);
  });

  it('extendTo (Shift+arrows) checks the range from the last product toggled, or just this one, and never unchecks', () => {
    const { result, rerender } = setup();
    act(() => result.current.onToggle(10));
    act(() => result.current.extendTo(30));
    expect(checked(result)).toEqual([10, 20, 30]);
    // The range start went off the page (another filter): the product moved to is checked, the checked one stays.
    rerender({ ids: [50, 60, 70] });
    act(() => result.current.onToggle(60));
    rerender({ ids: [30, 40] });
    act(() => result.current.extendTo(30));
    expect(checked(result)).toEqual([10, 20, 30, 60]);
    act(() => result.current.extendTo(40));
    expect(checked(result)).toEqual([10, 20, 30, 40, 60]);
  });

  it('selecting the page checks every product on show and keeps the ones checked elsewhere', () => {
    const { result, rerender } = setup([1, 2]);
    act(() => result.current.onToggle(1));
    rerender({ ids: [10, 20, null] });
    expect(result.current.pageState).toBe('none');
    act(() => result.current.togglePage());
    expect(checked(result)).toEqual([1, 10, 20]);
    expect(result.current.pageState).toBe('all');
  });

  it('with the whole page checked, selecting the page unchecks it and keeps the rest', () => {
    const { result, rerender } = setup([1, 2]);
    act(() => result.current.onToggle(1));
    rerender({ ids: [10, 20] });
    act(() => result.current.onToggle(10));
    expect(result.current.pageState).toBe('some');
    act(() => result.current.togglePage());
    act(() => result.current.togglePage());
    expect(checked(result)).toEqual([1]);
  });

  it('a page with no product has nothing to select', () => {
    const { result } = setup([null, null]);
    expect(result.current.pageState).toBe('empty');
    act(() => result.current.togglePage());
    expect(checked(result)).toEqual([]);
  });

  it('clear unchecks everything and forgets the range start', () => {
    const { result } = setup();
    act(() => result.current.onToggle(10));
    act(() => result.current.clear());
    act(() => result.current.onToggle(30, true));
    expect(checked(result)).toEqual([30]);
  });
});
