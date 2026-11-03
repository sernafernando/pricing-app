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

  it('starts empty when the rows are asked again for other filters: they bring their own colors', () => {
    const { result, rerender } = renderHook(({ rows }) => useColorOverlay('', rows), { initialProps: { rows: 'a' } });
    act(() => result.current.apply(event({ is_global: true, item_ids: [77], color: 'rojo' })));
    expect(result.current.colors.size).toBe(1);
    rerender({ rows: 'b' });
    expect(result.current.colors.size).toBe(0);
  });

  it("paints a publication on its own (publicacion_color:changed, by MLA), apart from the products' colors", () => {
    const { result } = renderHook(() => useColorOverlay('12'));
    act(() => result.current.applyOwn({ data: { is_global: false, equipo_id: 12, item_ids: ['MLA4'], color: 'azul' } }));
    act(() => result.current.applyOwn({ data: { is_global: true, equipo_id: 1, item_ids: ['MLA4'], color: null } }));
    act(() => result.current.applyOwn({ data: { is_global: false, equipo_id: 13, item_ids: ['MLA5'], color: 'gris' } }));
    expect(result.current.own.get('MLA4')).toEqual({ marcado: 'azul', hintGlobal: null });
    expect(result.current.own.has('MLA5')).toBe(false);
    expect(result.current.colors.size).toBe(0);
  });

  it('forgets the own colors with the rest on another layer or other rows', () => {
    const { result, rerender } = renderHook(({ rows }) => useColorOverlay('', rows), { initialProps: { rows: 'a' } });
    act(() => result.current.applyOwn({ data: { is_global: true, item_ids: ['MLA4'], color: 'rojo' } }));
    rerender({ rows: 'b' });
    expect(result.current.own.size).toBe(0);
  });
});
