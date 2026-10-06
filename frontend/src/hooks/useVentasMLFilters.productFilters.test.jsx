/**
 * Tests for the `marcas` / `categorias` / `subcategorias` / `pms` URL round-trip added to
 * `useVentasMLFilters` by `ventas-ml-filtros-producto`.
 *
 * Follows the same convention already covered for `q` on this hook: CSV
 * params, set when non-empty, deleted (never `param=`) when cleared.
 */
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useVentasMLFilters } from './useVentasMLFilters';

function wrapper({ children }) {
  return <MemoryRouter initialEntries={['/']}>{children}</MemoryRouter>;
}

describe('useVentasMLFilters — product filters URL round-trip', () => {
  it('reads empty arrays when no product filter params are present', () => {
    const { result } = renderHook(() => useVentasMLFilters(), { wrapper });
    expect(result.current.productFilters).toEqual({ marcas: [], categorias: [], subcategorias: [], pms: [] });
  });

  it('parses marcas/subcategorias/pms from the URL on mount', () => {
    function wrapperWithParams({ children }) {
      return (
        <MemoryRouter initialEntries={['/?marcas=Sony,LG&categorias=Audio,Video&subcategorias=3,7&pms=10']}>
          {children}
        </MemoryRouter>
      );
    }
    const { result } = renderHook(() => useVentasMLFilters(), { wrapper: wrapperWithParams });
    expect(result.current.productFilters).toEqual({
      marcas: ['Sony', 'LG'],
      categorias: ['Audio', 'Video'],
      subcategorias: [3, 7],
      pms: [10],
    });
  });

  it('setProductFilters writes CSV params to the URL', () => {
    const { result } = renderHook(() => useVentasMLFilters(), { wrapper });
    act(() => {
      result.current.setProductFilters({ marcas: ['Sony'], categorias: ['Audio'], subcategorias: [3], pms: [10, 20] });
    });
    expect(result.current.productFilters).toEqual({
      marcas: ['Sony'],
      categorias: ['Audio'],
      subcategorias: [3],
      pms: [10, 20],
    });
  });

  it('clearProductFilters removes all four params instead of writing empty strings', () => {
    function wrapperWithParams({ children }) {
      return (
        <MemoryRouter initialEntries={['/?marcas=Sony&categorias=Audio&subcategorias=3&pms=10']}>
          {children}
        </MemoryRouter>
      );
    }
    const { result } = renderHook(() => useVentasMLFilters(), { wrapper: wrapperWithParams });
    act(() => {
      result.current.clearProductFilters();
    });
    expect(result.current.productFilters).toEqual({ marcas: [], categorias: [], subcategorias: [], pms: [] });
  });
});
