/**
 * The Auditoría de stock view (auditoria-stock S3-S8, S10, L6): its gate, what it asks `/view/stock-audit` and
 * `/view/items` for, and what it draws. Layout is the visual suite's job (`auditoriaStock.visual.test.jsx`).
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import PublicacionesML from './PublicacionesML';
import { publicacionesMlAPI } from '../services/api';
import { exportPublicacionesCsv } from '../utils/publicacionesMlExport';
import { exportAuditoriaStockExcel } from '../components/publicacionesMl/auditoria/exportStockAudit';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import { FACETS, ITEMS_RESPONSE, KPIS_RESPONSE } from '../test/visual/publicacionesMlFixtures';
import { AUDIT_NOTEBOOK_ITEMS, AUDIT_ORPHAN, stockAuditLevelResponse, stockAuditResponse } from '../test/visual/stockAuditFixtures';
import { mlPublicationsPresetsAPI } from '../services/mlPublicationsPresets';

// The columns are the user's saved layout of the view (pubml-columnas-presets S2): the server is mocked here.
vi.mock('../services/mlPublicationsPresets', () => ({
  mlPublicationsPresetsAPI: {
    getLayout: vi.fn(),
    saveLayout: vi.fn(),
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

// dnd-kit's gestures do not run in jsdom: a picker drag ends through its DndContext's own `onDragEnd`, by `id`.
const dragEnd = vi.hoisted(() => ({}));
vi.mock('@dnd-kit/core', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    DndContext: ({ id, onDragEnd, children }) => {
      dragEnd[id] = onDragEnd;
      return children;
    },
  };
});

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
// The product-level tests ask `nivel=producto`; the view opens on Marca (auditoria-stock-niveles S1).
const audit = async (entry = '/ml-publicaciones?vista=auditoria&nivel=producto') => {
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
  Object.values(mlPublicationsPresetsAPI).forEach((fn) => fn.mockReset());
  mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: null, preset_activo_id: null });
  mlPublicationsPresetsAPI.saveLayout.mockImplementation((vista, body) => Promise.resolve(body));
  mlPublicationsPresetsAPI.list.mockResolvedValue([]);
});

const savedAudit = () => mlPublicationsPresetsAPI.saveLayout.mock.calls.filter(([vista]) => vista === 'auditoria').at(-1)?.[1];

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
    await audit('/ml-publicaciones?vista=auditoria&nivel=producto&q=notebook&promo_aplicada=con');
    expect(auditCalls().at(-1)).toEqual({ q: 'notebook', promo_aplicada: 'con', nivel: 'producto', orden: 'valor_total', dir: 'desc', limit: 50, offset: 0 });
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

  it('notes where the base row Full stock comes from: "de variantes", "del pack x2" (never under the sales)', async () => {
    const t = await audit();
    expect(t.getByText('12 de variantes')).toBeInTheDocument();
    expect(t.getByText('50 del pack x2')).toBeInTheDocument();
    expect(t.queryByText('36 del pack x2')).not.toBeInTheDocument(); // the cartridge's 30D sales from its pack
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
    await audit('/ml-publicaciones?vista=auditoria&nivel=producto&orden=unidades_30d');
    expect(auditCalls().at(-1)).toMatchObject({ orden: 'valor_total', dir: 'desc' });
  });
});

describe('L6: hideable columns and KPI cards, remembered', () => {
  it('hiding a column in the picker drops it and remembers it, on the server (pubml-columnas-presets S2)', async () => {
    const user = userEvent.setup();
    await audit();
    await user.click(screen.getByRole('button', { name: /Columnas/ }));
    await user.click(screen.getByRole('checkbox', { name: 'Tendencia de ventas' }));
    await waitFor(() => expect(headers().filter((text) => text === 'Tendencia')).toHaveLength(1));
    await waitFor(() => expect(savedAudit()?.columns.visibility).toMatchObject({ units_trend: false, descripcion: true }), { timeout: 2000 });
  });

  it('opens with the layout saved for the audit, and its groups reorder as a block (pubml-columnas-presets S1)', async () => {
    mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: { visibility: { tipo: false }, order: [] }, preset_activo_id: null });
    await audit();
    expect(mlPublicationsPresetsAPI.getLayout).toHaveBeenCalledWith('auditoria');
    await waitFor(() => expect(headers()).not.toContain('Tipo'));
    await userEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    act(() => dragEnd['column-blocks']({ active: { id: 'group:Resultado' }, over: { id: 'col:estado' } }));
    await waitFor(() => {
      const keys = [...table().querySelectorAll('th[data-column]')].map((th) => th.getAttribute('data-column'));
      expect(keys.indexOf('facturado_30d')).toBeLessThan(keys.indexOf('unidades_erp'));
    });
    await waitFor(() => expect(savedAudit()?.columns.order.slice(0, 4)).toEqual(['descripcion', 'tipo', 'facturado_30d', 'total_gauss_30d']), {
      timeout: 2000,
    });
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

describe('promos-fila S2: the Promos aplicadas column', () => {
  const rowOf = (name) => within(table()).getByText(name, { selector: 'span' }).closest('tr');

  it('shows a green tag with the publications with an applied promo and a red one with those without', async () => {
    await audit();
    expect(headers().some((text) => text.includes('Promos'))).toBe(true);
    const notebook = within(rowOf('Notebook Demo 14 i5 8GB 512GB'));
    expect(notebook.getByLabelText('2 publicaciones con promo aplicada')).toHaveTextContent('2');
    expect(notebook.getByLabelText('3 publicaciones sin promo aplicada')).toHaveTextContent('3');
  });

  it('a side with no publication is not drawn, and a product without publications shows nothing', async () => {
    await audit();
    const cartridge = within(rowOf('Cartucho Demo 01 negro'));
    expect(cartridge.getByLabelText('2 publicaciones sin promo aplicada')).toBeInTheDocument();
    expect(cartridge.queryByLabelText(/con promo aplicada/)).not.toBeInTheDocument();
    expect(within(rowOf(AUDIT_ORPHAN.descripcion)).queryByLabelText(/promo aplicada/)).not.toBeInTheDocument();
  });

  it('a variant counts its own publications', async () => {
    const user = userEvent.setup();
    const t = await audit();
    await user.click(t.getByRole('button', { name: 'Abrir Notebook Demo 14 i5 8GB 512GB' }));
    const variant = within(rowOf('Notebook Demo 14 i5 16GB 512GB'));
    expect(variant.getByLabelText('1 publicación con promo aplicada')).toBeInTheDocument();
    expect(variant.getByLabelText('2 publicaciones sin promo aplicada')).toBeInTheDocument();
  });

  it('without the promotions database it reads "—", never 0', async () => {
    const body = stockAuditResponse();
    publicacionesMlAPI.stockAudit.mockResolvedValue({
      data: { ...body, rows: body.rows.map((row) => ({ ...row, promo_counts: null })) },
    });
    await audit();
    expect(within(rowOf('Notebook Demo 14 i5 8GB 512GB')).getByTitle('Promociones no disponibles')).toHaveTextContent('—');
    expect(within(table()).queryByLabelText(/promo aplicada/)).not.toBeInTheDocument();
  });

  it('its header sorts the audit by the publications with an applied promo, most first', async () => {
    const user = userEvent.setup();
    await audit();
    await user.click(within(table()).getByRole('button', { name: /^Promos/ }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ orden: 'promos_aplicadas', dir: 'desc' }));
  });

  it('can be hidden in the picker, and it is remembered', async () => {
    const user = userEvent.setup();
    await audit();
    await user.click(screen.getByRole('button', { name: /Columnas/ }));
    await user.click(screen.getByRole('checkbox', { name: 'Promos aplicadas' }));
    await waitFor(() => expect(headers().some((text) => text.includes('Promos'))).toBe(false));
    await waitFor(() => expect(savedAudit()?.columns.visibility).toMatchObject({ promos_aplicadas: false }), { timeout: 2000 });
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
    await audit('/ml-publicaciones?vista=auditoria&nivel=producto&q=notebook&orden=unidades_erp&pagina=2');
    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await waitFor(() => expect(exportAuditoriaStockExcel).toHaveBeenCalledTimes(1));
    expect(exportAuditoriaStockExcel).toHaveBeenCalledWith({ q: 'notebook', nivel: 'producto', orden: 'unidades_erp', dir: 'desc' });
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

describe('rotacion S2: the Rotación columns', () => {
  const rowOf = (name) => within(table()).getByText(name, { selector: 'span' }).closest('tr');

  it('groups Última venta, Ageing, Cobertura and Rotación under "Rotación"', async () => {
    await audit();
    const all = headers();
    for (const name of ['Rotación', 'Última venta', 'Ageing', 'Cobertura', 'Veces']) {
      expect(all.some((text) => text.includes(name))).toBe(true);
    }
  });

  it("shows each product's last sale, its ageing, its days of coverage and its rotation", async () => {
    await audit();
    const notebook = within(rowOf('Notebook Demo 14 i5 8GB 512GB'));
    expect(notebook.getByText(/^16\/11/)).toBeInTheDocument();
    expect(notebook.getByText('2 d')).toBeInTheDocument();
    // its own numbers: 50 in stock, 24 sold in 30 days, 50 on average -> 62,5 days and 0,48 times
    expect(notebook.getByLabelText('Días de cobertura')).toHaveTextContent('63 d');
    expect(notebook.getByLabelText('Rotación (veces)')).toHaveTextContent('0,48×/30d');
  });

  it("every figure of the group says it is the whole product's, without filters (L2)", async () => {
    await audit();
    const notebook = within(rowOf('Notebook Demo 14 i5 8GB 512GB'));
    const whole = /del producto completo, sin filtros/;
    expect(notebook.getByText(/^16\/11/).closest('[title]')).toHaveAttribute('title', expect.stringMatching(whole));
    expect(notebook.getByText('2 d')).toHaveAttribute('title', expect.stringMatching(whole));
    expect(notebook.getByLabelText('Días de cobertura')).toHaveAttribute('title', expect.stringMatching(whole));
    expect(notebook.getByLabelText('Rotación (veces)')).toHaveAttribute('title', expect.stringMatching(whole));
  });

  it('stock without sales lasts forever: ∞, and no last sale nor ageing', async () => {
    await audit();
    const pc = within(rowOf(AUDIT_ORPHAN.descripcion));
    const coverage = pc.getByLabelText('Días de cobertura');
    expect(coverage).toHaveTextContent('∞');
    expect(coverage).toHaveAttribute('title', '4 en stock y ninguna venta en 30 días: no se agota al ritmo actual, del producto completo, sin filtros');
    expect(pc.getByLabelText('Rotación (veces)')).toHaveTextContent('0,00×/30d');
  });

  it("the rotation says over how many days its average stock is, and marks the current stock's stand-in", async () => {
    const body = stockAuditResponse();
    const [notebook, ...rest] = body.rows;
    const approximate = { ...notebook, ventas: { ...notebook.ventas, stock_promedio_dias: 0, stock_promedio: 50 } };
    publicacionesMlAPI.stockAudit.mockResolvedValue({ data: { ...body, rows: [approximate, ...rest] } });
    await audit();
    const cartridge = within(rowOf('Cartucho Demo 01 negro')).getByLabelText('Rotación (veces)');
    expect(cartridge).toHaveAttribute(
      'title',
      'Veces que se vendió el stock en 30 días: 43 vendidas ÷ 131,6 de stock promedio (12 días) = 0,33, del producto completo, sin filtros',
    );
    const first = within(rowOf('Notebook Demo 14 i5 8GB 512GB')).getByLabelText('Rotación (veces)');
    expect(first).toHaveTextContent('≈ 0,48×/30d');
    expect(first).toHaveAttribute(
      'title',
      'Veces que se vendió el stock en 30 días: 24 vendidas ÷ 50 de stock actual (aproximado: todavía no hay fotos diarias del stock) = 0,48, del producto completo, sin filtros',
    );
  });

  it('a variant shows its own figures', async () => {
    const user = userEvent.setup();
    const t = await audit();
    await user.click(t.getByRole('button', { name: 'Abrir Notebook Demo 14 i5 8GB 512GB' }));
    const variant = within(rowOf('Notebook Demo 14 i5 16GB 512GB'));
    expect(variant.getByLabelText('Días de cobertura')).toHaveTextContent('45');
    expect(variant.getByLabelText('Rotación (veces)')).toHaveTextContent('0,67');
  });

  it('a publication shows its own last sale and ageing', async () => {
    const user = userEvent.setup();
    const t = await audit();
    await user.click(t.getByRole('button', { name: 'Abrir Notebook Demo 14 i5 8GB 512GB' }));
    const publication = within((await t.findByText('MLA1900000001')).closest('tr'));
    expect(publication.getByText(/^14\/11/)).toBeInTheDocument();
  });

  it.each([
    ['Cobertura', 'cobertura', 'desc'],
    ['Veces', 'rotacion', 'asc'],
    ['Ageing', 'ageing', 'desc'],
    ['Última venta', 'ultima_venta', 'asc'],
  ])('the %s header sorts the audit by %s, the worst first', async (header, orden, dir) => {
    const user = userEvent.setup();
    await audit();
    await user.click(within(table()).getByRole('button', { name: new RegExp(`^${header}`) }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ orden, dir }));
  });

  it('without ml_metricas.ver there is no Rotación column', async () => {
    canSeeKpis = false;
    await audit();
    expect(headers().some((text) => /Rotación|Cobertura|Ageing|Última venta/.test(text))).toBe(false);
  });

  it('each column can be hidden in the picker, and it is remembered', async () => {
    const user = userEvent.setup();
    await audit();
    await user.click(screen.getByRole('button', { name: /Columnas/ }));
    await user.click(screen.getByRole('checkbox', { name: 'Días de cobertura' }));
    await waitFor(() => expect(headers().some((text) => text.includes('Cobertura'))).toBe(false));
    await waitFor(() => expect(savedAudit()?.columns.visibility).toMatchObject({ cobertura: false }), { timeout: 2000 });
    for (const name of ['Última venta', 'Ageing', 'Rotación (veces)']) {
      expect(screen.getByRole('checkbox', { name })).toBeInTheDocument();
    }
  });
});

// auditoria-ventas-erp-full L2 (owner: "no comprendo que representa cada uno"): Cobertura and Rotación carry their unit,
// and the header and every cell explain the formula with the row's own numbers.
describe('auditoria-ventas-erp-full L2: Cobertura and Rotación explained', () => {
  const rowOf = (name) => within(table()).getByText(name, { selector: 'span' }).closest('tr');
  const owners = { stock_actual: 1341, vendidas_30d: 43, dias_cobertura: 935.6, rotacion: 0.03, stock_promedio: 1341, stock_promedio_dias: 12 };
  const withVentas = (patch) => {
    const body = stockAuditResponse();
    const [first, ...rest] = body.rows;
    publicacionesMlAPI.stockAudit.mockResolvedValue({ data: { ...body, rows: [{ ...first, ventas: { ...first.ventas, ...patch } }, ...rest] } });
  };

  it('Cobertura reads "936 d" and its tooltip is the formula with the row\'s numbers', async () => {
    withVentas(owners);
    await audit();
    const el = within(rowOf('Notebook Demo 14 i5 8GB 512GB')).getByLabelText('Días de cobertura');
    expect(el).toHaveTextContent('936 d');
    expect(el.getAttribute('title')).toBe(
      'Días que alcanza el stock al ritmo de venta de 30 días: 1.341 ÷ (43 ÷ 30) = 936 días (≈ 31 meses), del producto completo, sin filtros',
    );
  });

  it('Rotación reads "0,03×/30d" and its tooltip is the formula with the row\'s numbers', async () => {
    withVentas(owners);
    await audit();
    const el = within(rowOf('Notebook Demo 14 i5 8GB 512GB')).getByLabelText('Rotación (veces)');
    expect(el).toHaveTextContent('0,03×/30d');
    expect(el.getAttribute('title')).toBe(
      'Veces que se vendió el stock en 30 días: 43 vendidas ÷ 1.341 de stock promedio (12 días) = 0,03, del producto completo, sin filtros',
    );
  });

  it('with stock and no sale, Cobertura says why it is ∞ with the row\'s stock', async () => {
    withVentas({ ...owners, vendidas_30d: 0, dias_cobertura: null, cobertura_infinita: true });
    await audit();
    const el = within(rowOf('Notebook Demo 14 i5 8GB 512GB')).getByLabelText('Días de cobertura');
    expect(el.getAttribute('title')).toBe('1.341 en stock y ninguna venta en 30 días: no se agota al ritmo actual, del producto completo, sin filtros');
  });

  it('the headers explain what each one is', async () => {
    await audit();
    const th = (name) => within(table()).getAllByRole('columnheader').find((h) => h.textContent.includes(name));
    expect(within(th('Cobertura')).getByTitle(/^Días que alcanza el stock al ritmo de venta de los últimos 30 días: stock ÷ \(vendidas en 30 días ÷ 30\)/)).toBeInTheDocument();
    expect(within(th('Veces')).getByTitle(/^Veces que se vendió el stock en 30 días: vendidas en 30 días ÷ stock promedio/)).toBeInTheDocument();
  });

  it('a brand row explains its own sums the same way', async () => {
    publicacionesMlAPI.stockAudit.mockImplementation((params) => Promise.resolve({ data: stockAuditLevelResponse(params) }));
    const t = await audit('/ml-publicaciones?vista=auditoria');
    await t.findByText('DEMO', { selector: 'span' });
    const brand = within(rowOf('DEMO'));
    expect(brand.getByLabelText('Días de cobertura')).toHaveTextContent(/^\d[\d.]* d$/);
    expect(brand.getByLabelText('Días de cobertura').getAttribute('title')).toMatch(/^Días que alcanza el stock al ritmo de venta de 30 días: [\d.]+ ÷ \([\d.]+ ÷ 30\) = /);
    expect(brand.getByLabelText('Rotación (veces)').getAttribute('title')).toMatch(/^Veces que se vendió el stock en 30 días: [\d.]+ vendidas ÷ /);
  });
});

// The verifier's probes (rotacion S1/S2/L1): a never-sold product's ageing, "—" for a division by zero, the singular day,
// the permission gate on the picker, and the sort in the URL.
describe('rotacion S2: edge cases', () => {
  const rowOf = (name) => within(table()).getByText(name, { selector: 'span' }).closest('tr');
  const withVentas = (patch) => {
    const body = stockAuditResponse();
    const [first, ...rest] = body.rows;
    publicacionesMlAPI.stockAudit.mockResolvedValue({ data: { ...body, rows: [{ ...first, ventas: { ...first.ventas, ...patch } }, ...rest] } });
  };

  it('a never-sold product shows its ageing from the publication date and "—" as last sale', async () => {
    withVentas({ ultima_venta: null, ultima_venta_dias: null, ageing_dias: 70 });
    await audit();
    const row = within(rowOf('Notebook Demo 14 i5 8GB 512GB'));
    expect(row.getByText('70 d')).toBeInTheDocument();
  });

  it('no stock and no sale: coverage reads "—" (never 0, never ∞)', async () => {
    withVentas({ dias_cobertura: null, cobertura_infinita: false });
    await audit();
    const row = rowOf('Notebook Demo 14 i5 8GB 512GB');
    expect(within(row).queryByLabelText('Días de cobertura')).not.toBeInTheDocument();
    expect(row.textContent).not.toContain('∞');
  });

  it('a null rotation (average stock 0) reads "—", not 0,00', async () => {
    withVentas({ rotacion: null });
    await audit();
    const row = rowOf('Notebook Demo 14 i5 8GB 512GB');
    expect(within(row).queryByLabelText('Rotación (veces)')).not.toBeInTheDocument();
  });

  it('a single photographed day says "día" in the singular', async () => {
    withVentas({ stock_promedio_dias: 1 });
    await audit();
    const el = within(rowOf('Notebook Demo 14 i5 8GB 512GB')).getByLabelText('Rotación (veces)');
    expect(el.getAttribute('title')).toMatch(/stock promedio \(1 día\)/);
  });

  it('with sales but without margin the four columns are in the picker and the table', async () => {
    canSeeMargin = false;
    await audit();
    const h = headers().join('|');
    for (const name of ['Última venta', 'Ageing', 'Cobertura', 'Veces']) expect(h).toContain(name);
  });

  it('without ml_metricas.ver the picker does not offer the Rotación columns', async () => {
    canSeeKpis = false;
    const user = userEvent.setup();
    await audit();
    await user.click(screen.getByRole('button', { name: /Columnas/ }));
    for (const name of ['Última venta', 'Ageing', 'Días de cobertura', 'Rotación (veces)']) {
      expect(screen.queryByRole('checkbox', { name })).not.toBeInTheDocument();
    }
  });

  it('a ?orden=cobertura URL without ml_metricas.ver falls back to the default sort', async () => {
    canSeeKpis = false;
    await audit('/ml-publicaciones?vista=auditoria&nivel=producto&orden=cobertura');
    expect(auditCalls().at(-1).orden).toBe('valor_total');
  });

  it('a ?orden=cobertura URL with ml_metricas.ver is sent as is', async () => {
    await audit('/ml-publicaciones?vista=auditoria&nivel=producto&orden=cobertura&dir=desc');
    expect(auditCalls().at(-1)).toMatchObject({ orden: 'cobertura', dir: 'desc' });
  });
});

describe('auditoria-stock-niveles S1: Marca > Categoría levels', () => {
  const rowOf = (name) => within(table()).getByText(name, { selector: 'span' }).closest('tr');
  const levels = () => within(screen.getByRole('group', { name: 'Ver por' }));
  const openAt = (query = '') => audit(`/ml-publicaciones?vista=auditoria${query}`);
  const urlOf = (keys) => `&abiertos=${encodeURIComponent(JSON.stringify(keys))}`;
  beforeEach(() => {
    publicacionesMlAPI.stockAudit.mockImplementation((params) => Promise.resolve({ data: stockAuditLevelResponse(params) }));
  });

  it('opens on the Marca level: the request carries nivel=marca and the brands are the rows', async () => {
    const t = await openAt();
    expect(auditCalls()[0]).toMatchObject({ nivel: 'marca', orden: 'valor_total', dir: 'desc', limit: 50, offset: 0 });
    expect(auditCalls()[0]).not.toHaveProperty('grupo_marca');
    expect(await t.findByText('DEMO', { selector: 'span' })).toBeInTheDocument();
    expect(t.getByText('Sin marca', { selector: 'span' })).toBeInTheDocument();
    expect(levels().getByRole('button', { name: 'Marca', pressed: true })).toBeInTheDocument();
    expect(screen.getByText(/de 2 marcas/)).toBeInTheDocument();
  });

  it('the selector switches the top level', async () => {
    const user = userEvent.setup();
    const t = await openAt();
    await user.click(levels().getByRole('button', { name: 'Categoría' }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ nivel: 'categoria' }));
    expect(await t.findByText('NOTEBOOKS', { selector: 'span' })).toBeInTheDocument();
    await user.click(levels().getByRole('button', { name: 'Producto' }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ nivel: 'producto' }));
    expect(await t.findByText('Notebook Demo 14 i5 8GB 512GB')).toBeInTheDocument();
  });

  it('drilling into a brand asks its categories with grupo_marca, and the breadcrumb goes back', async () => {
    const user = userEvent.setup();
    const t = await openAt();
    await user.click(await t.findByRole('button', { name: 'Ver categorías de DEMO' }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ nivel: 'categoria', grupo_marca: 'DEMO' }));
    expect(levels().getByRole('button', { name: 'Categoría', pressed: true })).toBeInTheDocument();
    const crumbs = within(screen.getByRole('navigation', { name: 'Nivel de la auditoría' }));
    // the way back names the brand as its row does, not by its key
    expect(await crumbs.findByText('Demo')).toBeInTheDocument();
    // a category row of the drilled level drills into its products with both keys
    await user.click(await t.findByRole('button', { name: 'Ver productos de INSUMOS' }));
    await waitFor(() =>
      expect(auditCalls().at(-1)).toMatchObject({ nivel: 'producto', grupo_marca: 'DEMO', grupo_categoria: 'INSUMOS' }),
    );
    const path = within(screen.getByRole('navigation', { name: 'Nivel de la auditoría' }));
    expect(await path.findByRole('button', { name: 'Demo' })).toBeInTheDocument();
    expect(await path.findByText('Insumos')).toBeInTheDocument();
    await user.click(within(screen.getByRole('navigation', { name: 'Nivel de la auditoría' })).getByRole('button', { name: 'Todas las marcas' }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ nivel: 'marca' }));
    expect(auditCalls().at(-1)).not.toHaveProperty('grupo_marca');
    expect(auditCalls().at(-1)).not.toHaveProperty('grupo_categoria');
  });

  it('clicking a brand row drills down like its button', async () => {
    const user = userEvent.setup();
    const t = await openAt();
    await user.click(await t.findByText('DEMO', { selector: 'span' }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ nivel: 'categoria', grupo_marca: 'DEMO' }));
  });

  it('a brand opens into its categories without a request; a category asks its products with its grupo', async () => {
    const user = userEvent.setup();
    const t = await openAt();
    await user.click(await t.findByRole('button', { name: 'Abrir DEMO' }));
    expect(t.getByText('NOTEBOOKS', { selector: 'span' })).toBeInTheDocument();
    expect(t.getByText('INSUMOS', { selector: 'span' })).toBeInTheDocument();
    expect(auditCalls()).toHaveLength(1);
    await user.click(t.getByRole('button', { name: 'Abrir INSUMOS' }));
    expect(await t.findByText('Cartucho Demo 01 negro')).toBeInTheDocument();
    expect(auditCalls().at(-1)).toMatchObject({
      nivel: 'producto',
      grupo_marca: 'DEMO',
      grupo_categoria: 'INSUMOS',
      orden: 'valor_total',
      dir: 'desc',
      limit: 100,
      offset: 0,
    });
    // a product inside it opens into its publications and variants as everywhere
    await user.click(t.getByRole('button', { name: 'Abrir Cartucho Demo 01 negro' }));
    expect(await t.findByText('Cartucho Demo 01 negro x2')).toBeInTheDocument();
    expect(publicacionesMlAPI.items.mock.calls.at(-1)[0]).toMatchObject({ item_ids: '9101', desglose_envio: true });
  });

  it('the opened rows survive a reload (URL)', async () => {
    const t = await openAt(urlOf(['g:marca:DEMO', 'g:marca:DEMO|categoria:INSUMOS']));
    expect(await t.findByText('Cartucho Demo 01 negro')).toBeInTheDocument();
    expect(t.getByText('NOTEBOOKS', { selector: 'span' })).toBeInTheDocument();
    expect(auditCalls().some((params) => params.grupo_categoria === 'INSUMOS')).toBe(true);
  });

  it('the level and the drill survive a reload (URL)', async () => {
    const t = await openAt('&nivel=producto&grupo_marca=DEMO&grupo_categoria=NOTEBOOKS');
    expect(auditCalls()[0]).toMatchObject({ nivel: 'producto', grupo_marca: 'DEMO', grupo_categoria: 'NOTEBOOKS' });
    expect(await t.findByText('Notebook Demo 14 i5 8GB 512GB')).toBeInTheDocument();
    expect(levels().getByRole('button', { name: 'Producto', pressed: true })).toBeInTheDocument();
  });

  it('a header sorts the brands, and the products a category opens keep that sort', async () => {
    const user = userEvent.setup();
    const t = await openAt('&orden=unidades_erp&dir=asc');
    expect(auditCalls()[0]).toMatchObject({ nivel: 'marca', orden: 'unidades_erp', dir: 'asc' });
    await user.click(within(table()).getAllByRole('button', { name: /^ERP/ })[1]);
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ nivel: 'marca', orden: 'valor_erp' }));
    await user.click(await t.findByRole('button', { name: 'Abrir DEMO' }));
    await user.click(t.getByRole('button', { name: 'Abrir NOTEBOOKS' }));
    await waitFor(() => expect(auditCalls().at(-1)).toMatchObject({ nivel: 'producto', grupo_categoria: 'NOTEBOOKS', orden: 'valor_erp' }));
  });

  it('a group without cost on some products still shows its costed value and says "N productos sin costo"', async () => {
    const user = userEvent.setup();
    const t = await openAt();
    await user.click(await t.findByRole('button', { name: 'Abrir Sin marca' }));
    // the cable has no cost: its category and brand say so, and their values are the costed part
    expect(within(rowOf('Sin categoría')).getByText('1 producto sin costo')).toBeInTheDocument();
    expect(within(rowOf('Sin marca')).getByText('1 producto sin costo')).toBeInTheDocument();
    // DEMO is its products' exact sum: notebook 21.000 + cartridge 806,90 + PC 2.440
    expect(within(rowOf('DEMO')).queryByText(/sin costo/)).not.toBeInTheDocument();
    expect(rowOf('DEMO').querySelector('td[data-column="valor_total"]').textContent).toContain('24.247');
  });

  it('the Excel export carries the level and the drill', async () => {
    const user = userEvent.setup();
    exportAuditoriaStockExcel.mockReset();
    exportAuditoriaStockExcel.mockResolvedValue(undefined);
    await openAt('&nivel=categoria&grupo_marca=DEMO');
    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await waitFor(() => expect(exportAuditoriaStockExcel).toHaveBeenCalledTimes(1));
    expect(exportAuditoriaStockExcel).toHaveBeenCalledWith({ nivel: 'categoria', grupo_marca: 'DEMO', orden: 'valor_total', dir: 'desc' });
  });
});

describe('auditoria-stock-niveles S3, S4: "ERP n · Full n" under the sales, coverage and rotation', () => {
  const rowOf = (name) => within(table()).getByText(name, { selector: 'span' }).closest('tr');
  const cell = (row, key) => row.querySelector(`td[data-column="${key}"]`);

  it('a brand row: its split; a sale without shipping data is a pickup, plain ERP with no warning (L3)', async () => {
    publicacionesMlAPI.stockAudit.mockImplementation((params) => Promise.resolve({ data: stockAuditLevelResponse(params) }));
    const t = await audit('/ml-publicaciones?vista=auditoria');
    await t.findByText('DEMO', { selector: 'span' });
    const brand = rowOf('DEMO');
    // the sum of its products: notebook ERP 4 · Full 2 + cartridge ERP 6 · Full 3 (2 without shipping data) + PC 0
    expect(cell(brand, 'unidades_7d')).toHaveTextContent('ERP 10 · Full 5');
    expect(cell(brand, 'unidades_30d')).toHaveTextContent('ERP 45 · Full 22');
    for (const key of ['unidades_7d', 'unidades_30d']) {
      expect(within(cell(brand, key)).queryByTitle(/sin dato de envío/)).not.toBeInTheDocument();
      expect(cell(brand, key)).not.toHaveTextContent(/sin dato/);
    }
    expect(cell(rowOf('Sin marca'), 'unidades_7d')).toHaveTextContent('ERP 0 · Full 0');
  });

  it('auditoria-ventas-erp-full S1: a product row\'s sales say only where the stock left from, never "de variantes"', async () => {
    const t = await audit();
    for (const name of ['Notebook Demo 14 i5 8GB 512GB', 'Cartucho Demo 01 negro']) {
      const row = rowOf(name);
      for (const key of ['unidades_7d', 'unidades_30d']) {
        expect(cell(row, key)).toHaveTextContent(/ERP \d+ · Full \d+/);
        expect(cell(row, key)).not.toHaveTextContent(/de variantes|del pack|variante/);
      }
    }
    // the Full stock still says where its units are (that note is about stock, not sales)
    expect(t.getByText('12 de variantes')).toBeInTheDocument();
  });

  it('a product row and a pack (in base units, ERP + Full = the total shown)', async () => {
    const user = userEvent.setup();
    const t = await audit();
    const notebook = rowOf('Notebook Demo 14 i5 8GB 512GB');
    expect(cell(notebook, 'unidades_7d')).toHaveTextContent('ERP 4 · Full 2');
    expect(cell(notebook, 'unidades_30d')).toHaveTextContent('ERP 16 · Full 8');
    expect(within(notebook).queryByTitle(/sin dato de envío/)).not.toBeInTheDocument();
    await user.click(t.getByRole('button', { name: 'Abrir Cartucho Demo 01 negro' }));
    const pack = rowOf('Cartucho Demo 01 negro x2');
    // 4 packs in 7 days = 8 units: ERP 3 + Full 1 packs = 6 + 2 units
    expect(cell(pack, 'unidades_7d')).toHaveTextContent('8');
    expect(cell(pack, 'unidades_7d')).toHaveTextContent('ERP 6 · Full 2');
    expect(cell(pack, 'unidades_30d')).toHaveTextContent('ERP 24 · Full 12');
  });

  it('a publication row: the split of /items?desglose_envio=true, with no shipping warning (L3)', async () => {
    const user = userEvent.setup();
    const t = await audit();
    await user.click(t.getByRole('button', { name: 'Abrir Notebook Demo 14 i5 8GB 512GB' }));
    const publication = (await t.findByText('MLA1900000001')).closest('tr');
    expect(publicacionesMlAPI.items.mock.calls.at(-1)[0]).toMatchObject({ item_ids: '9001', desglose_envio: true });
    expect(cell(publication, 'unidades_7d')).toHaveTextContent('ERP 3 · Full 1');
    expect(cell(publication, 'unidades_30d')).toHaveTextContent('ERP 12 · Full 3');
    expect(within(cell(publication, 'unidades_30d')).queryByTitle(/sin dato de envío/)).not.toBeInTheDocument();
  });

  it('coverage and rotation by origin, ∞ for stock without sales and "—" for none', async () => {
    await audit();
    const notebook = rowOf('Notebook Demo 14 i5 8GB 512GB');
    // ERP 30 in stock over 16 ERP sales = 56 days, 16 / 30 = 0,53; Full 20 over 8 Full sales = 75 days, 8 / 20 = 0,40
    expect(cell(notebook, 'cobertura')).toHaveTextContent('ERP 56 · Full 75');
    expect(cell(notebook, 'rotacion')).toHaveTextContent('ERP 0,53 · Full 0,40');
    // another product, other numbers: ERP 80 over 29 = 83 days, Full 50 over 14 = 107 days
    const cartridge = rowOf('Cartucho Demo 01 negro');
    expect(cell(cartridge, 'cobertura')).toHaveTextContent('ERP 83 · Full 107');
    const pc = rowOf(AUDIT_ORPHAN.descripcion);
    expect(cell(pc, 'cobertura')).toHaveTextContent('ERP ∞ · Full —');
    expect(cell(pc, 'rotacion')).toHaveTextContent('ERP 0,00 · Full —');
  });

  it('ERP sales without ERP stock read out of stock: 0 days and an infinite rotation, never "—" (PR #2345 review)', async () => {
    const user = userEvent.setup();
    const t = await audit();
    await user.click(t.getByRole('button', { name: 'Abrir Notebook Demo 14 i5 8GB 512GB' }));
    // the 16GB variant sold 6 by ERP in 30 days and holds no ERP stock of its own; Full 12 over 2 Full sales
    const variant = rowOf('Notebook Demo 14 i5 16GB 512GB');
    expect(cell(variant, 'cobertura')).toHaveTextContent('ERP 0 · Full 180');
    expect(cell(variant, 'rotacion')).toHaveTextContent('ERP ∞ · Full 0,17');
  });
});
