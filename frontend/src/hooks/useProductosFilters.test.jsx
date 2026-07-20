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

describe('useProductosFilters — promo filter wiring', () => {
  it('defaults filtroPromoTipos to [] and filtroPromoEstado to disponible', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    expect(result.current.filtroPromoTipos).toEqual([]);
    expect(result.current.filtroPromoEstado).toBe('disponible');
  });

  it('construirFiltrosParams omits promo_tipos/promo_estado when no types selected', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    const params = result.current.construirFiltrosParams();
    expect(params.promo_tipos).toBeUndefined();
    expect(params.promo_estado).toBeUndefined();
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

  it('construirFiltrosParams reflects filtroPromoEstado = aplicada', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoTipos(['SMART']);
      result.current.setFiltroPromoEstado('aplicada');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.promo_tipos).toBe('SMART');
    expect(params.promo_estado).toBe('aplicada');
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

describe('useProductosFilters — promo aplicación tri-state filter', () => {
  it('defaults filtroPromoAplicacion to null and omits both booleans', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    expect(result.current.filtroPromoAplicacion).toBeNull();
    const params = result.current.construirFiltrosParams();
    expect(params.con_promo_aplicada).toBeUndefined();
    expect(params.con_promo_sin_aplicar).toBeUndefined();
  });

  it('construirFiltrosParams sends con_promo_aplicada=true when filtroPromoAplicacion is "aplicada"', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoAplicacion('aplicada');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.con_promo_aplicada).toBe(true);
    expect(params.con_promo_sin_aplicar).toBeUndefined();
  });

  it('construirFiltrosParams sends con_promo_sin_aplicar=true when filtroPromoAplicacion is "sin_aplicar"', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoAplicacion('sin_aplicar');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.con_promo_sin_aplicar).toBe(true);
    expect(params.con_promo_aplicada).toBeUndefined();
  });

  it('loadFiltersFromURL round-trips promo_aplicacion from the URL', () => {
    const { result } = renderHook(() => useProductosFilters(), {
      wrapper: wrapperWithURL(['/?promo_aplicacion=aplicada']),
    });

    expect(result.current.filtroPromoAplicacion).toBe('aplicada');
  });

  it('limpiarTodosFiltros resets filtroPromoAplicacion to null', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoAplicacion('sin_aplicar');
    });
    act(() => {
      result.current.limpiarTodosFiltros();
    });

    expect(result.current.filtroPromoAplicacion).toBeNull();
  });

  it('does not regress the existing promo_tipos Avanzados filter', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPromoTipos(['SMART']);
      result.current.setFiltroPromoAplicacion('aplicada');
    });

    const params = result.current.construirFiltrosParams();
    expect(params.promo_tipos).toBe('SMART');
    expect(params.promo_estado).toBe('disponible');
    expect(params.con_promo_aplicada).toBe(true);
  });
});
