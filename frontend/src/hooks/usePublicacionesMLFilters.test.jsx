/**
 * usePublicacionesMLFilters (publicaciones-ml-vista P11a.T2, S9.1): every
 * filter lives in the URL, so a shared link or a reload shows the same list.
 */
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { usePublicacionesMLFilters, buildItemsParams, PAGE_SIZE } from './usePublicacionesMLFilters';

const setup = (url = '/') => {
  const wrapper = ({ children }) => <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>;
  return renderHook(
    () => ({ hook: usePublicacionesMLFilters(), search: useLocation().search }),
    { wrapper },
  );
};

describe('reading the URL', () => {
  it('has neutral defaults', () => {
    const { result } = setup('/');
    const f = result.current.hook.filters;
    expect(f.q).toBe('');
    expect(f.vista).toBe('publicacion');
    expect(f.estado).toEqual([]);
    expect(f.pagina).toBe(1);
    expect(f.sel).toBe('');
    expect(f.orden).toBe('');
  });

  it('parses every param of the contract', () => {
    const url =
      '/?q=router&vista=agrupado&estado=active,paused&estado_excluir=closed&tiendas=57997,none' +
      '&marcas=TP-LINK,EPSON&categorias=Redes&subcategorias=12,13&pms=4&familia=998' +
      '&tipo=full,catalogo&vinculo=auto&stock=sin_stock&evento=price_changed&evento_desde=7d' +
      '&orden=precio&dir=asc&pagina=3&sel=MLA123&tab=eventos';
    const f = setup(url).result.current.hook.filters;
    expect(f).toMatchObject({
      q: 'router',
      vista: 'agrupado',
      estado: ['active', 'paused'],
      estado_excluir: ['closed'],
      tiendas: ['57997', 'none'],
      marcas: ['TP-LINK', 'EPSON'],
      categorias: ['Redes'],
      subcategorias: ['12', '13'],
      pms: ['4'],
      familia: '998',
      tipo: ['full', 'catalogo'],
      vinculo: ['auto'],
      stock: ['sin_stock'],
      evento: ['price_changed'],
      evento_desde: '7d',
      orden: 'precio',
      dir: 'asc',
      pagina: 3,
      sel: 'MLA123',
      tab: 'eventos',
    });
  });

  it('reads the page size from `limite`, only the sizes the backend allows', () => {
    expect(setup('/?limite=100').result.current.hook.filters.limite).toBe(100);
    expect(setup('/?limite=200').result.current.hook.filters.limite).toBe(PAGE_SIZE);
    expect(setup('/').result.current.hook.filters.limite).toBe(PAGE_SIZE);
  });

  it('falls back on an unknown vista, a bad dir and a bad page', () => {
    const f = setup('/?vista=otra&dir=up&pagina=-2').result.current.hook.filters;
    expect(f.vista).toBe('publicacion');
    expect(f.dir).toBe('');
    expect(f.pagina).toBe(1);
  });
});

describe('writing the URL', () => {
  it('round-trips: what is set is what is read back', () => {
    const { result } = setup('/');
    act(() => result.current.hook.setFilters({ q: 'router', estado: ['active'], tiendas: ['57997', 'none'] }));
    expect(result.current.hook.filters).toMatchObject({
      q: 'router',
      estado: ['active'],
      tiendas: ['57997', 'none'],
    });
    expect(new URLSearchParams(result.current.search).get('tiendas')).toBe('57997,none');
  });

  it('drops a param when it is emptied instead of writing `q=`', () => {
    const { result } = setup('/?q=router&estado=active');
    act(() => result.current.hook.setFilters({ q: '', estado: [] }));
    expect(result.current.search).toBe('');
  });

  it('changing a filter goes back to page 1 and closes the selection', () => {
    const { result } = setup('/?pagina=4&sel=MLA1&tab=eventos&estado=active');
    act(() => result.current.hook.setFilters({ estado: ['paused'] }));
    const params = new URLSearchParams(result.current.search);
    expect(params.has('pagina')).toBe(false);
    expect(params.has('sel')).toBe(false);
    expect(params.has('tab')).toBe(false);
    expect(params.get('estado')).toBe('paused');
  });

  it('changing the page keeps the filters and the selection', () => {
    const { result } = setup('/?estado=active&sel=MLA1');
    act(() => result.current.hook.setFilters({ pagina: 2 }));
    const params = new URLSearchParams(result.current.search);
    expect(params.get('pagina')).toBe('2');
    expect(params.get('estado')).toBe('active');
    expect(params.get('sel')).toBe('MLA1');
  });

  it('sorting goes back to page 1 and keeps the rest', () => {
    const { result } = setup('/?pagina=3&estado=active');
    act(() => result.current.hook.setFilters({ orden: 'precio', dir: 'asc' }));
    const params = new URLSearchParams(result.current.search);
    expect(params.has('pagina')).toBe(false);
    expect(params.get('orden')).toBe('precio');
    expect(params.get('dir')).toBe('asc');
    expect(params.get('estado')).toBe('active');
  });

  it('changing the page size goes back to page 1 and survives a reload', () => {
    const { result } = setup('/?pagina=3&estado=active');
    act(() => result.current.hook.setFilters({ limite: 100 }));
    const params = new URLSearchParams(result.current.search);
    expect(params.get('limite')).toBe('100');
    expect(params.has('pagina')).toBe(false);
    expect(params.get('estado')).toBe('active');
  });

  it('reset clears every param', () => {
    const { result } = setup('/?q=a&estado=active&pagina=2');
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('');
  });
});

describe('buildItemsParams', () => {
  const base = setup('/').result.current.hook.filters;

  it('sends only what is set, csv joined, with limit and offset', () => {
    const params = buildItemsParams({ ...base, q: ' router ', estado: ['active'], tipo: ['full', 'catalogo'], pagina: 3 });
    expect(params).toEqual({ q: 'router', estado: 'active', tipo: 'full,catalogo', limit: PAGE_SIZE, offset: 2 * PAGE_SIZE });
  });

  it('sends the backend vocabulary for "sin tienda"', () => {
    expect(buildItemsParams({ ...base, tiendas: ['57997', 'sin_tienda'] }).tiendas).toBe('57997,none');
  });

  it('maps the sort to orden/dir and never sends view-only params', () => {
    const params = buildItemsParams({ ...base, orden: 'titulo', dir: 'desc', vista: 'agrupado', sel: 'MLA1', tab: 'x' });
    expect(params).toMatchObject({ orden: 'titulo', dir: 'desc' });
    expect(params).not.toHaveProperty('vista');
    expect(params).not.toHaveProperty('sel');
    expect(params).not.toHaveProperty('tab');
    expect(params).not.toHaveProperty('pagina');
  });

  it('uses the page size of the URL', () => {
    expect(buildItemsParams({ ...base, limite: 100, pagina: 2 })).toMatchObject({ limit: 100, offset: 100 });
  });
});
