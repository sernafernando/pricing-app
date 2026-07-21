import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useProductosFilters } from './useProductosFilters';

function wrapper({ children }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

function wrapperWithURL(initialEntries) {
  return function URLWrapper({ children }) {
    return <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>;
  };
}

describe('useProductosFilters — unified promo filter (types + tri-state estado)', () => {
  it('defaults filtroPromoTipos to [] and filtroPromoEstado to disponible, and does not expose filtroPromoAplicacion', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    expect(result.current.filtroPromoTipos).toEqual([]);
    expect(result.current.filtroPromoEstado).toBe('disponible');
    expect(result.current.filtroPromoAplicacion).toBeUndefined();
    expect(result.current.setFiltroPromoAplicacion).toBeUndefined();
  });

  it('construirFiltrosParams omits all promo params when no types selected and estado is disponible (default/all)', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    const params = result.current.construirFiltrosParams();
    expect(params.promo_tipos).toBeUndefined();
    expect(params.promo_estado).toBeUndefined();
    expect(params.con_promo_aplicada).toBeUndefined();
    expect(params.con_promo_sin_aplicar).toBeUndefined();
  });

  it('construirFiltrosParams sends comma-joined promo_tipos + promo_estado when types selected', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoTipos(['SMART', 'DEAL']);
    });

    const params = result.current.construirFiltrosParams();
    expect(params.promo_tipos).toBe('SMART,DEAL');
    expect(params.promo_estado).toBe('disponible');
  });

  it('construirFiltrosParams reflects filtroPromoEstado = aplicada with types selected', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoTipos(['SMART']);
      result.current.setFiltroPromoEstado('aplicada');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.promo_tipos).toBe('SMART');
    expect(params.promo_estado).toBe('aplicada');
    expect(params.con_promo_aplicada).toBeUndefined();
  });

  it('construirFiltrosParams reflects filtroPromoEstado = sin_aplicar with types selected', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoTipos(['DEAL']);
      result.current.setFiltroPromoEstado('sin_aplicar');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.promo_tipos).toBe('DEAL');
    expect(params.promo_estado).toBe('sin_aplicar');
  });

  it('construirFiltrosParams sends legacy con_promo_aplicada=true when NO type selected and estado is aplicada (backend no-type fallback)', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoEstado('aplicada');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.con_promo_aplicada).toBe(true);
    expect(params.con_promo_sin_aplicar).toBeUndefined();
    expect(params.promo_tipos).toBeUndefined();
    expect(params.promo_estado).toBeUndefined();
  });

  it('construirFiltrosParams sends legacy con_promo_sin_aplicar=true when NO type selected and estado is sin_aplicar (backend no-type fallback)', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoEstado('sin_aplicar');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.con_promo_sin_aplicar).toBe(true);
    expect(params.con_promo_aplicada).toBeUndefined();
  });

  it('loadFiltersFromURL round-trips promo_tipos/promo_estado from the URL', () => {
    const { result } = renderHook(() => useProductosFilters(), {
      wrapper: wrapperWithURL(['/?promo_tipos=SMART,DEAL&promo_estado=aplicada']),
    });

    expect(result.current.filtroPromoTipos).toEqual(['SMART', 'DEAL']);
    expect(result.current.filtroPromoEstado).toBe('aplicada');
  });

  it('limpiarTodosFiltros resets promo filter state', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoTipos(['SMART']);
      result.current.setFiltroPromoEstado('aplicada');
    });
    act(() => {
      result.current.limpiarTodosFiltros();
    });

    expect(result.current.filtroPromoTipos).toEqual([]);
    expect(result.current.filtroPromoEstado).toBe('disponible');
  });

  it('limpiarFiltros (advanced-panel reset) resets promo filter state too', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoTipos(['SMART']);
      result.current.setFiltroPromoEstado('sin_aplicar');
    });
    act(() => {
      result.current.limpiarFiltros();
    });

    expect(result.current.filtroPromoTipos).toEqual([]);
    expect(result.current.filtroPromoEstado).toBe('disponible');
  });

  it('is combinable with an existing filter (marcas) without interference', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setMarcasSeleccionadas(['acme']);
      result.current.setFiltroPromoTipos(['DOD']);
    });

    const params = result.current.construirFiltrosParams();
    expect(params.marcas).toBe('acme');
    expect(params.promo_tipos).toBe('DOD');
    expect(params.promo_estado).toBe('disponible');
  });
});
