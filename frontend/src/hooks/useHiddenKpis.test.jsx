import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import useHiddenKpis from './useHiddenKpis';

const KEY = 'test.hidden-kpis';
const OPTIONS = [
  { id: 'units', label: 'Unidades vendidas' },
  { id: 'gross', label: 'Facturado bruto' },
];
const toggle = (result, id) => act(() => result.current.pickerTable.getAllLeafColumns().find((col) => col.id === id).getToggleVisibilityHandler()());

describe('useHiddenKpis', () => {
  beforeEach(() => localStorage.clear());

  it('shows every KPI with nothing stored (S3)', () => {
    const { result } = renderHook(() => useHiddenKpis(KEY, OPTIONS));
    expect(OPTIONS.every(({ id }) => result.current.isVisible(id))).toBe(true);
  });

  it('hides and shows one KPI at a time, and lists only the given options (S1, S2)', () => {
    const { result } = renderHook(() => useHiddenKpis(KEY, OPTIONS));
    const columns = result.current.pickerTable.getAllLeafColumns();
    expect(columns.map((col) => col.columnDef.header)).toEqual(['Unidades vendidas', 'Facturado bruto']);
    toggle(result, 'gross');
    expect(result.current.isVisible('gross')).toBe(false);
    expect(result.current.isVisible('units')).toBe(true);
    toggle(result, 'gross');
    expect(result.current.isVisible('gross')).toBe(true);
  });

  it('keeps the choice across a reload, per page key (S4)', () => {
    const first = renderHook(() => useHiddenKpis(KEY, OPTIONS));
    toggle(first.result, 'units');
    first.unmount();
    const again = renderHook(() => useHiddenKpis(KEY, OPTIONS));
    expect(again.result.current.isVisible('units')).toBe(false);
    const otherPage = renderHook(() => useHiddenKpis('other.page', OPTIONS));
    expect(otherPage.result.current.isVisible('units')).toBe(true);
  });

  it.each(['not json', '{"units":true}', '[1,2]', 'null'])('falls back to every KPI visible on a stored %s (S4)', (stored) => {
    localStorage.setItem(KEY, stored);
    const { result } = renderHook(() => useHiddenKpis(KEY, OPTIONS));
    expect(OPTIONS.every(({ id }) => result.current.isVisible(id))).toBe(true);
  });
});
