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

describe('useProductosFilters — limpiarTodosFiltros clears every filter', () => {
  it('clears the official-store filter', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => result.current.setFiltroTiendaOficial('2645'));
    expect(result.current.filtroTiendaOficial).toBe('2645');

    act(() => result.current.limpiarTodosFiltros());
    expect(result.current.filtroTiendaOficial).toBeNull();
  });

  it('leaves no filtro* state behind — guards every future filter', () => {
    // The official-store filter shipped without a line in limpiarTodosFiltros,
    // so "Limpiar" silently kept filtering. Rather than pin that one field,
    // this asserts the invariant: every `filtro*` value the hook exposes must
    // come back to a falsy/empty state. A new filter added without its reset
    // line fails here instead of reaching a user.
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroTiendaOficial('2645');
      result.current.setFiltroStock('con_stock');
      result.current.setFiltroPrecio('con_precio');
      result.current.setFiltroRebate('si');
      result.current.setFiltroOferta('si');
      result.current.setFiltroWebTransf('si');
      result.current.setFiltroTiendaNube('con_descuento');
      result.current.setFiltroMarkupClasica('bajo');
      result.current.setFiltroMarkupRebate('bajo');
      result.current.setFiltroMarkupOferta('bajo');
      result.current.setFiltroMarkupWebTransf('bajo');
      result.current.setFiltroOutOfCards('si');
      result.current.setFiltroMLA('con_mla');
      result.current.setFiltroEstadoMLA('activa');
      result.current.setFiltroNuevos('ultimos_7_dias');
      result.current.setFiltroPromoTipos(['DEAL']);
      result.current.setFiltroPromoEstado('aplicada');
      result.current.setMarcasSeleccionadas(['ACME']);
      result.current.setSubcategoriasSeleccionadas(['SUB']);
      result.current.setPmsSeleccionados([1]);
      result.current.setColoresSeleccionados(['rojo']);
    });

    act(() => result.current.limpiarTodosFiltros());

    // 'todos' and 'disponible' are this hook's "no filter" sentinels.
    const NEUTRAL = new Set([null, undefined, '', 'todos', 'disponible']);
    const leftovers = Object.entries(result.current)
      .filter(([key]) => key.startsWith('filtro') && !key.startsWith('filtros'))
      .filter(([, value]) => {
        if (Array.isArray(value)) return value.length > 0;
        if (typeof value === 'function') return false;
        return !NEUTRAL.has(value);
      })
      .map(([key, value]) => `${key}=${JSON.stringify(value)}`);

    expect(leftovers).toEqual([]);
    expect(result.current.marcasSeleccionadas).toEqual([]);
    expect(result.current.subcategoriasSeleccionadas).toEqual([]);
    expect(result.current.pmsSeleccionados).toEqual([]);
    expect(result.current.coloresSeleccionados).toEqual([]);
  });
});

describe('useProductosFilters — after clearing, no filter reaches the API', () => {
  const setEverything = (result) => {
    act(() => {
      result.current.setSearchInput('taladro');
      result.current.setFiltroStock('con_stock');
      result.current.setFiltroPrecio('con_precio');
      result.current.setFiltroRebate('si');
      result.current.setFiltroOferta('si');
      result.current.setFiltroWebTransf('si');
      result.current.setFiltroTiendaNube('con_descuento');
      result.current.setFiltroMarkupClasica('bajo');
      result.current.setFiltroMarkupRebate('bajo');
      result.current.setFiltroMarkupOferta('bajo');
      result.current.setFiltroMarkupWebTransf('bajo');
      result.current.setFiltroOutOfCards('si');
      result.current.setFiltroMLA('con_mla');
      result.current.setFiltroEstadoMLA('activa');
      result.current.setFiltroNuevos('ultimos_7_dias');
      result.current.setFiltroTiendaOficial('2645');
      result.current.setFiltroPromoTipos(['DEAL']);
      result.current.setFiltroPromoEstado('aplicada');
      result.current.setMarcasSeleccionadas(['ACME']);
      result.current.setSubcategoriasSeleccionadas(['SUB']);
      result.current.setPmsSeleccionados([7]);
      result.current.setColoresSeleccionados(['rojo']);
    });
  };

  // What the user actually observes is not hook state but the request the
  // list makes next. A filter that survives here is a filter that keeps
  // filtering after "Limpiar", which is the reported bug.
  it('limpiarTodosFiltros leaves construirFiltrosParams empty', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    setEverything(result);
    expect(Object.keys(result.current.construirFiltrosParams()).length).toBeGreaterThan(0);

    act(() => result.current.limpiarTodosFiltros());

    expect(result.current.construirFiltrosParams()).toEqual({});
  });

  it('limpiarFiltros leaves construirFiltrosParams empty too', () => {
    // Bound to the "Total Productos" stat card: clicking the card that means
    // "show me everything" must not leave a brand, colour or store filter on.
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    setEverything(result);

    act(() => result.current.limpiarFiltros());

    expect(result.current.construirFiltrosParams()).toEqual({});
  });
});

describe('useProductosFilters — wholesale (PxQ) filter', () => {
  it('defaults filtroPxq to null and sends no param', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });
    expect(result.current.filtroPxq).toBeNull();
    expect(result.current.construirFiltrosParams().con_pxq).toBeUndefined();
  });

  it('construirFiltrosParams sends con_pxq=true when the filter is on', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPxq('con_pxq');
    });

    expect(result.current.construirFiltrosParams().con_pxq).toBe(true);
  });

  it('keeps every other active filter alongside it (they add up, never replace)', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPxq('con_pxq');
      result.current.setFiltroPromoTipos(['SMART']);
      result.current.setMarcasSeleccionadas(['Epson']);
    });

    const params = result.current.construirFiltrosParams();
    expect(params.con_pxq).toBe(true);
    expect(params.promo_tipos).toBe('SMART');
    expect(params.marcas).toBe('Epson');
  });

  it('loadFiltersFromURL round-trips pxq from the URL', () => {
    const { result } = renderHook(() => useProductosFilters(), {
      wrapper: wrapperWithURL(['/?pxq=con_pxq']),
    });
    expect(result.current.filtroPxq).toBe('con_pxq');
  });

  it('limpiarTodosFiltros resets it', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPxq('con_pxq');
    });
    act(() => {
      result.current.limpiarTodosFiltros();
    });

    expect(result.current.filtroPxq).toBeNull();
    expect(result.current.construirFiltrosParams().con_pxq).toBeUndefined();
  });

  it('limpiarFiltros (advanced-panel reset) resets it too', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setFiltroPxq('con_pxq');
    });
    act(() => {
      result.current.limpiarFiltros();
    });

    expect(result.current.filtroPxq).toBeNull();
  });
});

describe('useProductosFilters — limpiarFiltrosAvanzados (the Filtros Avanzados panel button)', () => {
  // The panel used to keep its OWN hand-written list of setters inside
  // Productos.jsx. PxQ shipped without a line in it, so "Limpiar Todos" left
  // the listing filtered by wholesale prices while the panel looked clean —
  // the same drift that had already left `filtroTiendaOficial` behind. The
  // reset now lives here, and `resetAllFilters` delegates to it, so the two
  // cannot disagree.
  const ADVANCED_FILTERS = [
    ['setFiltroRebate', 'con_rebate'],
    ['setFiltroOferta', 'con_oferta'],
    ['setFiltroWebTransf', 'con_web_transf'],
    ['setFiltroTiendaNube', 'con_descuento'],
    ['setFiltroMarkupClasica', 'positivo'],
    ['setFiltroMarkupRebate', 'positivo'],
    ['setFiltroMarkupOferta', 'positivo'],
    ['setFiltroMarkupWebTransf', 'positivo'],
    ['setFiltroOutOfCards', 'con_out_of_cards'],
    ['setFiltroMLA', 'con_mla'],
    ['setFiltroEstadoMLA', 'activa'],
    ['setFiltroNuevos', 'ultimos_7_dias'],
    ['setFiltroTiendaOficial', '2645'],
    ['setFiltroPxq', 'con_pxq'],
  ];

  it('leaves no advanced filtro* state behind — guards every future filter', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      ADVANCED_FILTERS.forEach(([setter, value]) => result.current[setter](value));
      result.current.setColoresSeleccionados(['rojo']);
      result.current.setFiltroPromoTipos(['DEAL']);
      result.current.setFiltroPromoEstado('aplicada');
    });
    act(() => result.current.limpiarFiltrosAvanzados());

    // Stock/precio live in the MAIN bar, not in this panel: the panel must
    // not reach outside itself.
    const MAIN_BAR = new Set(['filtroStock', 'filtroPrecio']);
    const NEUTRAL = new Set([null, undefined, '', 'todos', 'disponible']);
    const leftovers = Object.entries(result.current)
      .filter(([key]) => key.startsWith('filtro') && !key.startsWith('filtros') && !MAIN_BAR.has(key))
      .filter(([, value]) => {
        if (Array.isArray(value)) return value.length > 0;
        if (typeof value === 'function') return false;
        return !NEUTRAL.has(value);
      })
      .map(([key, value]) => `${key}=${JSON.stringify(value)}`);

    expect(leftovers).toEqual([]);
    expect(result.current.coloresSeleccionados).toEqual([]);
    expect(result.current.construirFiltrosParams().con_pxq).toBeUndefined();
  });

  it('does not clear the main-bar filters it does not own', () => {
    const { result } = renderHook(() => useProductosFilters(), { wrapper });

    act(() => {
      result.current.setSearchInput('taladro');
      result.current.setFiltroStock('con_stock');
      result.current.setMarcasSeleccionadas(['ACME']);
      result.current.setFiltroPxq('con_pxq');
    });
    act(() => result.current.limpiarFiltrosAvanzados());

    expect(result.current.searchInput).toBe('taladro');
    expect(result.current.filtroStock).toBe('con_stock');
    expect(result.current.marcasSeleccionadas).toEqual(['ACME']);
    expect(result.current.filtroPxq).toBeNull();
  });
});

describe('Productos page — the Filtros Avanzados panel delegates its reset', () => {
  it('keeps no parallel list of setters in the page', async () => {
    // A source-level guard: the bug was a second, hand-maintained reset list
    // in the page that silently fell behind the hook. Behaviour tests on the
    // hook cannot see it, so this asserts the delegation itself.
    const fs = await import('node:fs');
    const { fileURLToPath } = await import('node:url');
    const path = await import('node:path');
    const here = path.dirname(fileURLToPath(import.meta.url));
    const source = fs.readFileSync(path.join(here, '..', 'pages', 'Productos.jsx'), 'utf8');

    expect(source).toContain('onClick={limpiarFiltrosAvanzados}');
    expect(source).not.toContain('setFiltroRebate(null);');
    expect(source).not.toContain('setFiltroPromoTipos([]);');
  });
});
