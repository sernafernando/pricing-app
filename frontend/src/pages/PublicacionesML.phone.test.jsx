/**
 * Publicaciones ML on a phone (mobile-metricas-pubml T2, S2-S5): cards instead of the table, the filters in a
 * bottom sheet, "Cargar 20 más", and the panel full screen with a way back to the list. `useIsPhone` is forced on;
 * every other test renders the desktop layout (jsdom's `matchMedia` never matches).
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import PublicacionesML from './PublicacionesML';
import { publicacionesMlAPI } from '../services/api';
import { openInMlPanel } from '../utils/mlSidePanel';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import {
  BRAND_NODES,
  FACETS,
  ITEMS,
  ITEMS_RESPONSE,
  DETAIL_RESPONSE,
  groupsResponse,
  KPIS_RESPONSE,
  VARIATIONS_RESPONSE,
} from '../test/visual/publicacionesMlFixtures';

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    patch: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosPropiosAPI: { get: vi.fn(() => new Promise(() => {})), save: vi.fn() },
  // The publication panel opens on Promos (owner, 2026-11-02): its promotions never answer here, these tests are
  // about the panel's opening and closing.
  promocionesAPI: { getPromocionesItem: vi.fn(() => new Promise(() => {})), refreshItemPromociones: vi.fn(() => new Promise(() => {})) },
  publicacionesMlAPI: { items: vi.fn(), products: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), enqueue: vi.fn(), kpis: vi.fn(), productIds: vi.fn(), stats: vi.fn(), statusItemIds: vi.fn(), statusItemIdsChecked: vi.fn(), statusBulk: vi.fn(), paintColors: vi.fn() },
  productosAPI: {
    // The product panel's publication tree (Productos' `ProductoMLAsPanel`): the product's publication.
    getProductoTree: vi.fn(() =>
      Promise.resolve({
        data: {
          item_id: 4101,
          tree: { level: 0, kind: 'producto', label: 'Router Archer AX55', children: [{ level: 1, kind: 'publicacion', mla: 'MLA1100000001', label: 'Router Archer AX55', children: [] }] },
        },
      }),
    ),
    marcas: vi.fn(() => Promise.resolve({ data: { marcas: ['TP,LINK', 'EPSON'] } })),
    categorias: vi.fn(() => Promise.resolve({ data: { categorias: ['REDES'] } })),
    subcategorias: vi.fn(() => Promise.resolve({ data: { categorias: [] } })),
    pms: vi.fn(() => Promise.resolve({ data: [{ id: 7, nombre: 'Ana' }] })),
    // The product panel's last purchases: no purchase, these tests are about the panel's opening and closing.
    detalle: vi.fn(() => Promise.resolve({ data: { producto: {}, pricing: {}, ultimas_compras: [] } })),
    listar: vi.fn(() => Promise.resolve({ data: { productos: [], total: 0 } })),
  },
  equiposAPI: {
    listar: vi.fn(() =>
      Promise.resolve({ data: [{ id: 1, nombre: 'U', es_global: true }, { id: 12, nombre: 'Ventas', es_global: false }] }),
    ),
  },
  preciosAPI: {
    calcularMarkup: vi.fn(() => Promise.resolve({ data: { markup: 10 } })),
    setRapido: vi.fn(() => Promise.resolve({ data: {} })),
    setCuota: vi.fn(() => Promise.resolve({ data: {} })),
    setRebate: vi.fn(() => Promise.resolve({ data: {} })),
    setWebTransferencia: vi.fn(() => Promise.resolve({ data: {} })),
    setOutOfCards: vi.fn(() => Promise.resolve({ data: {} })),
    tipoCambioActual: vi.fn(() => Promise.resolve({ data: { venta: 1000 } })),
    // The panel's Precios tab (`ProductPrices`) reads the product on its own.
    obtenerProducto: vi.fn(() => Promise.resolve({ data: { item_id: 4101, codigo: 'ARCHER-AX55', descripcion: 'Router Archer AX55' } })),
  },
  // No current offset unless a test says so: Productos' "markup con offsets" stays out of the cells.
  offsetsGananciaAPI: { vigentes: vi.fn(() => Promise.resolve({ data: [] })), grupoFiltros: vi.fn(() => Promise.resolve({ data: [] })) },
  registerAuthFailureHandler: vi.fn(),
}));

// jsdom lays nothing out: a test that needs the end of a long list in view says so (`virtualView.all`), and the
// virtualizer then shows every row; otherwise it is the real one.
const virtualView = vi.hoisted(() => ({ all: false }));
vi.mock('@tanstack/react-virtual', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useVirtualizer: (options) => {
      const real = actual.useVirtualizer(options);
      if (!virtualView.all) return real;
      const items = Array.from({ length: options.count }, (_, index) => ({
        index,
        key: options.getItemKey(index),
        start: index * 56,
        end: (index + 1) * 56,
      }));
      return Object.assign(Object.create(real), {
        getVirtualItems: () => items,
        getTotalSize: () => options.count * 56,
        measureElement: () => {},
      });
    },
  };
});

vi.mock('../hooks/useIsPhone', () => ({ default: () => true }));

// Team management has its own tests; here only that the page opens it and reloads its teams after.
vi.mock('../components/EquiposModal', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div role="dialog" aria-label="Gestión de equipos">
        <button type="button" onClick={onClose}>
          Cerrar equipos
        </button>
      </div>
    ) : null,
}));

// The color events (`producto_color:changed`, and a publication's own `publicacion_color:changed`) are pushed by
// each test through the captured listeners.
const sse = { listener: null, own: null };
vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: (channel, callback) => {
    if (channel === 'producto_color:changed') sse.listener = callback;
    if (channel === 'publicacion_color:changed') sse.own = callback;
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
// Productos' prices (S11): `productos.ver` or a price-edit code (`canViewProductPrices`).
let canSeePrices = true;
// Writing them (S11c): the Productos and Tienda edit codes (`pricePermissions`).
let canEditPrices = true;
let denied = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => {
      if (denied.has(permiso)) return false;
      if (permiso === 'ml_metricas.ver_ganancia') return canSeeMargin;
      if (permiso === 'ml_metricas.ver') return canSeeKpis;
      if (/^(productos\.(editar|toggle)|tienda\.editar)/.test(permiso)) return canSeePrices && canEditPrices;
      if (permiso.startsWith('productos.') || permiso.startsWith('tienda.')) return canSeePrices;
      return true;
    },
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const respond = (body) => publicacionesMlAPI.items.mockResolvedValue({ data: body });

const STATS_RESPONSE = {
  stats: { total: 40, con_stock: 30, con_precio: 35, con_stock_sin_precio: 3, nuevos: 5, nuevos_sin_precio: 2, oferta_sin_rebate: 4 },
  can_see_margin: false,
};

const page = async (entry = '/ml-publicaciones') => {
  renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
  await screen.findByText('MLA1100000001');
};

beforeEach(() => {
  canSeeMargin = false;
  canSeeKpis = true;
  canSeePrices = true;
  canEditPrices = true;
  denied = new Set();
  publicacionesMlAPI.kpis.mockReset();
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE });
  publicacionesMlAPI.stats.mockReset();
  publicacionesMlAPI.stats.mockResolvedValue({ data: STATS_RESPONSE });
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

const card = (title) => screen.getByRole('button', { name: new RegExp(title) });

describe('Publicaciones ML on a phone (mobile-metricas-pubml S2)', () => {
  it('shows each publication as a card, without the table nor its prices', async () => {
    await page();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    const router = card('Router TP-Link Archer AX55');
    expect(within(router).getByText('MLA1100000001')).toBeInTheDocument();
    expect(within(router).getByText('TP-Link')).toBeInTheDocument();
    expect(within(router).getByText('Ventas 30D')).toBeInTheDocument();
    expect(within(router).getByText('Stock')).toBeInTheDocument();
    expect(within(router).queryByText('Precio')).not.toBeInTheDocument();
    expect(within(card('Mouse inalámbrico Logitech')).getByText('3 variaciones')).toBeInTheDocument();
    expect(screen.getByText('235 publicaciones')).toBeInTheDocument();
  });

  it('opens the filters in a sheet and closes it with "Ver N publicaciones"', async () => {
    await page();
    await userEvent.click(screen.getByRole('button', { name: /^Filtros/ }));
    const sheet = screen.getByRole('dialog', { name: 'Filtros' });
    expect(within(sheet).getByText('Tipo')).toBeInTheDocument();
    expect(within(sheet).getByText('Vínculo')).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole('button', { name: 'Ver 235 publicaciones' }));
    expect(screen.queryByRole('dialog', { name: 'Filtros' })).not.toBeInTheDocument();
  });

  it('filters by state from the quick chips, and counts the filters on the Filtros button', async () => {
    await page();
    const activas = screen.getByRole('button', { name: 'Activas' });
    expect(activas).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(activas);
    expect(activas).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(publicacionesMlAPI.items).toHaveBeenLastCalledWith(expect.objectContaining({ estado: 'active' })));
    expect(screen.getByRole('button', { name: /^Filtros/ })).toHaveTextContent(/Filtros\s*1/);
  });

  it('loads the next 20 publications under the cards', async () => {
    await page();
    publicacionesMlAPI.items.mockResolvedValueOnce({
      data: { ...ITEMS_RESPONSE, items: [{ ...ITEMS[0], item_id: 'MLA1100000099', title: 'Switch TP-Link 8 bocas' }] },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Cargar 20 más' }));
    expect(publicacionesMlAPI.items).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50, limit: 20 }));
    expect(await screen.findByRole('button', { name: /Switch TP-Link 8 bocas/ })).toBeInTheDocument();
    expect(card('Router TP-Link Archer AX55')).toBeInTheDocument();
  });

  it('opens a publication full screen, and "Publicaciones" goes back to the list', async () => {
    await page();
    await userEvent.click(card('Router TP-Link Archer AX55'));
    const panel = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    expect(panel).toHaveAttribute('data-phone');
    expect(publicacionesMlAPI.detail.mock.calls.at(-1)[0]).toBe('MLA1100000001');
    await userEvent.click(within(panel).getByRole('button', { name: 'Publicaciones' }));
    expect(screen.queryByRole('complementary', { name: 'Detalle de la publicación' })).not.toBeInTheDocument();
  });

  it('puts "Ver en Mercado Libre" and the seller links ("⋯") at the top right of the full-screen panel', async () => {
    await page('/ml-publicaciones?sel=MLA1100000001&tab=resumen');
    const panel = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    await within(panel).findByText('MLA1100000001');
    expect(within(panel).getByRole('link', { name: 'Ver en Mercado Libre' })).toHaveAttribute('href', expect.stringContaining('MLA-1100000001'));
    // Not twice: the MLA line keeps none of them on a phone.
    expect(within(panel).queryByText('Ver en Mercado Libre')).not.toBeInTheDocument();
    expect(within(panel).queryByRole('link', { name: 'Ver en el panel de ML' })).not.toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('button', { name: /^Más acciones/ }));
    const menu = within(panel).getByRole('menu', { name: 'Panel del vendedor' });
    expect(within(menu).getByRole('menuitem', { name: 'Ver en el panel de ML' })).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: 'Ver promociones en ML' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(within(panel).queryByRole('menu')).not.toBeInTheDocument();
    // The menu took that Escape: the panel is still open.
    expect(screen.getByRole('complementary', { name: 'Detalle de la publicación' })).toBeInTheDocument();
  });

  it('keeps only Pausar and Resincronizar in the panel footer, the freshness above it', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: { ...DETAIL_RESPONSE, row: ITEMS[0], can_resync: true, can_change_status: true } });
    await page('/ml-publicaciones?sel=MLA1100000001&tab=resumen');
    const panel = await screen.findByRole('complementary', { name: 'Detalle de la publicación' });
    const footer = (await within(panel).findByRole('button', { name: 'Resincronizar' })).closest('footer');
    expect(within(footer).getByRole('button', { name: 'Pausar' })).toBeInTheDocument();
    expect(within(footer).queryByRole('list', { name: 'Actualización de los datos' })).not.toBeInTheDocument();
    expect(within(panel).getByRole('list', { name: 'Actualización de los datos' })).toBeInTheDocument();
  });

  it('shows "Limpiar" in the filters sheet, off without filters, and the team button with its word', async () => {
    await page();
    await userEvent.click(screen.getByRole('button', { name: /^Filtros/ }));
    const sheet = screen.getByRole('dialog', { name: 'Filtros' });
    expect(within(sheet).getByRole('button', { name: 'Limpiar' })).toBeDisabled();
    expect(within(sheet).getByRole('button', { name: 'Equipos' })).toHaveTextContent('Equipos');
  });
});
