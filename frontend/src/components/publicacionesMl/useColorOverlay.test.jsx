/**
 * useColorOverlay (S8): the colors painted since the rows loaded -- by this screen or by anyone (SSE
 * `producto_color:changed`) -- applied to the layer on show exactly as Productos applies them.
 */
import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import useColorOverlay from './useColorOverlay';

const event = (data) => ({ data: { vista: 'ml', ...data } });

describe('useColorOverlay', () => {
  it("paints the products on the layer on show: the global one's events on the global layer", () => {
    const { result } = renderHook(() => useColorOverlay(''));
    act(() => result.current.apply(event({ is_global: true, equipo_id: 1, item_ids: [77, 78], color: 'rojo' })));
    expect(result.current.colors.get('77')).toEqual({ marcado: 'rojo' });
    expect(result.current.colors.get('78')).toEqual({ marcado: 'rojo' });
  });

  it("a team's events on its layer; the global one's become the hint there; another team's are ignored", () => {
    const { result } = renderHook(() => useColorOverlay('12'));
    act(() => result.current.apply(event({ is_global: false, equipo_id: 12, item_ids: [77], color: 'verde' })));
    act(() => result.current.apply(event({ is_global: true, equipo_id: 1, item_ids: [77], color: 'azul' })));
    act(() => result.current.apply(event({ is_global: false, equipo_id: 13, item_ids: [77], color: 'gris' })));
    expect(result.current.colors.get('77')).toEqual({ marcado: 'verde', hintGlobal: 'azul' });
  });

  it('keeps a cleared color (null) and ignores the Tienda colors', () => {
    const { result } = renderHook(() => useColorOverlay(''));
    act(() => result.current.apply(event({ is_global: true, item_ids: [77], color: null })));
    act(() => result.current.apply(event({ is_global: true, item_ids: [78], color: 'rojo', vista: 'tienda' })));
    expect(result.current.colors.get('77')).toEqual({ marcado: null });
    expect(result.current.colors.has('78')).toBe(false);
  });

  it('starts empty on another layer: its rows are asked again with their own colors', () => {
    const { result, rerender } = renderHook(({ equipo }) => useColorOverlay(equipo), { initialProps: { equipo: '' } });
    act(() => result.current.apply(event({ is_global: true, item_ids: [77], color: 'rojo' })));
    rerender({ equipo: '12' });
    expect(result.current.colors.size).toBe(0);
  });
});
