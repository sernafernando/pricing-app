/**
 * Publicaciones ML page wiring (publicaciones-ml-vista P11a.T5): what it asks
 * `/ml-publications/view/items` for and what it does with the answer. Layout is
 * the visual suite's job (`src/test/visual/publicacionesMl.visual.test.jsx`).
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import PublicacionesML from './PublicacionesML';
import { publicacionesMlAPI } from '../services/api';
import { openInMlPanel } from '../utils/mlSidePanel';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import {
  DATA_STATE_OK,
  FACETS,
  ITEMS,
  ITEMS_RESPONSE,
  ITEMS_RESPONSE_EVENTS_OFF,
  itemsResponse,
  makeItem,
} from '../test/visual/publicacionesMlFixtures';

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { items: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

vi.mock('../utils/mlSidePanel', async (importOriginal) => ({
  ...(await importOriginal()),
  openInMlPanel: vi.fn(),
}));

// Everything is allowed except the margin, which each test grants on purpose.
let canSeeMargin = false;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => (permiso === 'ml_metricas.ver_ganancia' ? canSeeMargin : true),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const respond = (body) => publicacionesMlAPI.items.mockResolvedValue({ data: body });
const calls = () => publicacionesMlAPI.items.mock.calls.map(([params]) => params);
const lastParams = () => calls().at(-1);
const httpError = (status, data = {}) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } });

const page = async (entry = '/ml-publicaciones') => {
  renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
  await screen.findByText('MLA1100000001');
};

beforeEach(() => {
  canSeeMargin = false;
  seedTiendasOficiales([
    { store_id: 471846, nombre: 'TP-Link', clave: null, orden: 0, activa: true },
    { store_id: 57997, nombre: 'Gauss', clave: null, orden: 1, activa: true },
  ]);
  publicacionesMlAPI.items.mockReset();
  openInMlPanel.mockReset();
  respond({ ...ITEMS_RESPONSE, facets: FACETS });
});

afterAll(resetTiendasOficiales);

describe('the list', () => {
  it('asks for the first page of 50, with facets, and renders one row per MLA', async () => {
    await page();
    expect(lastParams()).toEqual({ limit: 50, offset: 0, facets: true });
    expect(screen.getByText(/Router TP-Link Archer AX55/)).toBeInTheDocument();
    expect(screen.getByText('MLA1100000004')).toBeInTheDocument();
    expect(screen.getByText('mostrando 1-50 de 235 publicaciones')).toBeInTheDocument();
  });

  it('reads the filters from the URL (S9.1)', async () => {
    await page('/ml-publicaciones?q=router&estado=active&tiendas=57997&orden=precio&dir=asc&pagina=2');
    expect(lastParams()).toEqual({
      q: 'router',
      estado: 'active',
      tiendas: '57997',
      orden: 'precio',
      dir: 'asc',
      limit: 50,
      offset: 50,
      facets: true,
    });
  });

  it('shows "—" for every nullable, never an empty cell or a made-up 0 (S4.1)', async () => {
    await page();
    const row = screen.getByText('MLA1100000003').closest('tr');
    expect(within(row).getByText('Sin título')).toBeInTheDocument();
    // status, price, stock, link (no_evaluado is a label, not a dash), tienda, actividad, evento
    expect(within(row).getAllByText('—').length).toBeGreaterThanOrEqual(5);
    expect(within(row).queryByText('0')).not.toBeInTheDocument();
  });

  it('has no "Último evento" column while the events flag is off (S56.2)', async () => {
    respond({ ...ITEMS_RESPONSE_EVENTS_OFF, facets: FACETS });
    await page();
    expect(screen.queryByRole('columnheader', { name: /Último evento/ })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Última actividad/ })).toBeInTheDocument();
  });

  it('shows the last event column while events are on', async () => {
    await page();
    expect(screen.getByRole('columnheader', { name: /Último evento/ })).toBeInTheDocument();
    expect(screen.getByText('Precio modificado')).toBeInTheDocument();
  });
});

describe('facets', () => {
  it('are asked for on a filter change, not on a page or sort change', async () => {
    await page();
    expect(lastParams().facets).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'Página 2' }));
    await waitFor(() => expect(lastParams().offset).toBe(50));
    expect(lastParams()).not.toHaveProperty('facets');

    await userEvent.click(screen.getByRole('button', { name: /^Precio/ }));
    await waitFor(() => expect(lastParams().orden).toBe('precio'));
    expect(lastParams()).not.toHaveProperty('facets');

    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await userEvent.click(within(estado).getByRole('button', { name: /Pausadas/ }));
    await waitFor(() => expect(lastParams().estado).toBe('paused'));
    expect(lastParams().facets).toBe(true);
  });

  it('keep showing the last counts while a page without facets loads', async () => {
    await page();
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    expect(within(estado).getByRole('button', { name: /Activas.*180/ })).toBeInTheDocument();
    respond(itemsResponse());
    await userEvent.click(screen.getByRole('button', { name: 'Página 2' }));
    await waitFor(() => expect(lastParams().offset).toBe(50));
    expect(within(screen.getByRole('group', { name: 'Filtrar por estado' })).getByRole('button', { name: /Activas.*180/ })).toBeInTheDocument();
  });

  it('are asked for again after a failure (the ref only advances on success)', async () => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockRejectedValueOnce(httpError(500));
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones'] });
    await screen.findByRole('alert');
    respond({ ...ITEMS_RESPONSE, facets: FACETS });
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    await screen.findByText('MLA1100000001');
    expect(lastParams().facets).toBe(true);
  });
});

describe('filters', () => {
  it('a status chip filters by estado and goes back to page 1', async () => {
    await page('/ml-publicaciones?pagina=3');
    expect(lastParams().offset).toBe(100);
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await userEvent.click(within(estado).getByRole('button', { name: /Activas/ }));
    await waitFor(() => expect(lastParams().estado).toBe('active'));
    expect(lastParams().offset).toBe(0);
  });

  it('"Sin tienda" is sent as the backend\'s `none`', async () => {
    await page();
    const tienda = screen.getByRole('group', { name: 'Filtrar por tienda oficial' });
    await userEvent.click(within(tienda).getByRole('button', { name: /Sin tienda/ }));
    await waitFor(() => expect(lastParams().tiendas).toBe('none'));
  });

  it('counts the "Sin tienda" chip from the backend\'s `none` facet', async () => {
    await page();
    const tienda = screen.getByRole('group', { name: 'Filtrar por tienda oficial' });
    expect(within(tienda).getByRole('button', { name: /Sin tienda.*35/ })).toBeInTheDocument();
  });

  it('search is debounced and sent as q', async () => {
    await page();
    await userEvent.type(screen.getByRole('searchbox'), 'archer');
    await waitFor(() => expect(lastParams().q).toBe('archer'), { timeout: 2000 });
  });

  it('"Limpiar filtros" appears with a filter active and clears it', async () => {
    await page('/ml-publicaciones?estado=active');
    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    await waitFor(() => expect(lastParams()).not.toHaveProperty('estado'));
  });
});

describe('sorting and paging', () => {
  it('clicking a sortable header sorts by it, its default direction first', async () => {
    await page();
    await userEvent.click(screen.getByRole('button', { name: /^Precio/ }));
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'precio', dir: 'asc' }));
    await userEvent.click(screen.getByRole('button', { name: /^Precio/ }));
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'precio', dir: 'desc' }));
  });

  it('defaults to activity, newest first', async () => {
    await page();
    expect(screen.getByRole('columnheader', { name: /Última actividad/ })).toHaveAttribute('aria-sort', 'descending');
  });
});

describe('page size', () => {
  it('comes from the URL, so a reload keeps the rows per page and the page', async () => {
    await page('/ml-publicaciones?limite=100&pagina=2');
    expect(lastParams()).toMatchObject({ limit: 100, offset: 100 });
  });

  it('changing it asks for the first page with the new size', async () => {
    await page('/ml-publicaciones?pagina=3');
    await userEvent.selectOptions(screen.getByLabelText('Filas por página'), '25');
    await waitFor(() => expect(lastParams()).toMatchObject({ limit: 25, offset: 0 }));
  });
});

describe('columns', () => {
  it('the picker hides and shows a column', async () => {
    await page();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Tienda' }));
    expect(screen.queryByRole('columnheader', { name: 'Tienda' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Tienda' }));
    expect(screen.getByRole('columnheader', { name: 'Tienda' })).toBeInTheDocument();
  });

  it('the publication column cannot be hidden', async () => {
    await page();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    expect(screen.queryByRole('checkbox', { name: 'Publicación' })).not.toBeInTheDocument();
  });
});

describe('banner', () => {
  it('S67.1: an empty store is named, with a matching empty message', async () => {
    respond({ ...itemsResponse({ items: [], total: 0 }), data_state: { ...DATA_STATE_OK, store_empty: true } });
    renderWithRouter(<PublicacionesML />);
    expect(await screen.findByText('Todavía no hay publicaciones sincronizadas')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Todavía no se sincronizó ninguna publicación');
  });

  it('S67.2: core-only is named', async () => {
    respond(
      itemsResponse({
        data_state: {
          ...DATA_STATE_OK,
          degraded: true,
          degradations: [{ code: 'resource_not_collected', resource: 'stock', affects: ['stock.full', 'stock.own'] }],
        },
      }),
    );
    await page();
    expect(screen.getByText(/Solo se sincronizan los datos básicos/)).toBeInTheDocument();
  });

  it('S67.3: an unavailable status is neutral and the list still renders', async () => {
    respond(
      itemsResponse({
        data_state: { available: false, reason: 'status_unavailable', degraded: true, degradations: [], sections_failed: [] },
      }),
    );
    await page();
    expect(screen.getByText(/No pudimos verificar el estado de la sincronización/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('loading and errors', () => {
  it('S69.1: shows a skeleton while the first page loads', async () => {
    publicacionesMlAPI.items.mockReturnValue(new Promise(() => {}));
    renderWithRouter(<PublicacionesML />);
    expect(await screen.findByLabelText('Cargando publicaciones')).toBeInTheDocument();
  });

  it('S69.1: a 503 consulta_lenta says the query took too long and can be retried', async () => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockRejectedValueOnce(
      httpError(503, { error: { code: 'consulta_lenta', message: 'La consulta tardó demasiado; reintentá.' } }),
    );
    renderWithRouter(<PublicacionesML />);
    expect(await screen.findByRole('alert')).toHaveTextContent('La consulta tardó demasiado');
    expect(screen.queryByText('MLA1100000001')).not.toBeInTheDocument();

    respond({ ...ITEMS_RESPONSE, facets: FACETS });
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('MLA1100000001')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says so when the filter is invalid (422), with the backend\'s message', async () => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockRejectedValue(
      httpError(422, { error: { code: 'validation_error', message: 'estado: unknown value', field: 'estado' } }),
    );
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?estado=zzz'] });
    expect(await screen.findByRole('alert')).toHaveTextContent('Filtro inválido');
  });

  it('a generic failure has a generic message', async () => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockRejectedValue(httpError(500));
    renderWithRouter(<PublicacionesML />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar las publicaciones');
  });

  it('a late answer to an old query never overwrites the newer one', async () => {
    let resolveOld;
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    renderWithRouter(<PublicacionesML />);
    await waitFor(() => expect(calls()).toHaveLength(1));
    respond({ ...ITEMS_RESPONSE, items: [ITEMS[3]], total: 1, facets: FACETS });
    await userEvent.click(screen.getByRole('button', { name: /Activas/ }));
    await screen.findByText('MLA1100000004');
    resolveOld({ data: { ...ITEMS_RESPONSE, facets: FACETS } });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText('MLA1100000001')).not.toBeInTheDocument();
  });
});

describe('opening a publication', () => {
  it('Ctrl+click opens it in the ML panel (S66.1) and does not select the row', async () => {
    await page();
    const row = screen.getByText('MLA1100000001').closest('tr');
    fireEvent.click(row, { ctrlKey: true });
    expect(openInMlPanel).toHaveBeenCalledWith(ITEMS[0].permalink);
    expect(row).not.toHaveAttribute('aria-current');
  });

  it('Cmd+click does the same (S66.2)', async () => {
    await page();
    fireEvent.click(screen.getByText('MLA1100000002').closest('tr'), { metaKey: true });
    expect(openInMlPanel).toHaveBeenCalledWith(ITEMS[1].permalink);
  });

  it('a publication without a permalink opens nothing (S66.3)', async () => {
    await page();
    const row = screen.getByText('MLA1100000003').closest('tr');
    fireEvent.click(row, { ctrlKey: true });
    expect(openInMlPanel).toHaveBeenCalledWith(null);
    expect(row).not.toHaveAttribute('aria-current');
  });

  it('a plain click selects the row and does not open ML (S66.4)', async () => {
    await page();
    const row = screen.getByText('MLA1100000001').closest('tr');
    await userEvent.click(row);
    expect(openInMlPanel).not.toHaveBeenCalled();
    expect(row).toHaveAttribute('aria-current', 'true');
  });
});

describe('markup (publicaciones-ml-vista P11b.T2)', () => {
  const MARKUP = { min: -4, max: 12, worst: -4, any_negative: true, reason: 'ok', partial: 0, ads: null };
  const withMargin = (entry = '/ml-publicaciones') => {
    canSeeMargin = true;
    respond({
      ...ITEMS_RESPONSE,
      can_see_margin: true,
      facets: FACETS,
      items: [makeItem({ ...ITEMS[0], markup: MARKUP }), ...ITEMS.slice(1)],
    });
    return page(entry);
  };

  it('without ver_ganancia there is no column, no controls, and no markup param (S68.1)', async () => {
    await page('/ml-publicaciones?markup_neg=1&markup_min=5&orden=markup');
    expect(screen.queryByRole('columnheader', { name: /Markup/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('switch', { name: /negativo/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Markup mínimo/)).not.toBeInTheDocument();
    for (const params of calls()) {
      expect(params).not.toHaveProperty('markup_neg');
      expect(params).not.toHaveProperty('markup_min');
      expect(params).not.toHaveProperty('orden');
    }
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    expect(screen.queryByRole('checkbox', { name: 'Markup' })).not.toBeInTheDocument();
  });

  it('with ver_ganancia the column shows the range, and the sort is labelled "peor variación"', async () => {
    await withMargin();
    expect(screen.getByText('-4,0% – 12,0%')).toBeInTheDocument();
    const header = screen.getByRole('columnheader', { name: /Markup/ });
    expect(within(header).getByText('peor variación')).toBeInTheDocument();
  });

  it('clicking the header sorts by orden=markup, worst first', async () => {
    await withMargin();
    await userEvent.click(screen.getByRole('button', { name: /^Markup/ }));
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'markup', dir: 'asc' }));
    await userEvent.click(screen.getByRole('button', { name: /^Markup/ }));
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'markup', dir: 'desc' }));
  });

  it('the picker lists the markup column under its plain name', async () => {
    await withMargin();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Markup' }));
    expect(screen.queryByRole('columnheader', { name: /Markup/ })).not.toBeInTheDocument();
  });

  it('"Solo negativos" sends markup_neg=true and goes back to page 1', async () => {
    await withMargin('/ml-publicaciones?pagina=3');
    await userEvent.click(screen.getByRole('switch', { name: /negativo/i }));
    await waitFor(() => expect(lastParams()).toMatchObject({ markup_neg: true, offset: 0 }));
    expect(screen.getByRole('switch', { name: /negativo/i })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('switch', { name: /negativo/i }));
    await waitFor(() => expect(lastParams()).not.toHaveProperty('markup_neg'));
  });

  it('mínimo and máximo are sent when committed, not on every keystroke', async () => {
    await withMargin();
    const before = calls().length;
    await userEvent.type(screen.getByLabelText('Markup mínimo (%)'), '-5');
    expect(calls()).toHaveLength(before);
    await userEvent.type(screen.getByLabelText('Markup máximo (%)'), '20{Enter}');
    await waitFor(() => expect(lastParams()).toMatchObject({ markup_min: '-5', markup_max: '20' }));
  });

  it('clearing a bound removes the param', async () => {
    await withMargin('/ml-publicaciones?markup_min=5');
    expect(screen.getByLabelText('Markup mínimo (%)')).toHaveValue('5');
    await userEvent.clear(screen.getByLabelText('Markup mínimo (%)'));
    await userEvent.tab();
    await waitFor(() => expect(lastParams()).not.toHaveProperty('markup_min'));
  });

  it('a markup filter counts as active: "Limpiar filtros" appears and clears it', async () => {
    await withMargin('/ml-publicaciones?markup_neg=1');
    expect(lastParams()).toMatchObject({ markup_neg: true });
    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    await waitFor(() => expect(lastParams()).not.toHaveProperty('markup_neg'));
    expect(screen.getByLabelText('Markup mínimo (%)')).toHaveValue('');
  });
});
