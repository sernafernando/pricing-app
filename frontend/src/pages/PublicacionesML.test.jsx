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
  BRAND_NODES,
  DATA_STATE_OK,
  FACETS,
  ITEMS,
  ITEMS_RESPONSE,
  DETAIL_RESPONSE,
  ITEMS_RESPONSE_EVENTS_OFF,
  groupsResponse,
  itemsResponse,
  KPIS_RESPONSE,
  KPIS_RESPONSE_MARGIN,
  makeItem,
  VARIATIONS_RESPONSE,
  VARIATION_ITEM,
} from '../test/visual/publicacionesMlFixtures';

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { items: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), enqueue: vi.fn(), kpis: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

vi.mock('../utils/mlSidePanel', async (importOriginal) => ({
  ...(await importOriginal()),
  openInMlPanel: vi.fn(),
}));

// Everything is allowed except the margin, which each test grants on purpose.
let canSeeMargin = false;
let canSeeKpis = true;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => {
      if (permiso === 'ml_metricas.ver_ganancia') return canSeeMargin;
      if (permiso === 'ml_metricas.ver') return canSeeKpis;
      return true;
    },
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
  canSeeKpis = true;
  publicacionesMlAPI.kpis.mockReset();
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE });
  seedTiendasOficiales([
    { store_id: 471846, nombre: 'TP-Link', clave: null, orden: 0, activa: true },
    { store_id: 57997, nombre: 'Gauss', clave: null, orden: 1, activa: true },
  ]);
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.variations.mockReset();
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
  publicacionesMlAPI.groups.mockReset();
  publicacionesMlAPI.groups.mockResolvedValue({ data: groupsResponse('marca', BRAND_NODES) });
  publicacionesMlAPI.detail.mockReset();
  publicacionesMlAPI.detail.mockImplementation((itemId) =>
    Promise.resolve({ data: { ...DETAIL_RESPONSE, row: ITEMS.find((item) => item.item_id === itemId) ?? ITEMS[0] } }),
  );
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

describe('the detail panel (publicaciones-ml-vista P13a.T1)', () => {
  const panel = () => screen.queryByRole('complementary', { name: 'Detalle de la publicación' });

  it('is closed until a publication is selected', async () => {
    await page();
    expect(panel()).not.toBeInTheDocument();
    expect(publicacionesMlAPI.detail).not.toHaveBeenCalled();
  });

  it('a plain click opens it beside the table, which stays on screen (never an overlay)', async () => {
    await page();
    await userEvent.click(screen.getByText('MLA1100000001').closest('tr'));
    const opened = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    await within(opened).findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    expect(publicacionesMlAPI.detail).toHaveBeenCalledWith('MLA1100000001');
    expect(screen.getByRole('table', { name: 'Publicaciones de Mercado Libre' })).toBeInTheDocument();
    expect(opened.parentElement).toContainElement(screen.getByRole('table', { name: 'Publicaciones de Mercado Libre' }));
  });

  it('opens from the URL: sel and tab survive a reload', async () => {
    await page('/ml-publicaciones?sel=MLA1100000002&tab=resumen');
    const opened = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    await within(opened).findByRole('heading', { name: /Cartucho Epson 544/ });
    expect(within(opened).getByRole('tab', { name: 'Resumen' })).toHaveAttribute('aria-selected', 'true');
  });

  it('selecting another row swaps the content', async () => {
    await page();
    await userEvent.click(screen.getByText('MLA1100000001').closest('tr'));
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    await userEvent.click(screen.getByText('MLA1100000002').closest('tr'));
    expect(await screen.findByRole('heading', { name: /Cartucho Epson 544/ })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Router TP-Link Archer AX55/ })).not.toBeInTheDocument();
  });

  it('Escape closes it and focus goes back to the row it came from (S63.1)', async () => {
    await page();
    const row = screen.getByText('MLA1100000001').closest('tr');
    await userEvent.click(row);
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    expect(row).toHaveFocus();
    expect(row).not.toHaveAttribute('aria-current');
  });

  it('the close button clears the selection', async () => {
    await page('/ml-publicaciones?sel=MLA1100000002');
    await userEvent.click(await screen.findByRole('button', { name: 'Cerrar panel' }));
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
  });

  it('changing a filter closes the selection', async () => {
    await page('/ml-publicaciones?sel=MLA1100000002');
    await screen.findByRole('heading', { name: /Cartucho Epson 544/ });
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await userEvent.click(within(estado).getByRole('button', { name: /Pausadas/ }));
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
  });

  it('the panel still opens for a publication that is not on the current page', async () => {
    await page('/ml-publicaciones?sel=MLA9999999999');
    expect(await screen.findByRole('complementary', { name: 'Detalle de la publicación' })).toBeInTheDocument();
    expect(publicacionesMlAPI.detail).toHaveBeenCalledWith('MLA9999999999');
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

  it('a shared link with markup_neg=true shows the switch on, as the request filters', async () => {
    await withMargin('/ml-publicaciones?markup_neg=true');
    expect(lastParams()).toMatchObject({ markup_neg: true });
    expect(screen.getByRole('switch', { name: /negativo/i })).toHaveAttribute('aria-checked', 'true');
  });

  it('typing a decimal comma that equals the bound in the URL leaves the field in the URL form', async () => {
    await withMargin('/ml-publicaciones?markup_min=-2.5');
    const before = calls().length;
    const field = screen.getByLabelText('Markup mínimo (%)');
    await userEvent.clear(field);
    await userEvent.type(field, '-2,5');
    await userEvent.tab();
    expect(calls()).toHaveLength(before);
    expect(field).toHaveValue('-2.5');
  });

  it('a markup filter counts as active: "Limpiar filtros" appears and clears it', async () => {
    await withMargin('/ml-publicaciones?markup_neg=1');
    expect(lastParams()).toMatchObject({ markup_neg: true });
    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    await waitFor(() => expect(lastParams()).not.toHaveProperty('markup_neg'));
    expect(screen.getByLabelText('Markup mínimo (%)')).toHaveValue('');
  });
});

describe('variation sub-rows (publicaciones-ml-vista P11b.T3)', () => {
  const ONE_VARIATION = makeItem({ ...ITEMS[0], item_id: 'MLA1100000009', variations_count: 1 });
  const withVariations = (entry = '/ml-publicaciones') => {
    respond({ ...ITEMS_RESPONSE, items: [VARIATION_ITEM, ONE_VARIATION, ...ITEMS] });
    renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
    return screen.findByText('MLA1100000005');
  };
  const toggle = () => screen.getByRole('button', { name: /variaciones de MLA1100000005/ });

  it('only a publication with more than one variation can be expanded', async () => {
    await withVariations();
    expect(screen.getAllByRole('button', { name: /^Ver las \d+ variaciones/ })).toHaveLength(2); // MLA...05 and the gone one with 3
    expect(screen.queryByRole('button', { name: /variaciones de MLA1100000009/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /variaciones de MLA1100000001/ })).not.toBeInTheDocument();
  });

  it('asks for nothing until a row is expanded (lazy)', async () => {
    await withVariations();
    expect(publicacionesMlAPI.variations).not.toHaveBeenCalled();
  });

  it('expanding fetches that publication\'s variations and shows its sub-rows', async () => {
    await withVariations();
    await userEvent.click(toggle());
    expect(publicacionesMlAPI.variations).toHaveBeenCalledTimes(1);
    expect(publicacionesMlAPI.variations).toHaveBeenCalledWith('MLA1100000005');
    expect(await screen.findByText('Router Archer AX55 negro')).toBeInTheDocument();
    expect(toggle()).toHaveAttribute('aria-expanded', 'true');
  });

  it('the sub-rows sit right under their publication', async () => {
    await withVariations();
    await userEvent.click(toggle());
    await screen.findByText('Router Archer AX55 negro');
    const rows = screen.getAllByRole('row');
    const parent = rows.findIndex((row) => within(row).queryByText('MLA1100000005'));
    expect(within(rows[parent + 1]).getByText('Variación 9001')).toBeInTheDocument();
    expect(within(rows[parent + 3]).getByText('Variación 9003')).toBeInTheDocument();
  });

  it('collapsing hides them again', async () => {
    await withVariations();
    await userEvent.click(toggle());
    await screen.findByText('Router Archer AX55 negro');
    await userEvent.click(toggle());
    expect(screen.queryByText('Router Archer AX55 negro')).not.toBeInTheDocument();
    expect(toggle()).toHaveAttribute('aria-expanded', 'false');
  });

  it('expanding does not select the row nor change the URL selection', async () => {
    await withVariations();
    await userEvent.click(toggle());
    await screen.findByText('Router Archer AX55 negro');
    expect(toggle().closest('tr')).not.toHaveAttribute('aria-current');
  });

  it('a failing fetch shows the error inside the row and the list stays', async () => {
    publicacionesMlAPI.variations.mockRejectedValue(httpError(500));
    await withVariations();
    await userEvent.click(toggle());
    expect(await screen.findByText('No se pudieron cargar las variaciones.')).toBeInTheDocument();
    expect(screen.getByText('MLA1100000001')).toBeInTheDocument();
  });

  it('without ver_ganancia the sub-rows carry no cost nor markup', async () => {
    await withVariations();
    await userEvent.click(toggle());
    await screen.findByText('Router Archer AX55 negro');
    expect(screen.queryByText('41.000,50')).not.toBeInTheDocument();
    expect(screen.queryByText('12,5%')).not.toBeInTheDocument();
  });

  it('with ver_ganancia they show cost and markup, the negative one highlighted', async () => {
    canSeeMargin = true;
    await withVariations();
    await userEvent.click(toggle());
    await screen.findByText('Router Archer AX55 negro');
    expect(screen.getByText('41.000,50')).toBeInTheDocument();
    expect(screen.getByText('-4,2%').closest('tr')).toHaveAttribute('data-negative');
  });
});

describe('open rows reset with the list (publicaciones-ml-vista P11b)', () => {
  it('going to another page and back shows the rows collapsed again', async () => {
    respond({ ...ITEMS_RESPONSE, items: [VARIATION_ITEM, ...ITEMS] });
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones'] });
    await screen.findByText('MLA1100000005');
    await userEvent.click(screen.getByRole('button', { name: /variaciones de MLA1100000005/ }));
    await screen.findByText('Router Archer AX55 negro');
    await userEvent.click(screen.getByRole('button', { name: 'Página 2' }));
    await waitFor(() => expect(lastParams().offset).toBe(50));
    await waitFor(() => expect(screen.queryByText('Router Archer AX55 negro')).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Página 1' }));
    await waitFor(() => expect(lastParams().offset).toBe(0));
    expect(await screen.findByRole('button', { name: /^Ver las 3 variaciones de MLA1100000005/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Router Archer AX55 negro')).not.toBeInTheDocument();
  });
});

describe('the Agrupado view (P12a)', () => {
  const groupCalls = () => publicacionesMlAPI.groups.mock.calls.map(([params]) => params);
  const tree = async (entry = '/ml-publicaciones?vista=agrupado') => {
    renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
    await screen.findByText('EPSON');
  };

  it('shows the tree for vista=agrupado: the roots from /groups, 100 at a time, families off', async () => {
    await tree();
    expect(groupCalls()).toEqual([{ familias: false, limit: 100, offset: 0 }]);
    expect(screen.getByRole('table', { name: /agrupadas/ })).toBeInTheDocument();
    expect(screen.queryByText('MLA1100000001')).not.toBeInTheDocument();
  });

  it('asks /items only for the state and the facet counts, not for a page of rows', async () => {
    await tree();
    await waitFor(() => expect(publicacionesMlAPI.items).toHaveBeenCalled());
    expect(lastParams()).toEqual({ limit: 1, offset: 0, facets: true });
  });

  it('switches view from the header, in the URL, and back', async () => {
    const user = userEvent.setup();
    await page();
    await user.click(screen.getByRole('button', { name: 'Agrupado' }));
    await screen.findByText('EPSON');
    await user.click(screen.getByRole('button', { name: 'Publicaciones' }));
    await screen.findByText('MLA1100000001');
    expect(screen.queryByText('EPSON')).not.toBeInTheDocument();
  });

  it('keeps the filter bar: the store chips reach the tree', async () => {
    await tree('/ml-publicaciones?vista=agrupado&tiendas=57997&estado=active');
    expect(groupCalls()[0]).toMatchObject({ tiendas: '57997', estado: 'active' });
    expect(screen.getByText('Tienda:')).toBeInTheDocument();
  });

  it('has the family toggle only in the tree, off by default, and it asks for families', async () => {
    const user = userEvent.setup();
    await page();
    expect(screen.queryByRole('switch', { name: /familias/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Agrupado' }));
    await screen.findByText('EPSON');
    const toggle = screen.getByRole('switch', { name: /familias/i });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    await user.click(toggle);
    await waitFor(() => expect(groupCalls().at(-1).familias).toBe(true));
    expect(screen.getByRole('switch', { name: /familias/i })).toHaveAttribute('aria-checked', 'true');
  });

  it('reads the family toggle from the URL', async () => {
    await tree('/ml-publicaciones?vista=agrupado&familias=1');
    expect(groupCalls()[0].familias).toBe(true);
  });

  it('does not offer the markup filters the tree does not apply, nor send them', async () => {
    canSeeMargin = true;
    await tree('/ml-publicaciones?vista=agrupado&markup_neg=1&markup_min=5');
    expect(screen.queryByText('Markup:')).not.toBeInTheDocument();
    expect(groupCalls()[0]).not.toHaveProperty('markup_neg');
    expect(groupCalls()[0]).not.toHaveProperty('markup_min');
  });

  it('keeps the markup filters in the list view', async () => {
    canSeeMargin = true;
    await page();
    expect(screen.getByText('Markup:')).toBeInTheDocument();
  });

  it('shows the node figures only with ver_ganancia', async () => {
    await tree();
    expect(screen.queryByRole('columnheader', { name: /Negativos/ })).not.toBeInTheDocument();
  });

  it('clicking a publication of the tree selects it without asking /items again', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.groups.mockResolvedValue({
      data: groupsResponse('producto', [
        { kind: 'producto', key: '9', label: 'Router Z', count: 1, leaf: true, params: { producto: '9' } },
      ]),
    });
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado'] });
    await user.click(await screen.findByRole('button', { name: /Abrir Router Z/ }));
    const leaf = (await screen.findByText(/Router TP-Link Archer AX55/)).closest('tr');
    await user.click(leaf);
    await waitFor(() => expect(leaf).toHaveAttribute('aria-current', 'true'));
    expect(publicacionesMlAPI.items.mock.calls.filter(([params]) => params.limit === 1)).toHaveLength(1);
    // ... and the detail panel opens beside the tree, like it does beside the list.
    const panel = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    await within(panel).findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    expect(publicacionesMlAPI.detail).toHaveBeenCalledWith('MLA1100000001');
  });

  it('"Limpiar filtros" keeps the tree and the family toggle', async () => {
    const user = userEvent.setup();
    await tree('/ml-publicaciones?vista=agrupado&familias=1&tiendas=57997');
    await user.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    await waitFor(() => expect(groupCalls().at(-1)).not.toHaveProperty('tiendas'));
    expect(groupCalls().at(-1).familias).toBe(true);
    expect(screen.getByRole('table', { name: /agrupadas/ })).toBeInTheDocument();
  });

  it('keeps the tree on screen when /items fails, and says so above it', async () => {
    const user = userEvent.setup();
    await tree();
    // A later /items failure (the facets of a changed filter) must not take the tree away.
    publicacionesMlAPI.items.mockRejectedValueOnce(httpError(503));
    await user.click(screen.getByRole('button', { name: /Pausadas/ }));
    expect(await screen.findByText(/La consulta tardó demasiado/)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /agrupadas/ })).toBeInTheDocument();
    expect(screen.getByText('EPSON')).toBeInTheDocument();
  });

  it('says the store is empty, like the list', async () => {
    respond({ ...ITEMS_RESPONSE, facets: FACETS, data_state: { ...DATA_STATE_OK, store_empty: true } });
    publicacionesMlAPI.groups.mockResolvedValue({ data: groupsResponse('marca', []) });
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado'] });
    expect(await screen.findByText('Todavía no hay publicaciones sincronizadas')).toBeInTheDocument();
  });
});

describe('the KPI strip (publicaciones-ml-vista P12b)', () => {
  const kpiCalls = () => publicacionesMlAPI.kpis.mock.calls;
  const kpiParams = () => kpiCalls().at(-1)[0];
  const strip = () => screen.findByRole('region', { name: 'Indicadores de las publicaciones' });

  it('asks /view/kpis for the list filters and the default 30-day period, never the paging or sort', async () => {
    await page('/ml-publicaciones?estado=active&orden=precio&dir=asc&pagina=2');
    const region = await strip();
    expect(kpiParams()).toEqual({ estado: 'active', periodo: 30 });
    expect(kpiCalls()[0][1].signal).toBeInstanceOf(AbortSignal);
    expect(within(region).getByText('Unidades vendidas')).toBeInTheDocument();
    expect(within(region).getByText('1.240')).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: '30 días' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('renders no strip, and asks for nothing, without ml_metricas.ver; the table still renders (S34.2)', async () => {
    canSeeKpis = false;
    await page();
    expect(screen.queryByRole('region', { name: 'Indicadores de las publicaciones' })).not.toBeInTheDocument();
    expect(kpiCalls()).toHaveLength(0);
  });

  it('shows the profit tiles only with ver_ganancia', async () => {
    await page();
    const region = await strip();
    expect(within(region).queryByText('Total Gauss')).not.toBeInTheDocument();
    expect(within(region).queryByText('Markup promedio')).not.toBeInTheDocument();
  });

  it('shows Total Gauss and markup with ver_ganancia', async () => {
    canSeeMargin = true;
    publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE_MARGIN });
    await page();
    const region = await strip();
    expect(await within(region).findByText('Total Gauss')).toBeInTheDocument();
    expect(within(region).getByText('Markup promedio')).toBeInTheDocument();
  });

  it('changing the period asks only the strip again, never the rows (S32.2)', async () => {
    const user = userEvent.setup();
    await page();
    const rowCalls = calls().length;
    await user.click(within(await strip()).getByRole('button', { name: '7 días' }));
    await waitFor(() => expect(kpiParams().periodo).toBe(7));
    expect(calls()).toHaveLength(rowCalls);
  });

  it('aborts the stale strip request when the filters change', async () => {
    const user = userEvent.setup();
    await page();
    await strip();
    const firstSignal = kpiCalls()[0][1].signal;
    await user.click(screen.getByRole('button', { name: /Pausadas/ }));
    await waitFor(() => expect(kpiParams().estado).toBe('paused'));
    expect(firstSignal.aborted).toBe(true);
  });

  it('a slow strip (503) shows a strip-level error and leaves the table intact', async () => {
    publicacionesMlAPI.kpis.mockRejectedValue(httpError(503));
    await page();
    expect(await screen.findByText(/Los KPIs tardaron demasiado/)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Publicaciones de Mercado Libre' })).toBeInTheDocument();
    expect(screen.getByText('MLA1100000001')).toBeInTheDocument();
  });

  it('with a markup filter, keeps the KPIs, warns they ignore it, and sends no markup param', async () => {
    canSeeMargin = true;
    publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE_MARGIN });
    await page('/ml-publicaciones?markup_neg=1&markup_min=5');
    const region = await strip();
    expect(within(region).getByText('Los KPIs no aplican el filtro de markup')).toBeInTheDocument();
    expect(await within(region).findByText('Unidades vendidas')).toBeInTheDocument();
    for (const [params] of kpiCalls()) {
      expect(Object.keys(params).filter((key) => key.startsWith('markup_'))).toEqual([]);
    }
    expect(lastParams().markup_neg).toBe(true);
  });

  it('shows no markup notice without a markup filter', async () => {
    canSeeMargin = true;
    await page();
    await strip();
    expect(screen.queryByText(/no aplican el filtro de markup/)).not.toBeInTheDocument();
  });
});
