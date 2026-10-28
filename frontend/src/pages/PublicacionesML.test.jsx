/**
 * Publicaciones ML page wiring (publicaciones-ml-vista P11a.T5): what it asks
 * `/ml-publications/view/items` for and what it does with the answer. Layout is
 * the visual suite's job (`src/test/visual/publicacionesMl.visual.test.jsx`).
 */
import { describe, it, expect, vi, beforeEach, afterEach, afterAll } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import PublicacionesML from './PublicacionesML';
import api, { publicacionesMlAPI } from '../services/api';
import { openInMlPanel } from '../utils/mlSidePanel';
import { exportPublicacionesCsv, exportPublicacionesSheets } from '../utils/publicacionesMlExport';
import { loadGoogleIdentity } from '../utils/googleSheetsExport';
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
  productsResponse,
} from '../test/visual/publicacionesMlFixtures';

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    patch: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosPropiosAPI: { get: vi.fn(() => new Promise(() => {})), save: vi.fn() },
  publicacionesMlAPI: { items: vi.fn(), products: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), enqueue: vi.fn(), kpis: vi.fn(), productIds: vi.fn() },
  productosAPI: {
    marcas: vi.fn(() => Promise.resolve({ data: { marcas: ['TP,LINK', 'EPSON'] } })),
    categorias: vi.fn(() => Promise.resolve({ data: { categorias: ['REDES'] } })),
    subcategorias: vi.fn(() => Promise.resolve({ data: { categorias: [] } })),
    pms: vi.fn(() => Promise.resolve({ data: [{ id: 7, nombre: 'Ana' }] })),
  },
  equiposAPI: {
    listar: vi.fn(() =>
      Promise.resolve({ data: [{ id: 1, nombre: 'U', es_global: true }, { id: 12, nombre: 'Ventas', es_global: false }] }),
    ),
  },
  registerAuthFailureHandler: vi.fn(),
}));

// The color events (`producto_color:changed`) are pushed by each test through the captured listener.
const sse = { listener: null };
vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: (channel, callback) => {
    if (channel === 'producto_color:changed') sse.listener = callback;
  },
}));

vi.mock('../utils/mlSidePanel', async (importOriginal) => ({
  ...(await importOriginal()),
  openInMlPanel: vi.fn(),
}));

vi.mock('../utils/publicacionesMlExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportPublicacionesCsv: vi.fn(),
  exportPublicacionesSheets: vi.fn(),
}));
vi.mock('../utils/googleSheetsExport', async (importOriginal) => ({
  ...(await importOriginal()),
  loadGoogleIdentity: vi.fn(() => Promise.resolve(true)),
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
  publicacionesMlAPI.productIds.mockReset();
  publicacionesMlAPI.productIds.mockResolvedValue({ data: { item_ids: [4101, 4102], count: 2, sin_producto: 1 } });
  respond({ ...ITEMS_RESPONSE, facets: FACETS });
});

afterAll(resetTiendasOficiales);

describe('the list', () => {
  it('asks for the first page of 50, with facets, and renders one row per MLA', async () => {
    await page();
    expect(lastParams()).toEqual({ orden: 'facturado_30d', dir: 'desc', limit: 50, offset: 0, facets: true });
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

  it('has no "Último evento" column while the events flag is off, not even in the picker (S56.2)', async () => {
    respond({ ...ITEMS_RESPONSE_EVENTS_OFF, facets: FACETS });
    await page();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    expect(screen.queryByRole('checkbox', { name: 'Último evento' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Última actividad' })).toBeInTheDocument();
  });

  it('offers the last event column while events are on: hidden at first, the picker shows it', async () => {
    await page();
    expect(screen.queryByRole('columnheader', { name: /Último evento/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Último evento' }));
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

  it('defaults to Facturado 30D, highest first, like Métricas: the whole set ranked by the backend', async () => {
    await page();
    expect(lastParams()).toMatchObject({ orden: 'facturado_30d' });
    expect(screen.getByRole('columnheader', { name: /Facturado 30D/ })).toHaveAttribute('aria-sort', 'descending');
  });

  it('without ml_metricas.ver the default stays the activity, newest first (its column is in the picker)', async () => {
    canSeeKpis = false;
    await page();
    expect(lastParams()).not.toHaveProperty('orden');
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Última actividad' }));
    expect(screen.getByRole('columnheader', { name: /Última actividad/ })).toHaveAttribute('aria-sort', 'descending');
  });

  it('each Métricas figure sorts the list, highest first', async () => {
    canSeeMargin = true;
    await page();
    const sortBy = (header) => userEvent.click(within(screen.getByRole('columnheader', { name: header })).getByRole('button'));
    await sortBy(/^7D/);
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'unidades_7d', dir: 'desc' }));
    await sortBy(/^30D/);
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'unidades_30d', dir: 'desc' }));
    await sortBy(/^Real 30D/);
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'markup_30d', dir: 'desc' }));
    await sortBy(/^Total Gauss 30D/);
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'total_gauss_30d', dir: 'desc' }));
    await sortBy(/^Facturado 30D/);
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'facturado_30d', dir: 'desc' }));
    await sortBy(/^Facturado 30D/);
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'facturado_30d', dir: 'asc' }));
  });

  it('a shared link with a margin sort opens with the default sort for who cannot see margins', async () => {
    await page('/ml-publicaciones?orden=markup_30d&dir=asc');
    expect(lastParams()).toMatchObject({ orden: 'facturado_30d', dir: 'desc' });
    expect(screen.getByRole('columnheader', { name: /Facturado 30D/ })).toHaveAttribute('aria-sort', 'descending');
  });
});

describe('stock: our own, Full and the ERP, three columns never summed', () => {
  const cellUnder = (key, itemId) => screen.getByText(itemId).closest('tr').querySelector(`td[data-column="${key}"]`);
  const sortButton = (name) => within(screen.getByRole('columnheader', { name })).getByRole('button');

  it('shows each stock under STOCK in its own column, never the available sum', async () => {
    respond({
      ...ITEMS_RESPONSE,
      facets: FACETS,
      items: ITEMS.map((item, i) => ({ ...item, erp_stock: { quantity: i === 0 ? 12 : null } })),
    });
    await page();
    expect(screen.getByRole('columnheader', { name: 'Stock' })).toHaveAttribute('colspan', '3');
    expect(cellUnder('stock_propio', 'MLA1100000001')).toHaveTextContent('14');
    expect(cellUnder('stock_full', 'MLA1100000001')).toHaveTextContent('20');
    expect(cellUnder('stock_erp', 'MLA1100000001')).toHaveTextContent('12');
    expect(screen.getByText('MLA1100000001').closest('tr')).not.toHaveTextContent('34');
    // The cartridge: a real zero of our own, no Full figure, no product.
    expect(cellUnder('stock_propio', ITEMS[1].item_id)).toHaveTextContent('0');
    expect(cellUnder('stock_full', ITEMS[1].item_id)).toHaveTextContent('—');
    expect(cellUnder('stock_erp', ITEMS[1].item_id)).toHaveTextContent('—');
    expect(screen.queryByRole('columnheader', { name: /Stock ML/ })).not.toBeInTheDocument();
  });

  it('each stock column sorts by its own figure, highest first', async () => {
    await page();
    await userEvent.click(sortButton(/^Propio/));
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'stock_propio', dir: 'desc' }));
    await userEvent.click(sortButton(/^Full/));
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'stock_full', dir: 'desc' }));
    await userEvent.click(sortButton(/^ERP/));
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'stock_erp', dir: 'desc' }));
  });

  it('offers "Sin stock propio", "Full sin stock" and "Sin stock ERP", each with its count', async () => {
    respond({ ...ITEMS_RESPONSE, facets: { ...FACETS, stock: { propio_sin_stock: 3, full_sin_stock: 6, erp_sin_stock: 9 } } });
    await page();
    const stock = screen.getByRole('group', { name: 'Filtrar por stock' });
    expect(within(stock).queryByRole('button', { name: /Sin stock ML/ })).not.toBeInTheDocument();
    expect(within(stock).getByRole('button', { name: /Full sin stock.*6/ })).toBeInTheDocument();
    expect(within(stock).getByRole('button', { name: /Sin stock ERP.*9/ })).toBeInTheDocument();
    await userEvent.click(within(stock).getByRole('button', { name: /Sin stock propio.*3/ }));
    await waitFor(() => expect(lastParams().stock).toBe('propio_sin_stock'));
  });

  it('offers "Con stock ERP" (Productos\' "Con stock") with its count and asks for it (P6)', async () => {
    respond({ ...ITEMS_RESPONSE, facets: { ...FACETS, stock: { ...FACETS.stock, erp_con_stock: 4 } } });
    await page();
    const stock = screen.getByRole('group', { name: 'Filtrar por stock' });
    await userEvent.click(within(stock).getByRole('button', { name: /Con stock ERP.*4/ }));
    await waitFor(() => expect(lastParams().stock).toBe('erp_con_stock'));
  });

  it('an old link with the "Sin stock ML" value opens with "Sin stock propio" active and asks for it', async () => {
    await page('/ml-publicaciones?stock=sin_stock');
    expect(lastParams().stock).toBe('propio_sin_stock');
    const stock = screen.getByRole('group', { name: 'Filtrar por stock' });
    expect(within(stock).getByRole('button', { name: /Sin stock propio/ })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('Métricas ML figures (the owner-approved layout)', () => {
  const METRICS = {
    units_7d: 14,
    units_30d: 1234,
    series_units_90d: Array.from({ length: 90 }, () => 1),
    gross_30d: 98500.5,
    last_sale_at: '2026-10-14T13:05:00Z',
    ageing_days: 45,
    total_gauss_30d: 15000,
    markup_30d: 18.5,
    markup_delta_pp: 1.2,
    series_markup_90d: Array.from({ length: 90 }, () => 18.5),
  };
  const cellUnder = (key, itemId) => screen.getByText(itemId).closest('tr').querySelector(`td[data-column="${key}"]`);
  const withMetrics = () => respond({ ...ITEMS_RESPONSE, facets: FACETS, items: [{ ...ITEMS[0], metrics: METRICS }, ...ITEMS.slice(1)] });

  it('groups the columns under Métricas’ own headings', async () => {
    canSeeMargin = true;
    withMetrics();
    await page();
    for (const name of ['Ventas (unidades)', 'Markup', 'Resultado financiero', 'Rotación', 'Stock']) {
      expect(screen.getByRole('columnheader', { name })).toHaveAttribute('scope', 'colgroup');
    }
  });

  it('shows the row’s Métricas figures, and "—" for a publication Métricas has no row for', async () => {
    canSeeMargin = true;
    withMetrics();
    await page();
    expect(cellUnder('unidades_7d', 'MLA1100000001')).toHaveTextContent('14');
    expect(cellUnder('unidades_30d', 'MLA1100000001')).toHaveTextContent('1.234');
    expect(cellUnder('markup_30d', 'MLA1100000001')).toHaveTextContent('18,5%');
    expect(cellUnder('facturado_30d', 'MLA1100000001')).toHaveTextContent('$ 98.500,50');
    expect(cellUnder('total_gauss_30d', 'MLA1100000001')).toHaveTextContent('$ 15.000,00');
    expect(cellUnder('ageing', 'MLA1100000001')).toHaveTextContent('45 d');
    for (const key of ['unidades_30d', 'markup_30d', 'facturado_30d', 'last_sale', 'ageing']) {
      expect(cellUnder(key, ITEMS[1].item_id)).toHaveTextContent('—');
    }
  });

  it('without ml_metricas.ver there are no Métricas figures at all', async () => {
    canSeeKpis = false;
    withMetrics();
    await page();
    expect(screen.queryByRole('columnheader', { name: 'Ventas (unidades)' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Rotación' })).not.toBeInTheDocument();
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
  it('Vínculo and Tienda start hidden: the store and the link sit in the Publicación cell', async () => {
    await page();
    expect(screen.queryByRole('columnheader', { name: 'Vínculo' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Tienda' })).not.toBeInTheDocument();
    const row = screen.getByText('MLA1100000001').closest('tr');
    expect(within(row).getByLabelText('Tienda: TP-Link')).toBeInTheDocument();
    expect(within(row).getByLabelText('Vínculo: Automático')).toHaveTextContent('ARCHER-AX55');
  });

  it('the picker shows and hides a column', async () => {
    await page();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Tienda' }));
    expect(screen.getByRole('columnheader', { name: 'Tienda' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Tienda' }));
    expect(screen.queryByRole('columnheader', { name: 'Tienda' })).not.toBeInTheDocument();
  });

  it('the publication column cannot be hidden', async () => {
    await page();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    expect(screen.queryByRole('checkbox', { name: 'Publicación' })).not.toBeInTheDocument();
  });
});

describe('SKU divergence', () => {
  it('the "SKU distinto del producto" chip filters by vinculo=sku_divergente', async () => {
    await page();
    const vinculo = screen.getByRole('group', { name: 'Filtrar por vínculo' });
    await userEvent.click(within(vinculo).getByRole('button', { name: /SKU distinto del producto/ }));
    await waitFor(() => expect(lastParams().vinculo).toBe('sku_divergente'));
  });

  it('with the filter on, each row shows its SKU, the product by SKU and the linked product', async () => {
    respond({
      ...itemsResponse({
        total: 1,
        items: [
          makeItem({
            item_id: 'MLA1100000001',
            seller_sku: 'SKU-71',
            link: { state: 'auto', producto_item_id: 70, codigo: 'MAP-70', descripcion: 'Router del mapa', marca: null },
            sku_divergence: { kind: 'otro_producto', producto_item_id: 71, codigo: 'SKU-71', descripcion: 'Switch del SKU' },
          }),
        ],
      }),
      facets: FACETS,
    });
    await page('/ml-publicaciones?vinculo=sku_divergente');
    expect(screen.getByRole('columnheader', { name: 'SKU distinto' })).toBeInTheDocument();
    const row = screen.getByText('MLA1100000001').closest('tr');
    expect(within(row).getByLabelText('Producto por SKU: SKU-71 Switch del SKU')).toBeInTheDocument();
    expect(within(row).getByLabelText('Producto vinculado: MAP-70 Router del mapa')).toBeInTheDocument();
  });

  it('without the filter there is no divergence column', async () => {
    await page();
    expect(screen.queryByRole('columnheader', { name: 'SKU distinto' })).not.toBeInTheDocument();
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

  it.each([
    ['Alt', { altKey: true }, 'https://vendedores.mercadolibre.com.ar/publicaciones?page=1&sort=DEFAULT&search=1100000001'],
    [
      'Shift',
      { shiftKey: true },
      'https://vendedores.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=1100000001',
    ],
  ])('%s+click anywhere on the row opens the seller panel, like Ctrl+click, and does not select it', async (_, keys, url) => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    try {
      await page();
      const row = screen.getByText('MLA1100000001').closest('tr');
      fireEvent.click(row, keys);
      expect(open).toHaveBeenCalledWith(url, '_blank', 'noopener,noreferrer');
      expect(openInMlPanel).not.toHaveBeenCalled();
      expect(row).not.toHaveAttribute('aria-current');
    } finally {
      open.mockRestore();
    }
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
  // MARKUP's "Actual": the markup at today's price, the worst variation (what the sort and the filters use).
  const WORST_HEADER = { name: /^Actual/ };

  it('without ver_ganancia there is no column, no controls, and no markup param (S68.1)', async () => {
    await page('/ml-publicaciones?markup_neg=1&markup_min=5&orden=markup');
    expect(screen.queryByRole('columnheader', { name: /Markup/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('switch', { name: /negativo/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Markup mínimo/)).not.toBeInTheDocument();
    for (const params of calls()) {
      expect(params).not.toHaveProperty('markup_neg');
      expect(params).not.toHaveProperty('markup_min');
      // The markup sort is dropped: the list asks for its default (Facturado 30D, the user sees the sales).
      expect(params.orden).toBe('facturado_30d');
    }
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    expect(screen.queryByRole('checkbox', { name: 'Markup actual' })).not.toBeInTheDocument();
  });

  it('with ver_ganancia MARKUP\'s "Actual" shows the range of today\'s markup, from the start', async () => {
    await withMargin();
    expect(screen.getByText('-4,0% – 12,0%')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', WORST_HEADER)).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /peor variación/ })).not.toBeInTheDocument();
  });

  it('clicking the header sorts by orden=markup, worst first', async () => {
    await withMargin();
    const sortButton = () => within(screen.getByRole('columnheader', WORST_HEADER)).getByRole('button');
    await userEvent.click(sortButton());
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'markup', dir: 'asc' }));
    await userEvent.click(sortButton());
    await waitFor(() => expect(lastParams()).toMatchObject({ orden: 'markup', dir: 'desc' }));
  });

  it('the picker lists the markup column under a name that stands alone', async () => {
    await withMargin();
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Markup actual' }));
    expect(screen.queryByRole('columnheader', WORST_HEADER)).not.toBeInTheDocument();
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
    expect(groupCalls()).toEqual([{ dimension: 'marca', familias: false, limit: 100, offset: 0 }]);
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

  describe('the dimension picker', () => {
    const picker = () => screen.queryByRole('group', { name: 'Agrupar por' });

    it('shows only in the tree, with the dimensions /groups takes, marca by default', async () => {
      const user = userEvent.setup();
      await page();
      expect(picker()).not.toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Agrupado' }));
      await screen.findByText('EPSON');
      const options = within(picker()).getAllByRole('button');
      expect(options.map((button) => button.textContent)).toEqual(['Marca', 'Categoría', 'Subcategoría', 'Tienda', 'PM']);
      expect(within(picker()).getByRole('button', { name: 'Marca' })).toHaveAttribute('aria-pressed', 'true');
    });

    it('changing it asks /groups again with the dimension and starts the tree over, collapsed', async () => {
      const user = userEvent.setup();
      await tree();
      await user.click(screen.getByRole('button', { name: /Abrir EPSON/ }));
      await waitFor(() => expect(groupCalls().some((params) => params.path)).toBe(true));
      publicacionesMlAPI.groups.mockResolvedValue({
        data: groupsResponse('categoria', [
          { kind: 'categoria', key: 'REDES', label: 'REDES', count: 4, leaf: false, params: { categorias: 'REDES' } },
        ]),
      });
      await user.click(within(picker()).getByRole('button', { name: 'Categoría' }));
      expect(await screen.findByText('REDES')).toBeInTheDocument();
      expect(groupCalls().at(-1)).toEqual({ dimension: 'categoria', familias: false, limit: 100, offset: 0 });
      expect(screen.queryByText('EPSON')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Abrir REDES/ })).toHaveAttribute('aria-expanded', 'false');
      expect(within(picker()).getByRole('button', { name: 'Categoría' })).toHaveAttribute('aria-pressed', 'true');
    });

    it('names the first column after the levels of the dimension, down to the publication', async () => {
      await tree();
      expect(
        screen.getByRole('columnheader', { name: /Marca › Categoría › Subcategoría › Producto › Publicación/ }),
      ).toBeInTheDocument();
    });

    it('names the family level too when families are on', async () => {
      await tree('/ml-publicaciones?vista=agrupado&familias=1');
      expect(
        screen.getByRole('columnheader', { name: /Producto › Familia › Publicación/ }),
      ).toBeInTheDocument();
    });

    it('reads the dimension from the URL and shows the subcategories by their backend title', async () => {
      publicacionesMlAPI.groups.mockResolvedValue({
        data: groupsResponse('subcategoria_categoria', [
          { kind: 'subcategoria_categoria', key: '12|REDES', label: 'Switches · REDES', count: 3, leaf: false, params: { subcategorias: '12' } },
        ]),
      });
      renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado&agrupar=subcategoria'] });
      expect(await screen.findByText('Switches · REDES')).toBeInTheDocument();
      expect(groupCalls()[0].dimension).toBe('subcategoria');
      expect(screen.getByRole('columnheader', { name: /^Subcategoría › Producto/ })).toBeInTheDocument();
      expect(screen.getByText('Subcategoría', { selector: 'span' })).toBeInTheDocument();
    });

    it('groups by tienda: the stores on top, tagged Tienda, and the header starts at the store', async () => {
      publicacionesMlAPI.groups.mockResolvedValue({
        data: groupsResponse('tienda', [
          { kind: 'tienda', key: 'c:GAUSS', label: 'GAUSS', count: 5, leaf: false, params: { tiendas: '57997,61000' } },
          { kind: 'tienda', key: '__none__', label: 'Sin tienda', count: 2, leaf: false, params: { tiendas: 'none' } },
        ]),
      });
      renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado&agrupar=tienda'] });
      expect(await screen.findByText('GAUSS')).toBeInTheDocument();
      expect(groupCalls()[0].dimension).toBe('tienda');
      expect(
        screen.getByRole('columnheader', { name: /^Tienda › Marca › Categoría › Subcategoría › Producto › Publicación/ }),
      ).toBeInTheDocument();
      expect(screen.getAllByText('Tienda', { selector: 'span' })).toHaveLength(2);
    });

    it('groups by PM: the PMs on top, tagged PM, and the header starts at the PM', async () => {
      publicacionesMlAPI.groups.mockResolvedValue({
        data: groupsResponse('pm', [
          { kind: 'pm', key: '7', label: 'Ana Pérez', count: 5, leaf: false, params: { pm_grupo: '7' } },
          { kind: 'pm', key: '__none__', label: 'Sin PM', count: 2, leaf: false, params: { pm_grupo: '__none__' } },
        ]),
      });
      renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado&agrupar=pm&familias=1'] });
      expect(await screen.findByText('Ana Pérez')).toBeInTheDocument();
      expect(groupCalls()[0]).toMatchObject({ dimension: 'pm', familias: true });
      expect(
        screen.getByRole('columnheader', { name: /^PM › Marca › Categoría › Subcategoría › Producto › Familia › Publicación/ }),
      ).toBeInTheDocument();
      expect(screen.getAllByText('PM', { selector: 'span' })).toHaveLength(2);
    });

    it('keeps the family toggle working under another dimension', async () => {
      await tree('/ml-publicaciones?vista=agrupado&agrupar=categoria&familias=1');
      expect(groupCalls()[0]).toMatchObject({ dimension: 'categoria', familias: true });
    });
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

describe('the Producto view', () => {
  const productCalls = () => publicacionesMlAPI.products.mock.calls.map(([params]) => params);
  const products = async (entry = '/ml-publicaciones?vista=producto') => {
    renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
    await screen.findByText('Router Archer AX55');
  };

  beforeEach(() => {
    publicacionesMlAPI.products.mockReset();
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse(undefined, { total: 120 }) });
  });

  it('offers the views in Métricas ML order: Producto, Publicaciones, Agrupado', async () => {
    await page();
    const views = within(screen.getByRole('group', { name: 'Vista' })).getAllByRole('button');
    expect(views.map((button) => button.textContent)).toEqual(['Producto', 'Publicaciones', 'Agrupado']);
    expect(screen.getByRole('button', { name: 'Publicaciones' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows the products for vista=producto, by Facturado 30D, the page in the URL', async () => {
    await products('/ml-publicaciones?vista=producto&estado=active&pagina=2');
    expect(productCalls()).toEqual([{ estado: 'active', orden: 'facturado_30d', dir: 'desc', limit: 50, offset: 50 }]);
    expect(screen.getByRole('table', { name: /por producto/ })).toBeInTheDocument();
    expect(screen.getByText(/de 120 productos/)).toBeInTheDocument();
  });

  it('asks /items only for the state and the facet counts', async () => {
    await products();
    await waitFor(() => expect(publicacionesMlAPI.items).toHaveBeenCalled());
    expect(lastParams()).toEqual({ limit: 1, offset: 0, facets: true });
  });

  it('switches to it from the header, in the URL', async () => {
    const user = userEvent.setup();
    await page();
    await user.click(screen.getByRole('button', { name: 'Producto' }));
    await screen.findByText('Router Archer AX55');
    expect(screen.queryByText('MLA1100000001')).not.toBeInTheDocument();
  });

  it('sorts the products from a figure header', async () => {
    const user = userEvent.setup();
    await products();
    await user.click(screen.getByRole('button', { name: /^7D/ }));
    await waitFor(() => expect(productCalls().at(-1)).toMatchObject({ orden: 'unidades_7d', dir: 'desc' }));
  });

  it('opens a publication of a product in the side panel, as the list does', async () => {
    publicacionesMlAPI.detail.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    await products();
    await user.click(screen.getByRole('button', { name: /Abrir Router Archer AX55/ }));
    await user.click(await screen.findByText('MLA1100000001'));
    expect(await screen.findByRole('complementary', { name: 'Detalle de la publicación' })).toBeInTheDocument();
  });

  it('does not offer the markup filters it does not apply', async () => {
    canSeeMargin = true;
    await products('/ml-publicaciones?vista=producto&markup_neg=1');
    expect(screen.queryByText('Markup:')).not.toBeInTheDocument();
    expect(productCalls()[0]).not.toHaveProperty('markup_neg');
  });
});

describe('the product panel', () => {
  const productPanel = () => screen.queryByRole('complementary', { name: 'Detalle del producto' });
  const publicationPanel = () => screen.queryByRole('complementary', { name: 'Detalle de la publicación' });
  const products = async (entry = '/ml-publicaciones?vista=producto') => {
    renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
    await within(await screen.findByRole('table', { name: /por producto/ })).findByText('Router Archer AX55');
  };
  const rowOf = (text) => within(screen.getByRole('table', { name: /por producto/ })).getByText(text).closest('tr');

  beforeEach(() => {
    publicacionesMlAPI.products.mockReset();
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse(undefined, { total: 120 }) });
  });

  it('a click on a product opens its panel, highlights its row and does not expand it', async () => {
    const user = userEvent.setup();
    await products();
    await user.click(rowOf('Router Archer AX55'));
    const opened = await screen.findByRole('complementary', { name: 'Detalle del producto' });
    expect(await within(opened).findByRole('heading', { name: 'Router Archer AX55' })).toBeInTheDocument();
    expect(publicacionesMlAPI.products).toHaveBeenCalledWith(expect.objectContaining({ producto: '4101', limit: 1 }));
    expect(screen.getByRole('button', { name: /Abrir Router Archer AX55/ })).toHaveAttribute('aria-expanded', 'false');
    expect(rowOf('Router Archer AX55')).toHaveAttribute('aria-current', 'true');
    expect(publicationPanel()).not.toBeInTheDocument();
  });

  it('a publication of the panel opens its own panel, which goes back to the product', async () => {
    const user = userEvent.setup();
    await products('/ml-publicaciones?vista=producto&prod=4101');
    const opened = await screen.findByRole('complementary', { name: 'Detalle del producto' });
    await user.click(await within(opened).findByRole('button', { name: /MLA1100000001/ }));

    const detail = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    expect(productPanel()).not.toBeInTheDocument();
    await user.click(within(detail).getByRole('button', { name: 'Volver a Router Archer AX55' }));

    expect(await screen.findByRole('complementary', { name: 'Detalle del producto' })).toBeInTheDocument();
    expect(publicationPanel()).not.toBeInTheDocument();
  });

  it('a publication opened from the list has no way back to a product', async () => {
    const user = userEvent.setup();
    await products();
    await user.click(screen.getByRole('button', { name: /Abrir Router Archer AX55/ }));
    await user.click(await screen.findByText('MLA1100000001'));
    const detail = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    expect(within(detail).queryByRole('button', { name: /^Volver/ })).not.toBeInTheDocument();
  });

  it('closing it clears the product', async () => {
    const user = userEvent.setup();
    await products('/ml-publicaciones?vista=producto&prod=4101');
    const opened = await screen.findByRole('complementary', { name: 'Detalle del producto' });
    await user.click(within(opened).getByRole('button', { name: 'Cerrar panel' }));
    await waitFor(() => expect(productPanel()).not.toBeInTheDocument());
    expect(rowOf('Router Archer AX55')).not.toHaveAttribute('aria-current');
  });

  it('a filter change closes it', async () => {
    const user = userEvent.setup();
    await products('/ml-publicaciones?vista=producto&prod=4101');
    await screen.findByRole('complementary', { name: 'Detalle del producto' });
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await user.click(within(estado).getByRole('button', { name: /Activas/ }));
    await waitFor(() => expect(productPanel()).not.toBeInTheDocument());
  });

  it('the Agrupado view still opens its nodes on a click, with no product panel', async () => {
    const user = userEvent.setup();
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado'] });
    await user.click(await screen.findByText('EPSON'));
    await waitFor(() => expect(screen.getByRole('button', { name: /Cerrar EPSON/ })).toBeInTheDocument());
    expect(productPanel()).not.toBeInTheDocument();
  });
});

describe('the product filters (Marca, Categoría, Subcategoría, PM)', () => {
  const URL_FILTERS = 'marcas=TP%252CLINK&categorias=REDES&subcategorias=12&pms=7';
  const SENT = { marcas: 'TP%2CLINK', categorias: 'REDES', subcategorias: '12', pms: '7' };

  beforeEach(() => {
    publicacionesMlAPI.products.mockReset();
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse(undefined, { total: 120 }) });
  });

  it.each([
    ['Publicaciones', '/ml-publicaciones', 'MLA1100000001'],
    ['Producto', '/ml-publicaciones?vista=producto', 'Router Archer AX55'],
    ['Agrupado', '/ml-publicaciones?vista=agrupado', 'EPSON'],
  ])('are offered under "Producto:" in the %s view', async (_view, entry, ready) => {
    renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
    await screen.findByText(ready);
    const card = screen.getByRole('region', { name: 'Filtros' });
    expect(within(card).getByText('Producto:')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Subcategoría' })).toBeInTheDocument();
  });

  it('reach /items from the URL', async () => {
    await page(`/ml-publicaciones?${URL_FILTERS}`);
    expect(lastParams()).toMatchObject(SENT);
  });

  it('reach /products in the Producto view', async () => {
    renderWithRouter(<PublicacionesML />, { initialEntries: [`/ml-publicaciones?vista=producto&${URL_FILTERS}`] });
    await screen.findByText('Router Archer AX55');
    expect(publicacionesMlAPI.products.mock.calls[0][0]).toMatchObject(SENT);
  });

  it('reach /groups in the Agrupado view', async () => {
    renderWithRouter(<PublicacionesML />, { initialEntries: [`/ml-publicaciones?vista=agrupado&${URL_FILTERS}`] });
    await screen.findByText('EPSON');
    expect(publicacionesMlAPI.groups.mock.calls[0][0]).toMatchObject(SENT);
  });

  it('a picked brand filters the list and goes back to page 1', async () => {
    const user = userEvent.setup();
    await page('/ml-publicaciones?pagina=2');
    await user.click(screen.getByRole('button', { name: 'Marca' }));
    await user.click(await screen.findByLabelText('TP,LINK'));
    await waitFor(() => expect(lastParams().marcas).toBe('TP%2CLINK'));
    expect(lastParams().offset).toBe(0);
  });

  it('show a chip per active value, and "Limpiar filtros" clears them too', async () => {
    const user = userEvent.setup();
    await page(`/ml-publicaciones?${URL_FILTERS}`);
    expect(screen.getByRole('button', { name: 'Quitar Marca: TP,LINK' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Quitar PM: Ana' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    await waitFor(() => expect(lastParams()).not.toHaveProperty('marcas'));
    expect(lastParams()).not.toHaveProperty('pms');
  });
});

describe('bulk actions over products (S6)', () => {
  const pick = (mla) => screen.getByRole('checkbox', { name: `Seleccionar el producto de ${mla}` });

  it('asks the products of the filter and shows their count', async () => {
    await page('/ml-publicaciones?estado=active');
    expect(await screen.findByRole('button', { name: 'Acciones masivas (2 productos)' })).toBeEnabled();
    expect(publicacionesMlAPI.productIds.mock.calls.at(-1)[0]).toEqual({ estado: 'active' });
  });

  it('checking a publication checks its product; a publication with no product cannot be checked', async () => {
    await page();
    await userEvent.click(pick('MLA1100000001'));
    expect(await screen.findByRole('button', { name: 'Acciones masivas (1 producto seleccionado)' })).toBeEnabled();
    expect(pick('MLA1100000001')).toBeChecked();
    expect(pick('MLA1100000004')).toBeDisabled();
  });

  it('a filter change clears the checked products', async () => {
    await page();
    await userEvent.click(pick('MLA1100000001'));
    await screen.findByRole('button', { name: 'Acciones masivas (1 producto seleccionado)' });
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await userEvent.click(within(estado).getByRole('button', { name: /Activas/ }));
    expect(await screen.findByRole('button', { name: 'Acciones masivas (2 productos)' })).toBeInTheDocument();
  });

  it('in the Producto view a product row checks the product; "Sin producto" cannot be checked', async () => {
    publicacionesMlAPI.products.mockReset();
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse(undefined, { total: 120 }) });
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=producto'] });
    await screen.findByText('Router Archer AX55');
    await userEvent.click(pick('Router Archer AX55'));
    expect(await screen.findByRole('button', { name: 'Acciones masivas (1 producto seleccionado)' })).toBeEnabled();
    expect(pick('Sin producto')).toBeDisabled();
  });
});

describe('CSV export of the current view (S7)', () => {
  const exportButton = () => screen.getByRole('button', { name: /Exportar CSV/ });
  // The list's own request without the page and the facets: the file holds what the list holds, every page of it.
  const withoutPaging = ({ limit, offset, facets, ...params }) => {
    void limit, offset, facets;
    return params;
  };

  beforeEach(() => {
    exportPublicacionesCsv.mockReset();
    exportPublicacionesCsv.mockResolvedValue(undefined);
    publicacionesMlAPI.products.mockReset();
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse(undefined, { total: 120 }) });
  });

  it('exports the Publicación view with exactly the list request, minus the page', async () => {
    canSeeMargin = true;
    await page('/ml-publicaciones?q=router&estado=active,paused&tiendas=sin_tienda&orden=markup&dir=asc&markup_min=5&pagina=3');
    await userEvent.click(exportButton());
    expect(exportPublicacionesCsv).toHaveBeenCalledTimes(1);
    const [vista, params] = exportPublicacionesCsv.mock.calls[0];
    expect(vista).toBe('publicacion');
    expect(params).toEqual(withoutPaging(lastParams()));
    expect(params).toMatchObject({ q: 'router', estado: 'active,paused', tiendas: 'none', orden: 'markup', dir: 'asc', markup_min: '5' });
  });

  it('exports the Producto view with exactly the products request, minus the page', async () => {
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=producto&estado=active&pagina=2'] });
    await screen.findByText('Router Archer AX55');
    await userEvent.click(exportButton());
    const [vista, params] = exportPublicacionesCsv.mock.calls[0];
    expect(vista).toBe('producto');
    expect(params).toEqual(withoutPaging(publicacionesMlAPI.products.mock.calls.at(-1)[0]));
    expect(params).toEqual({ estado: 'active', orden: 'facturado_30d', dir: 'desc' });
  });

  it('offers no export in the Agrupado view', async () => {
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado'] });
    await screen.findByText('EPSON');
    expect(screen.queryByRole('button', { name: /Exportar CSV/ })).not.toBeInTheDocument();
  });

  it('shows "Exportando…" while the file downloads', async () => {
    let finish;
    exportPublicacionesCsv.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    await page();
    await userEvent.click(exportButton());
    expect(screen.getByRole('button', { name: /Exportando/ })).toBeDisabled();
    finish();
    expect(await screen.findByRole('button', { name: /Exportar CSV/ })).toBeEnabled();
  });

  it('shows the backend message when the export is refused', async () => {
    exportPublicacionesCsv.mockRejectedValue(new Error('Son 12000 publicaciones (máximo 10000). Acotá los filtros.'));
    await page();
    await userEvent.click(exportButton());
    expect(await screen.findByRole('alert')).toHaveTextContent('Son 12000 publicaciones (máximo 10000). Acotá los filtros.');
  });

  const narrow = async () => {
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await userEvent.click(within(estado).getByRole('button', { name: /Activas/ }));
    await waitFor(() => expect(lastParams().estado).toBe('active'));
  };

  it('narrowing the filters clears the refusal, so the operator can retry', async () => {
    exportPublicacionesCsv.mockRejectedValue(new Error('Son 12000 publicaciones (máximo 10000). Acotá los filtros.'));
    await page();
    await userEvent.click(exportButton());
    await screen.findByRole('alert');
    await narrow();
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('a refusal for a list the operator already left is not shown under the new filters', async () => {
    let refuse;
    exportPublicacionesCsv.mockReturnValue(new Promise((_, reject) => (refuse = reject)));
    await page();
    await userEvent.click(exportButton());
    await narrow();
    refuse(new Error('Son 12000 publicaciones (máximo 10000). Acotá los filtros.'));
    expect(await screen.findByRole('button', { name: /Exportar CSV/ })).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('Exportar a Sheets', () => {
  const sheetsButton = () => screen.getByRole('button', { name: 'Exportar a Sheets' });

  beforeEach(() => {
    vi.stubEnv('VITE_GOOGLE_CLIENT_ID', 'client-123');
    exportPublicacionesCsv.mockReset();
    exportPublicacionesCsv.mockResolvedValue(undefined);
    exportPublicacionesSheets.mockReset();
    exportPublicacionesSheets.mockResolvedValue({ url: 'https://docs.google.com/spreadsheets/d/sid', opened: true });
    loadGoogleIdentity.mockClear();
  });
  afterEach(() => vi.unstubAllEnvs());

  it('is not offered without a Google client id', async () => {
    vi.stubEnv('VITE_GOOGLE_CLIENT_ID', '');
    await page();
    expect(screen.queryByRole('button', { name: /Sheets/ })).not.toBeInTheDocument();
    expect(loadGoogleIdentity).not.toHaveBeenCalled();
  });

  it('is not offered in the Agrupado view, like the CSV', async () => {
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=agrupado'] });
    await screen.findByText('EPSON');
    expect(screen.queryByRole('button', { name: /Sheets/ })).not.toBeInTheDocument();
  });

  it('sends exactly the view and request of "Exportar CSV"', async () => {
    canSeeMargin = true;
    await page('/ml-publicaciones?q=router&orden=markup&dir=asc&pagina=3');
    expect(loadGoogleIdentity).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /Exportar CSV/ }));
    await userEvent.click(sheetsButton());
    expect(exportPublicacionesSheets).toHaveBeenCalledTimes(1);
    expect(exportPublicacionesSheets.mock.calls[0]).toEqual(exportPublicacionesCsv.mock.calls[0]);
    expect(exportPublicacionesSheets.mock.calls[0][0]).toBe('publicacion');
  });

  it('says "Exportando a Sheets…" while it works', async () => {
    let finish;
    exportPublicacionesSheets.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    await page();
    await userEvent.click(sheetsButton());
    expect(screen.getByRole('button', { name: 'Exportando a Sheets…' })).toBeDisabled();
    // The page says it is processing and the browser asks before a reload or close would kill the export.
    expect(screen.getByText('Exportando a Google Sheets…')).toBeInTheDocument();
    const unload = () => {
      const event = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(unload()).toBe(true);
    finish({ url: 'u', opened: true });
    expect(await screen.findByRole('button', { name: 'Exportar a Sheets' })).toBeEnabled();
    expect(screen.queryByText('Exportando a Google Sheets…')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Abrir en Google Sheets' })).toBeInTheDocument();
    expect(unload()).toBe(false);
  });

  it('shows a refusal like the CSV export does', async () => {
    exportPublicacionesSheets.mockRejectedValue(new Error('La consulta tardó demasiado.'));
    await page();
    await userEvent.click(sheetsButton());
    expect(await screen.findByRole('alert')).toHaveTextContent('La consulta tardó demasiado.');
  });

  it('a cancelled Google popup is a quiet note, not an error', async () => {
    exportPublicacionesSheets.mockRejectedValue(Object.assign(new Error('Exportación cancelada'), { cancelled: true }));
    await page();
    await userEvent.click(sheetsButton());
    expect(await screen.findByRole('status')).toHaveTextContent('Exportación cancelada');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('when the browser blocked the new tab, links to the sheet', async () => {
    exportPublicacionesSheets.mockResolvedValue({ url: 'https://docs.google.com/spreadsheets/d/sid', opened: false });
    await page();
    await userEvent.click(sheetsButton());
    const link = await screen.findByRole('link', { name: 'Abrir en Google Sheets' });
    expect(link).toHaveAttribute('href', 'https://docs.google.com/spreadsheets/d/sid');
  });

  it('links to the new sheet even when its tab seemed to open (a browser can block it silently)', async () => {
    await page();
    await userEvent.click(sheetsButton());
    const link = await screen.findByRole('link', { name: 'Abrir en Google Sheets' });
    expect(link).toHaveAttribute('href', 'https://docs.google.com/spreadsheets/d/sid');
    expect(screen.getByRole('status')).toHaveTextContent('Hoja creada en Google Sheets');
  });

  it('a filter change drops the note about the previous list', async () => {
    exportPublicacionesSheets.mockRejectedValue(Object.assign(new Error('Exportación cancelada'), { cancelled: true }));
    await page();
    await userEvent.click(sheetsButton());
    await screen.findByText('Exportación cancelada');
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await userEvent.click(within(estado).getByRole('button', { name: /Activas/ }));
    await waitFor(() => expect(screen.queryByText('Exportación cancelada')).not.toBeInTheDocument());
  });

  it('a popup closed after a filter change says nothing under the new list', async () => {
    let cancel;
    exportPublicacionesSheets.mockReturnValue(new Promise((_, reject) => (cancel = reject)));
    await page();
    await userEvent.click(sheetsButton());
    const estado = screen.getByRole('group', { name: 'Filtrar por estado' });
    await userEvent.click(within(estado).getByRole('button', { name: /Activas/ }));
    await act(async () => cancel(Object.assign(new Error('Exportación cancelada'), { cancelled: true })));
    expect(screen.queryByText('Exportación cancelada')).not.toBeInTheDocument();
  });
});

describe('the color layer (S8)', () => {
  it('lists the global layer and the teams, and asks the rows on the chosen one', async () => {
    await page();
    const capa = await screen.findByRole('combobox', { name: 'Capa de color' });
    expect(within(capa).getAllByRole('option').map((o) => o.textContent)).toEqual(['Global', 'Ventas']);
    await userEvent.selectOptions(capa, '12');
    await waitFor(() => expect(lastParams()).toMatchObject({ equipo_id: '12' }));
  });

  it("drops a layer the user has no team for (a link shared by someone else): the list is asked on the global one", async () => {
    await page('/ml-publicaciones?equipo=99');
    await waitFor(() => expect(lastParams()).not.toHaveProperty('equipo_id'));
    expect(screen.getByRole('combobox', { name: 'Capa de color' })).toHaveValue('');
    // Never asked on that layer, not even before the teams loaded: the 403 would flash a false error.
    expect(calls().map((params) => params.equipo_id)).not.toContain('99');
  });

  it('a team layer from the link is asked once the teams say it is the user\'s, with no request before', async () => {
    await page('/ml-publicaciones?equipo=12');
    expect(calls().map((params) => params.equipo_id)).toEqual(['12']);
  });

  it("paints a publication with its product's color", async () => {
    respond({ ...ITEMS_RESPONSE, items: [{ ...ITEMS[0], color_marcado: 'rojo' }, ...ITEMS.slice(1)], facets: FACETS });
    await page();
    expect(screen.getByText('MLA1100000001').closest('tr')).toHaveAttribute('data-tone');
  });
});

describe('painting colors (S8)', () => {
  const firstRow = () => screen.getByText('MLA1100000001').closest('tr');

  it("repaints the rows of a product someone paints on the layer on show, and ignores another team's", async () => {
    await page();
    expect(firstRow()).not.toHaveAttribute('data-tone');
    act(() => sse.listener({ data: { vista: 'ml', is_global: false, equipo_id: 99, item_ids: [4101], color: 'rojo' } }));
    expect(firstRow()).not.toHaveAttribute('data-tone');
    act(() => sse.listener({ data: { vista: 'ml', is_global: true, equipo_id: 1, item_ids: [4101], color: 'rojo' } }));
    expect(firstRow()).toHaveAttribute('data-tone');
  });

  it('paints the checked products from the list, without asking the list again', async () => {
    await page();
    const asked = publicacionesMlAPI.items.mock.calls.length;
    await userEvent.click(within(firstRow()).getByRole('checkbox', { name: /Seleccionar el producto de/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Pintar 1 producto' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'OK' }));
    await waitFor(() => expect(firstRow()).toHaveAttribute('data-tone'));
    expect(api.post).toHaveBeenCalledWith('/productos/actualizar-color-lote', { item_ids: [4101], color: 'verde' });
    expect(publicacionesMlAPI.items.mock.calls.length).toBe(asked);
    expect(screen.queryByRole('button', { name: /Pintar/ })).not.toBeInTheDocument();
  });
});

describe('keyboard shortcuts', () => {
  it('the header button and ? open the help; Ctrl+F goes to the search; ↓ then Enter opens a publication', async () => {
    const user = userEvent.setup();
    await page();
    await user.click(screen.getByRole('button', { name: 'Atajos de teclado' }));
    expect(screen.getByRole('heading', { name: 'Atajos de teclado' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Atajos de teclado' })).not.toBeInTheDocument());
    await user.keyboard('?');
    expect(screen.getByRole('heading', { name: 'Atajos de teclado' })).toBeInTheDocument();
    await user.keyboard('?');
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Atajos de teclado' })).not.toBeInTheDocument());

    await user.keyboard('{Control>}f{/Control}');
    expect(screen.getByPlaceholderText(/Buscar por título/)).toHaveFocus();

    screen.getByPlaceholderText(/Buscar por título/).blur();
    await user.keyboard('{ArrowDown}{Enter}');
    await waitFor(() => expect(publicacionesMlAPI.detail).toHaveBeenCalledWith(ITEMS[0].item_id));
  });
});

describe('bulk actions and filters from the keyboard (S9b)', () => {
  it('Ctrl+K opens Calcular Web Transf. and Ctrl+Shift+P opens Calcular PVP over the filtered products', async () => {
    const user = userEvent.setup();
    await page();
    await screen.findByRole('button', { name: 'Acciones masivas (2 productos)' });
    await user.keyboard('{Control>}k{/Control}');
    expect(await screen.findByRole('heading', { name: /Calcular Precios Web Transferencia/ })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: /Calcular Precios Web Transferencia/ })).not.toBeInTheDocument(),
    );
    await user.keyboard('{Control>}{Shift>}P{/Shift}{/Control}');
    expect(await screen.findByRole('heading', { name: /Calcular Precios PVP/ })).toBeInTheDocument();
  });

  it('Alt+M, Alt+S and Alt+P open the Marca, Subcategoría and PM filters', async () => {
    const user = userEvent.setup();
    await page();
    await user.keyboard('{Alt>}m{/Alt}');
    expect(await screen.findByLabelText('TP,LINK')).toBeInTheDocument();
    await user.keyboard('{Alt>}p{/Alt}');
    await waitFor(() => expect(screen.queryByLabelText('TP,LINK')).not.toBeInTheDocument());
    expect(await screen.findByLabelText('Ana')).toBeInTheDocument();
    await user.keyboard('{Alt>}s{/Alt}');
    await waitFor(() => expect(screen.queryByLabelText('Ana')).not.toBeInTheDocument());
  });
});

describe('keyboard export', () => {
  it('Ctrl+E while an export runs starts no second one and is not left to the browser', async () => {
    let finish;
    exportPublicacionesCsv.mockReset();
    exportPublicacionesCsv.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup();
    await page();
    await user.keyboard('{Control>}e{/Control}');
    expect(screen.getByRole('button', { name: 'Exportando…' })).toBeDisabled();
    // Still taken from the browser (Chrome would jump to its address bar), and no second export starts.
    expect(fireEvent.keyDown(document.body, { key: 'e', code: 'KeyE', ctrlKey: true })).toBe(false);
    expect(exportPublicacionesCsv).toHaveBeenCalledTimes(1);
    await act(async () => finish());
  });
});

describe('painting from the keyboard (S8)', () => {
  const firstRow = () => screen.getByText('MLA1100000001').closest('tr');

  it("a digit paints the focused publication's product on the layer on show, as Productos' quick colors", async () => {
    const user = userEvent.setup();
    await page('/ml-publicaciones?equipo=12');
    await screen.findByRole('option', { name: 'Ventas' });
    firstRow().focus();
    await user.keyboard('4');
    await waitFor(() => expect(firstRow()).toHaveAttribute('data-tone'));
    expect(api.patch).toHaveBeenCalledWith('/productos/4101/color', { color: 'verde' }, { params: { equipo_id: 12 } });
  });

  it('says so for a publication with no product, and paints nothing', async () => {
    const user = userEvent.setup();
    api.patch.mockClear();
    await page();
    screen.getByText('MLA1100000003').closest('tr').focus();
    await user.keyboard('1');
    expect(await screen.findByText('La publicación no tiene producto vinculado')).toBeInTheDocument();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('F7 / F6 step through Global and the teams, and say which layer is on', async () => {
    const user = userEvent.setup();
    await page();
    await screen.findByRole('option', { name: 'Ventas' });
    await user.keyboard('{F7}');
    await waitFor(() => expect(lastParams()).toMatchObject({ equipo_id: '12' }));
    expect(await screen.findByText('Capa: Ventas')).toBeInTheDocument();
    await user.keyboard('{F6}');
    await waitFor(() => expect(lastParams()).not.toHaveProperty('equipo_id'));
  });
});
