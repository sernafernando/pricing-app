/**
 * The Auditoría de stock view (auditoria-stock S3-S8, S10, L6): its gate, what it asks `/view/stock-audit` and
 * `/view/items` for, and what it draws. Layout is the visual suite's job (`auditoriaStock.visual.test.jsx`).
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import PublicacionesML from './PublicacionesML';
import { publicacionesMlAPI } from '../services/api';
import { exportPublicacionesCsv } from '../utils/publicacionesMlExport';
import { exportAuditoriaStockExcel } from '../components/publicacionesMl/auditoria/exportStockAudit';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import { FACETS, ITEMS_RESPONSE, KPIS_RESPONSE } from '../test/visual/publicacionesMlFixtures';
import { AUDIT_NOTEBOOK_ITEMS, AUDIT_ORPHAN, stockAuditResponse } from '../test/visual/stockAuditFixtures';

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
  promocionesAPI: {
    getPromocionesItem: vi.fn(() => new Promise(() => {})),
    refreshItemPromociones: vi.fn(() => new Promise(() => {})),
    getCompetenciaCatalogo: vi.fn(() => new Promise(() => {})),
  },
  publicacionesMlAPI: { stockAudit: vi.fn(), items: vi.fn(), products: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), enqueue: vi.fn(), kpis: vi.fn(), productIds: vi.fn(), stats: vi.fn(), statusItemIds: vi.fn(), statusItemIdsChecked: vi.fn(), statusBulk: vi.fn(), paintColors: vi.fn() },
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
    misPreferencias: vi.fn(),
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

vi.mock('../components/publicacionesMl/auditoria/exportStockAudit', () => ({ exportAuditoriaStockExcel: vi.fn() }));
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


const auditCalls = () => publicacionesMlAPI.stockAudit.mock.calls.map(([params]) => params);
const table = () => screen.getByRole('table', { name: 'Auditoría de stock' });
const audit = async (entry = '/ml-publicaciones?vista=auditoria') => {
  renderWithRouter(<PublicacionesML />, { initialEntries: [entry] });
  await waitFor(() => expect(publicacionesMlAPI.stockAudit).toHaveBeenCalled());
  const shell = within(await screen.findByRole('table', { name: 'Auditoría de stock' }));
  await shell.findByText(/^(Notebook Demo|PC Demo)/, { selector: 'span' }).catch(() => null);
  return shell;
};
const headers = () => within(table()).getAllByRole('columnheader').map((th) => th.textContent);

beforeEach(() => {
  canSeeMargin = true;
  canSeeKpis = true;
  canSeePrices = true;
  canEditPrices = true;
  denied = new Set();
  localStorage.clear();
  seedTiendasOficiales([{ store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true }]);
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.items.mockImplementation((params) =>
    Promise.resolve({ data: params?.item_ids ? AUDIT_NOTEBOOK_ITEMS : { ...ITEMS_RESPONSE, facets: FACETS } }),
  );
  publicacionesMlAPI.stockAudit.mockReset();
  publicacionesMlAPI.stockAudit.mockResolvedValue({ data: stockAuditResponse() });
  publicacionesMlAPI.kpis.mockReset();
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE });
  publicacionesMlAPI.stats.mockReset();
  publicacionesMlAPI.stats.mockResolvedValue({ data: { stats: {}, can_see_margin: true } });
  publicacionesMlAPI.productIds.mockReset();
  publicacionesMlAPI.productIds.mockResolvedValue({ data: { item_ids: [], count: 0, sin_producto: 0 } });
  publicacionesMlAPI.groups.mockReset();
  publicacionesMlAPI.groups.mockResolvedValue({ data: { nodes: [], total: 0 } });
});

afterAll(resetTiendasOficiales);

describe('S8: the gate', () => {
  it('offers "Auditoría de stock" last among the views with ml_publicaciones.ver_auditoria_stock', async () => {
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones'] });
    await screen.findByText('MLA1100000001');
    const views = within(screen.getByRole('group', { name: 'Vista' })).getAllByRole('button');
    expect(views.map((b) => b.textContent)).toEqual(['Producto', 'Publicaciones', 'Precios', 'Agrupado', 'Auditoría de stock']);
    expect(publicacionesMlAPI.stockAudit).not.toHaveBeenCalled();
  });

  it('without it: no option, and a link to the view opens the publication list without asking the audit', async () => {
    denied = new Set(['ml_publicaciones.ver_auditoria_stock']);
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=auditoria'] });
    await screen.findByText('MLA1100000001');
    expect(screen.queryByRole('button', { name: 'Auditoría de stock' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Publicaciones', pressed: true })).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Auditoría de stock' })).not.toBeInTheDocument();
    expect(publicacionesMlAPI.stockAudit).not.toHaveBeenCalled();
  });

  it('the other views still render with it', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: { rows: [], total: 0, limit: 50, offset: 0 } });
    renderWithRouter(<PublicacionesML />, { initialEntries: ['/ml-publicaciones?vista=precios'] });
    expect(await screen.findByText('MLA1100000001')).toBeInTheDocument();
    expect(publicacionesMlAPI.stockAudit).not.toHaveBeenCalled();
  });
});

describe('S3-S7: the view', () => {
  it('asks the audit for the page by Valor total, biggest first, with the list filters', async () => {
    await audit('/ml-publicaciones?vista=auditoria&q=notebook&promo_aplicada=con');
    expect(auditCalls().at(-1)).toEqual({ q: 'notebook', promo_aplicada: 'con', orden: 'valor_total', dir: 'desc', limit: 50, offset: 0 });
  });

  it('draws one row per base product, its rate line and its KPIs, not the publication KPIs', async () => {
    const t = await audit();
    expect(t.getByText('Notebook Demo 14 i5 8GB 512GB')).toBeInTheDocument();
    expect(t.getByText('Cartucho Demo 01 negro')).toBeInTheDocument();
    expect(t.getByText('Con stock sin publicación activa')).toBeInTheDocument();
    expect(screen.getByText('$ 1.450,00')).toBeInTheDocument();
    expect(screen.getByText('Valor a costo sin IVA')).toBeInTheDocument();
    const kpis = within(screen.getByRole('region', { name: 'Indicadores de la auditoría de stock' }));
    expect(kpis.getByText('USD 24.247')).toBeInTheDocument();
    expect(kpis.getByText('Con promo aplicada')).toBeInTheDocument();
    expect(screen.getByText(/de 3 productos/)).toBeInTheDocument();
    expect(publicacionesMlAPI.kpis).not.toHaveBeenCalled();
  });

  it('notes where the base row Full and sales come from: "de variantes", "del pack x2"', async () => {
    const t = await audit();
    expect(t.getByText('12 de variantes')).toBeInTheDocument();
    expect(t.getByText('50 del pack x2')).toBeInTheDocument();
    expect(t.getByText('36 del pack x2')).toBeInTheDocument();
  });

  it('groups the columns Stock / Valor stock / Ventas / Markup / Resultado, Tipo and Estado included', async () => {
    await audit();
    const all = headers();
    for (const name of ['Stock (unidades)', 'Valor stock (USD · ARS)', 'Ventas (unidades)', 'Markup con sell in / sell out', 'Resultado', 'Tipo', 'Estado', 'Actual', 'Real 30D', 'Total Gauss 30D']) {
      expect(all.some((text) => text.includes(name))).toBe(true);
    }
  });

  it('without ml_metricas.ver_ganancia: no markup nor Total Gauss column', async () => {
    canSeeMargin = false;
    await audit();
    const all = headers();
    expect(all.some((text) => text.includes('Markup'))).toBe(false);
    expect(all.some((text) => text.includes('Total Gauss'))).toBe(false);
    expect(all.some((text) => text.includes('Ventas'))).toBe(true);
  });

  it('opening a product asks its publications from /items with its params and shows them under it', async () => {
    const user = userEvent.setup();
    const t = await audit();
    await user.click(t.getByRole('button', { name: 'Abrir Notebook Demo 14 i5 8GB 512GB' }));
    expect(await t.findByText('MLA1900000001')).toBeInTheDocument();
    expect(publicacionesMlAPI.items.mock.calls.at(-1)[0]).toMatchObject({ item_ids: '9001', limit: 100, offset: 0 });
    expect(t.getByText('Notebook Demo 14 i5 16GB 512GB')).toBeInTheDocument();
    expect(t.getByText('Promo aplicada')).toBeInTheDocument();
  });

  it('a sortable header sorts the audit by its key', async () => {
    const user = userEvent.setup();
    await audit();
    // Stock's ERP is the first "ERP" header (Valor stock's is the second).
    await user.click(within(table()).getAllByRole('button', { name: /^ERP/ })[0]);
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ orden: 'unidades_erp', dir: 'desc' }));
  });

  it('a sales sort without ml_metricas.ver falls back to Valor total (no 403)', async () => {
    canSeeKpis = false;
    await audit('/ml-publicaciones?vista=auditoria&orden=unidades_30d');
    expect(auditCalls().at(-1)).toMatchObject({ orden: 'valor_total', dir: 'desc' });
  });
});

describe('L6: hideable columns and KPI cards, remembered', () => {
  it('hiding a column in the picker drops it and remembers it', async () => {
    const user = userEvent.setup();
    await audit();
    await user.click(screen.getByRole('button', { name: /Columnas/ }));
    await user.click(screen.getByRole('checkbox', { name: 'Tendencia de ventas' }));
    await waitFor(() => expect(headers().filter((text) => text === 'Tendencia')).toHaveLength(1));
    expect(localStorage.getItem('publicaciones-ml.auditoria.columnas-ocultas')).toContain('units_trend');
  });

  it('hiding a KPI card drops it and remembers it', async () => {
    const user = userEvent.setup();
    await audit();
    const kpis = () => within(screen.getByRole('region', { name: 'Indicadores de la auditoría de stock' }));
    expect(kpis().getByText('Valor stock ERP')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Indicadores/ }));
    await user.click(screen.getByRole('checkbox', { name: 'Valor stock ERP' }));
    await waitFor(() => expect(kpis().queryByText('Valor stock ERP')).not.toBeInTheDocument());
    expect(localStorage.getItem('publicaciones-ml.auditoria.kpis-ocultos')).toContain('valor_erp');
  });
});

describe('L9: stock without cost', () => {
  const noCost = {
    ...AUDIT_ORPHAN,
    key: 'p9301',
    product_item_id: 9301,
    descripcion: 'Mochila Demo sin costo',
    costo: null,
    erp: { unidades: 6, usd: null, ars: null },
    full: { unidades: 0, usd: null, ars: null },
    total: { unidades: 6, usd: null, ars: null },
    sin_costo: true,
  };
  const withNoCost = (count) => {
    const body = stockAuditResponse([noCost]);
    return { ...body, kpis: { ...body.kpis, productos_sin_costo: count } };
  };
  const kpis = () => within(screen.getByRole('region', { name: 'Indicadores de la auditoría de stock' }));

  it('its value cells read "—", never 0', async () => {
    publicacionesMlAPI.stockAudit.mockResolvedValue({ data: withNoCost(1) });
    const t = await audit();
    const row = t.getByText('Mochila Demo sin costo').closest('tr');
    const cells = (key) => row.querySelector(`td[data-column="${key}"]`).textContent;
    for (const key of ['valor_erp', 'valor_full', 'valor_total']) expect(cells(key)).toBe('—');
    expect(row.textContent).not.toMatch(/\$ 0\b/);
  });

  it.each([
    [1, '1 producto sin costo'],
    [3, '3 productos sin costo'],
  ])('with %i the value KPIs say "%s"', async (count, note) => {
    publicacionesMlAPI.stockAudit.mockResolvedValue({ data: withNoCost(count) });
    await audit();
    expect(kpis().getByText(new RegExp(`^${note}`))).toBeInTheDocument();
  });

  it('with none there is no note', async () => {
    await audit();
    expect(kpis().queryByText(/sin costo/)).not.toBeInTheDocument();
  });

  it('a value the BNA rate cannot reach reads "—" in its KPI', async () => {
    const body = stockAuditResponse();
    publicacionesMlAPI.stockAudit.mockResolvedValue({
      data: { ...body, tipo_cambio: null, kpis: { ...body.kpis, total: { unidades: 184, usd: 24246.9, ars: null } } },
    });
    await audit();
    const total = kpis().getByText('Valor stock total').closest('div');
    expect(within(total).getByText('—')).toBeInTheDocument();
  });
});

describe('L8: the promo KPIs without the promotions database', () => {
  it('read "—", never 0', async () => {
    const body = stockAuditResponse();
    publicacionesMlAPI.stockAudit.mockResolvedValue({
      data: { ...body, kpis: { ...body.kpis, productos_con_promo_aplicada: null, productos_sin_promo_aplicada: null } },
    });
    await audit();
    const card = within(screen.getByRole('region', { name: 'Indicadores de la auditoría de stock' }))
      .getByText('Productos con stock')
      .closest('div');
    expect(within(card).getAllByText('—')).toHaveLength(2);
  });
});

describe('L7: Exportar a Excel', () => {
  beforeEach(() => {
    exportAuditoriaStockExcel.mockReset();
    exportAuditoriaStockExcel.mockResolvedValue(undefined);
    exportPublicacionesCsv.mockReset();
  });

  it('downloads every row of the audit with its filters and sort, not the page', async () => {
    const user = userEvent.setup();
    await audit('/ml-publicaciones?vista=auditoria&q=notebook&orden=unidades_erp&pagina=2');
    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await waitFor(() => expect(exportAuditoriaStockExcel).toHaveBeenCalledTimes(1));
    expect(exportAuditoriaStockExcel).toHaveBeenCalledWith({ q: 'notebook', orden: 'unidades_erp', dir: 'desc' });
    expect(exportPublicacionesCsv).not.toHaveBeenCalled();
  });

  it("shows the backend's refusal", async () => {
    const user = userEvent.setup();
    exportAuditoriaStockExcel.mockRejectedValue(new Error('La consulta tardó demasiado: acotá los filtros o reintentá.'));
    await audit();
    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    expect(await screen.findByText('La consulta tardó demasiado: acotá los filtros o reintentá.')).toBeInTheDocument();
  });

  it('keeps Acciones masivas and Pausar / activar hidden in this view', async () => {
    await audit();
    expect(screen.queryByRole('button', { name: /Acciones masivas/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Pausar \/ activar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Exportar a Sheets/ })).not.toBeInTheDocument();
  });
});
