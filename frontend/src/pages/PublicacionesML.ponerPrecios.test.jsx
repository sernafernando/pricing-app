/**
 * MODO PONER PRECIOS shell (S1–S3): toggle, hide vista, force publicacion, column preset, filter collapse.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import PublicacionesML from './PublicacionesML';
import { publicacionesMlAPI } from '../services/api';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import {
  BRAND_NODES,
  ITEMS_RESPONSE,
  KPIS_RESPONSE,
  groupsResponse,
} from '../test/visual/publicacionesMlFixtures';

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal();
  const okLocal = (data) => vi.fn(() => Promise.resolve({ data }));
  const pendingLocal = () => vi.fn(() => new Promise(() => {}));
  return {
    ...actual,
    default: {
      get: okLocal([]),
      post: okLocal({}),
      patch: okLocal({}),
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    },
    publicacionesMlAPI: {
      items: vi.fn(),
      products: vi.fn(),
      variations: vi.fn(),
      groups: vi.fn(),
      detail: vi.fn(),
      enqueue: vi.fn(),
      kpis: vi.fn(),
      productIds: vi.fn(),
      stats: vi.fn(),
    },
    productosAPI: {
      getProductoTree: okLocal({ item_id: 1, tree: {} }),
      marcas: okLocal({ marcas: [] }),
      categorias: okLocal({ categorias: [] }),
      subcategorias: okLocal({ categorias: [] }),
      pms: okLocal([]),
      detalle: okLocal({ producto: {}, pricing: {}, ultimas_compras: [] }),
      listar: okLocal({ productos: [], total: 0 }),
    },
    equiposAPI: {
      listar: okLocal([
        { id: 1, nombre: 'U', es_global: true },
        { id: 12, nombre: 'Ventas', es_global: false },
      ]),
    },
    preciosAPI: {
      calcularMarkup: okLocal({ markup: 10 }),
      setRapido: okLocal({}),
      setCuota: okLocal({}),
      setRebate: okLocal({}),
      setWebTransferencia: okLocal({}),
      setOutOfCards: okLocal({}),
      tipoCambioActual: okLocal({ venta: 1000 }),
      obtenerProducto: okLocal({ item_id: 1, codigo: 'X' }),
    },
    offsetsGananciaAPI: { vigentes: okLocal([]), grupoFiltros: okLocal([]) },
    productosPropiosAPI: { get: pendingLocal(), save: vi.fn() },
    promocionesAPI: { getPromocionesItem: pendingLocal(), refreshItemPromociones: pendingLocal() },
    registerAuthFailureHandler: vi.fn(),
  };
});

vi.mock('../components/EquiposModal', () => ({ default: () => null }));
vi.mock('../hooks/useSSEChannel', () => ({ useSSEChannel: () => {} }));

let canWritePromos = true;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => (permiso === 'promos.escribir' ? canWritePromos : true),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const modeButton = () => screen.getByRole('button', { name: 'Poner precios' });

async function page(entry = '/ml-publicaciones') {
  renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
  if (entry.includes('vista=agrupado')) await screen.findByText('EPSON');
  else await screen.findByText('MLA1100000001');
}

beforeEach(() => {
  canWritePromos = true;
  seedTiendasOficiales();
  publicacionesMlAPI.items.mockReset().mockResolvedValue({ data: ITEMS_RESPONSE });
  publicacionesMlAPI.groups.mockReset().mockResolvedValue({ data: groupsResponse('marca', BRAND_NODES) });
  publicacionesMlAPI.productIds.mockReset().mockResolvedValue({
    data: { item_ids: [4101, 4102], count: 2, sin_producto: 1 },
  });
  publicacionesMlAPI.kpis.mockReset().mockResolvedValue({ data: KPIS_RESPONSE });
  publicacionesMlAPI.stats.mockReset().mockResolvedValue({
    data: {
      stats: {
        total: 40,
        con_stock: 30,
        con_precio: 35,
        con_stock_sin_precio: 3,
        nuevos: 5,
        nuevos_sin_precio: 2,
        oferta_sin_rebate: 4,
      },
      can_see_margin: true,
    },
  });
});

afterEach(() => resetTiendasOficiales());

describe('MODO PONER PRECIOS shell', () => {
  it('hides the button without promos.escribir', async () => {
    canWritePromos = false;
    await page();
    expect(screen.queryByRole('button', { name: 'Poner precios' })).not.toBeInTheDocument();
  });

  it('activates: hides vista, forces publicacion, applies column preset, collapses filters', async () => {
    const user = userEvent.setup();
    await page('/ml-publicaciones?vista=agrupado');
    await user.click(modeButton());
    expect(modeButton()).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByLabelText('Vista')).not.toBeInTheDocument();
    await screen.findByText('MLA1100000001');
    const table = screen.getByRole('table');
    expect(within(table).getByText('Código')).toBeInTheDocument();
    // Owner, 2026-11-04: "en la vista de poner precios ... también tienen que estar los badges de Clásica, 3 cuotas".
    expect(within(table).getByRole('columnheader', { name: /^Tipo/ })).toBeInTheDocument();
    expect(within(table).getAllByText('Clásica').length).toBeGreaterThan(0);
    const toggle = screen.getByRole('button', { name: /Minimizar filtros/i });
    await user.click(toggle);
    expect(screen.getByLabelText('Filtrar por tipo').closest('[hidden]')).toBeTruthy();
  });

  it("sorted by Código, a product's publications come by listing type", async () => {
    const user = userEvent.setup();
    await page();
    await user.click(modeButton());
    await screen.findByText('MLA1100000001');
    await user.click(within(screen.getByRole('columnheader', { name: /^Código/ })).getByRole('button'));
    await waitFor(() =>
      expect(publicacionesMlAPI.items.mock.calls.at(-1)[0]).toMatchObject({ orden: 'codigo,tipo', dir: 'asc,asc' }),
    );
  });

  it('exits and restores the previous vista', async () => {
    const user = userEvent.setup();
    await page('/ml-publicaciones?vista=agrupado');
    await user.click(modeButton());
    await screen.findByText('MLA1100000001');
    await user.click(modeButton());
    await screen.findByText('EPSON');
    await waitFor(() => expect(screen.getByLabelText('Vista')).toHaveTextContent(/Agrupado/i));
  });
});
