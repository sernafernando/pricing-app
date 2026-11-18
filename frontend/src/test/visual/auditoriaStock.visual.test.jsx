/**
 * Auditoría de stock (auditoria-stock S3-S7, S10, L6) -- the real page, real CSS, real Chromium, with invented
 * `GET /view/stock-audit` and `/view/items` answers (`stockAuditFixtures`). Checks the view fits the window in both
 * themes and, with `VITE_AUDITORIA_SHOTS_DIR`, takes the screenshots compared with the approved mock v2.
 *
 *   VITE_AUDITORIA_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual auditoriaStock
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme, tokenColor } from './visualHelpers';
import PublicacionesML from '../../pages/PublicacionesML';
import { publicacionesMlAPI } from '../../services/api';
import { FACETS, ITEMS_RESPONSE, KPIS_RESPONSE } from './publicacionesMlFixtures';
import { AUDIT_CARTRIDGE_ITEMS, AUDIT_NOTEBOOK_ITEMS, AUDIT_PACK_ITEMS, stockAuditLevelResponse, stockAuditResponse } from './stockAuditFixtures';

const BRANCHES = { 9001: AUDIT_NOTEBOOK_ITEMS, 9101: AUDIT_CARTRIDGE_ITEMS, 9102: AUDIT_PACK_ITEMS };

// The markup column, its filters and the sub-rows' cost are for `ver_ganancia` only.
let canSeeMargin = false;
let canSeeKpis = true;
// One function for every render, as the real context's `tienePermiso` is: hooks that read on its change (the
// prearmadas badge) would otherwise cancel their own read on each render.
const tienePermiso = (permiso) => {
  if (permiso === 'ml_metricas.ver_ganancia') return canSeeMargin;
  if (permiso === 'ml_metricas.ver') return canSeeKpis;
  return true;
};
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso,
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../hooks/useSSEChannel', () => ({ useSSEChannel: vi.fn() }));
// The product panel's publication tree (Productos' `ProductoMLAsPanel`): the product's publication, collapsed.
const DEFAULT_TREE = vi.hoisted(() => ({
  data: {
    item_id: 4101,
    tree: {
      level: 0,
      kind: 'producto',
      label: 'Router Archer AX55',
      children: [
        { level: 1, kind: 'publicacion', mla: 'MLA1100000005', label: 'Router TP-Link Archer AX55 por color', pricelist_id: 4, publication_status: 'active', children: [] },
      ],
    },
    skipped_anomalous_edges: 0,
    skipped_edges: [],
  },
}));
// The reads of `api.get` the page makes: Productos' Tienda Nube card surcharge (the Web Transf. hint) and the
// Auditoría panel's users and kinds, the long ones as in production; every other read, an empty list.
const API_GETS = vi.hoisted(() => ({
  '/markups-tienda/config/porcentaje_tarjeta_tn': { valor: 25 },
  '/auditoria/usuarios': {
    usuarios: [
      { id: 1, nombre: 'Gabriel DeMarco' },
      { id: 2, nombre: 'leandrorochagausson' },
      { id: 3, nombre: 'Agustina Montivero' },
    ],
  },
  '/auditoria/tipos-accion': {
    tipos: ['modificar_precio_clasica', 'modificar_precio_web', 'modificar_porcentaje_rebate', 'desmarcar_out_of_cards', 'activar_web_transferencia'],
  },
  // The product panel's sell-in lots (`SellInLotes`): a used-up lot, the current one, a queued USD one, a future one.
  '/sell-in/productos/4101/lotes': {
    item_id: 4101,
    lotes: [
      { numero: 1, compra_item_id: 501, compra_id: 41, proveedor: 'Mayorista Sur SRL', facturas: ['A-0003-00012345'], moneda: 'ARS', fecha_desde: '2026-09-01', cantidad: 20, consumidas: 20, restantes: 0, descuento_unit: '1250.000000', estado: 'agotado' },
      { numero: 2, compra_item_id: 502, compra_id: 42, proveedor: 'Mayorista Sur SRL', facturas: ['A-0003-00012390', 'A-0003-00012391'], moneda: 'ARS', fecha_desde: '2026-10-05', cantidad: 30, consumidas: 12, restantes: 18, descuento_unit: '980.333333', estado: 'vigente' },
      { numero: 3, compra_item_id: 503, compra_id: 43, proveedor: null, facturas: [], moneda: 'USD', fecha_desde: '2026-10-08', cantidad: 10, consumidas: 0, restantes: 10, descuento_unit: '10500.000000', estado: 'en_cola' },
      { numero: 4, compra_item_id: 504, compra_id: 44, proveedor: 'TP-Link Argentina', facturas: ['B-0001-00000077'], moneda: 'ARS', fecha_desde: '2026-11-15', cantidad: 50, consumidas: 0, restantes: 50, descuento_unit: '700.000000', estado: 'desde' },
    ],
    proxima: { numero: 2, compra_item_id: 502, descuento_unit: '980.333333', restantes: 18, siguiente: { numero: 3, descuento_unit: '10500.000000', fecha_desde: '2026-10-08', estado: 'en_cola' } },
    bono_costo: null,
    compra_visible: true,
  },
}));
vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn((url) => Promise.resolve({ data: API_GETS[url] ?? [] })),
    // Only the prearmadas badge posts here: two ready for every product asked.
    post: vi.fn((url, body) =>
      Promise.resolve({ data: { stats: Object.fromEntries((body?.items ?? []).map(({ item_id }) => [item_id, { exact: 2, upgrade: 0 }])) } }),
    ),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  pxqAPI: { getLive: vi.fn(), getMarkup: vi.fn(), createTier: vi.fn(), updateTier: vi.fn(), deleteTier: vi.fn(), sync: vi.fn(), adoptLive: vi.fn() },
  publicacionesMlAPI: { stockAudit: vi.fn(), items: vi.fn(), products: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), events: vi.fn(), history: vi.fn(), enqueue: vi.fn(), setItemStatus: vi.fn(), statusItemIds: vi.fn(), statusBulk: vi.fn(), kpis: vi.fn(), stats: vi.fn(() => Promise.resolve({ data: { stats: { total: 40, con_stock: 30, con_precio: 35, con_stock_sin_precio: 3, nuevos: 5, nuevos_sin_precio: 2, oferta_sin_rebate: 4 }, can_see_margin: false } })), productIds: vi.fn(() => Promise.resolve({ data: { item_ids: [4101, 4102], count: 2, sin_producto: 1 } })), productEnvio: vi.fn(() => new Promise(() => {})), saveProductEnvio: vi.fn(), productLinks: vi.fn(() => Promise.resolve({ data: { units: [] } })), setProductLink: vi.fn(), setProductLinkNone: vi.fn(), revertProductLinkAuto: vi.fn(), searchProducts: vi.fn() },
  productosPropiosAPI: {
    get: vi.fn(() =>
      Promise.resolve({
        data: { item_id: 4101, codigo: '6935364099589', descripcion: 'Router Archer AX55', ean: '6935364099589', ean_manual: false, sku: 'ARCHER-AX55', sku_manual: false, sku_candidatos: ['ARCHER-AX55'], can_edit: false },
      }),
    ),
    save: vi.fn(),
    chooseSource: vi.fn(),
    saveDatos: vi.fn(),
  },
  mlItemOverridesAPI: { get: vi.fn(), save: vi.fn(), pushToMl: vi.fn() },
  productoBanlistAPI: { add: vi.fn() },
  productoMaestroAPI: { listar: vi.fn(), leer: vi.fn(), guardar: vi.fn() },
  productoSpecsAPI: { leer: vi.fn(), guardar: vi.fn(), precargar: vi.fn(), campos: vi.fn(), valores: vi.fn() },
  productoTnVinculosAPI: { leer: vi.fn(), candidatos: vi.fn(), vincular: vi.fn() },
  productoMarcasAPI: { listar: vi.fn() },
  productoCategoriasAPI: { listar: vi.fn() },
  promocionesAPI: { getPromocionesItem: vi.fn(), getMarkupParaPrecio: vi.fn(() => Promise.resolve({ data: { nuestro_markup: null } })), descartarHayMejores: vi.fn(), refreshItemPromociones: vi.fn(), confirmarSinPromosML: vi.fn(), getCompetenciaCatalogo: vi.fn(), refreshCompetenciaCatalogo: vi.fn() },
  productosAPI: {
    getProductoTree: vi.fn(() => Promise.resolve(DEFAULT_TREE)),
    marcas: vi.fn(() => Promise.resolve({ data: { marcas: [] } })),
    categorias: vi.fn(() => Promise.resolve({ data: { categorias: [] } })),
    subcategorias: vi.fn(() => Promise.resolve({ data: { categorias: [] } })),
    pms: vi.fn(() => Promise.resolve({ data: [] })),
    // Productos' prices of the products on show (S11): Normal, Cuotas and PVP columns.
    listar: vi.fn(() =>
      Promise.resolve({
        data: {
          productos: [
            { item_id: 4101, descripcion: 'Router Archer AX55', marca: 'TP-LINK', categoria: 'REDES', stock: 12, costo: 95.5, moneda_costo: 'USD',
              precio_lista_ml: 189999, markup: 24.3, participa_rebate: true, precio_rebate: 197911, markup_rebate: 21.1,
              precio_3_cuotas: 209999, markup_3_cuotas: 18.2, precio_6_cuotas: 229999, markup_6_cuotas: 15.4,
              precio_pvp: 239999, markup_pvp: 31.9, has_catalog: true, catalog_status: 'winning', catalog_winner_price: 189999,
              tn_price: 249999, tn_promotional_price: 229999, tn_has_promotion: true,
              participa_web_transferencia: true, precio_web_transferencia: 179899, markup_web_real: 17.6, porcentaje_markup_web: 6.5,
              preservar_porcentaje_web: true },
            { item_id: 4102, precio_lista_ml: 45999, markup: -3.2, mejor_oferta_precio: 41399, mejor_oferta_markup: -0.098,
              mejor_oferta_porcentaje_rebate: 12.5, mejor_oferta_monto_rebate: 5174.88, mejor_oferta_fecha_hasta: '2026-11-30',
              mejor_oferta_pvp_seller: 47999, tn_price: 52999 },
          ],
          total: 2,
        },
      }),
    ),
    auditoria: vi.fn(() =>
      Promise.resolve({
        data: [
          {
            id: 2,
            item_id: 4101,
            usuario_nombre: 'Ana Pérez',
            usuario_email: 'ana.perez@example.com',
            tipo_accion: 'modificar_precio_clasica',
            valores_anteriores: { precio_lista_ml: 98500, markup_calculado: 12.5 },
            valores_nuevos: { precio_lista_ml: 102000.5, markup_calculado: 15.25 },
            fecha_cambio: '2026-10-20T14:30:00',
            comentario: 'Ajuste por la lista nueva del proveedor, con un comentario largo para ver cómo corta',
          },
          {
            id: 1,
            item_id: 4101,
            usuario_nombre: 'Juan Gómez',
            usuario_email: 'juan@example.com',
            tipo_accion: 'ml_vinculo_manual',
            valores_anteriores: null,
            valores_nuevos: { item_id: 'MLA1100000001', variation_id: null, producto: { item_id: 4101, codigo: 'ARCHER-AX55' } },
            fecha_cambio: '2026-10-19T10:00:00',
            comentario: null,
          },
        ],
      }),
    ),
    configCuotas: vi.fn(),
    detalle: vi.fn(() =>
      Promise.resolve({
        data: {
          ultimas_compras: [
            { proveedor: 'TP-Link Argentina S.A. con una razón social bastante larga', fecha: '2026-10-14T00:00:00', cantidad: 120, precio_unitario: 45.5, moneda_id: 2 },
            { proveedor: 'Distribuidora Norte', fecha: '2026-09-02T00:00:00', cantidad: 1.5, precio_unitario: 98500, moneda_id: 1 },
          ],
        },
      }),
    ),
  },
  preciosAPI: {
    obtenerProducto: vi.fn(() => new Promise(() => {})),
    tipoCambioActual: vi.fn(() => new Promise(() => {})),
    calcularMarkup: vi.fn(),
    calcularPorMarkup: vi.fn(),
    setRapido: vi.fn(),
    setCuota: vi.fn(),
  },
  offsetsGananciaAPI: {
    vigentes: vi.fn(() => new Promise(() => {})),
    grupoFiltros: vi.fn(() => new Promise(() => {})),
  },
  equiposAPI: { listar: vi.fn(() => Promise.resolve({ data: [] })) },
  registerAuthFailureHandler: vi.fn(),
}));


const SHOTS_DIR = import.meta.env.VITE_AUDITORIA_SHOTS_DIR;

const Shell = ({ children }) => (
  <div data-shell style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>
    {children}
  </div>
);

const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

// The product level unless a case says otherwise; the view itself opens on Marca (auditoria-stock-niveles S1).
const renderAudit = async ({ width = 2000, height = 1750, theme = 'light', entry = '/ml-publicaciones?vista=auditoria&nivel=producto', ready = 'Cartucho Demo 01 negro' } = {}) => {
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  window.scrollTo(0, 0);
  const screen = await render(
    <MemoryRouter initialEntries={[entry]}>
      <Shell>
        <PublicacionesML />
      </Shell>
    </MemoryRouter>,
  );
  await expect.element(screen.getByText(ready, { exact: true })).toBeVisible();
  return screen;
};

const open = async (screen, name) => {
  await userEvent.click(screen.getByRole('button', { name: `Abrir ${name}` }));
  await frame();
};

beforeEach(() => {
  canSeeMargin = true;
  canSeeKpis = true;
  localStorage.clear();
  publicacionesMlAPI.stockAudit.mockReset();
  publicacionesMlAPI.stockAudit.mockResolvedValue({ data: stockAuditResponse() });
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.items.mockImplementation((params) =>
    Promise.resolve({
      data: params?.item_ids
        ? (BRANCHES[params.item_ids] ?? { items: [], total: 0, limit: 100, offset: 0 })
        : { ...ITEMS_RESPONSE, facets: { ...FACETS, promo: { con_promo: 70, sin_promo: 165 } } },
    }),
  );
  publicacionesMlAPI.kpis.mockReset();
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE });
});

describe('Auditoría de stock', () => {
  for (const theme of ['light', 'dark']) {
    it(`2000x1750 ${theme}: KPIs, rate line and the table open into variants and publications, inside the window`, async () => {
      const screen = await renderAudit({ theme });
      await open(screen, 'Notebook Demo 14 i5 8GB 512GB');
      await expect.element(screen.getByText('MLA1900000001')).toBeVisible();
      await open(screen, 'Cartucho Demo 01 negro');
      await expect.element(screen.getByText('Cartucho Demo 01 negro x2')).toBeVisible();
      await open(screen, 'Cartucho Demo 01 negro x2');
      await expect.element(screen.getByText('MLA1900000102')).toBeVisible();
      // The page never scrolls sideways: the table does, in its own scroller.
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(2000);
      const accent = document.querySelector('[class*="cardAccent"]');
      expect(getComputedStyle(accent).borderColor).toBe(tokenColor('--cf-accent-blue'));
      // The badge of a publication with a started promotion is the success tone.
      const badge = screen.getByRole('table', { name: 'Auditoría de stock' }).getByText('Promo aplicada', { exact: true }).first().element();
      expect(getComputedStyle(badge).backgroundColor).toBe(tokenColor('--tone-success-bg'));
      window.scrollTo(0, 0);
      await frame();
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/auditoria-stock-${theme}.png` });
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`2000x1750 ${theme}: the Promos aplicadas column, a green and a red tag with their counts (promos-fila S2)`, async () => {
      const screen = await renderAudit({ theme });
      await open(screen, 'Notebook Demo 14 i5 8GB 512GB');
      await expect.element(screen.getByText('MLA1900000001')).toBeVisible();
      const con = screen.getByLabelText('2 publicaciones con promo aplicada').element();
      const sin = screen.getByLabelText('3 publicaciones sin promo aplicada').element();
      expect(getComputedStyle(con).color).toBe(tokenColor('--tone-success-fg'));
      expect(getComputedStyle(sin).color).toBe(tokenColor('--tone-danger-fg'));
      // The icon only, no "Promo aplicada" text next to it, on one line.
      expect(con.textContent).toBe('2');
      expect(con.querySelector('svg')).not.toBeNull();
      expect(con.getBoundingClientRect().top).toBe(sin.getBoundingClientRect().top);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(2000);
      window.scrollTo(0, 0);
      await frame();
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/promos-fila-${theme}.png` });
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`2000x1750 ${theme}: the Rotación columns at the end of the table, each figure on one line (rotacion S2)`, async () => {
      const screen = await renderAudit({ theme });
      await open(screen, 'Notebook Demo 14 i5 8GB 512GB');
      await expect.element(screen.getByText('MLA1900000001')).toBeVisible();
      // The table scrolls sideways in its own scroller: bring its last group, Rotación, into view.
      let scroller = screen.getByRole('table', { name: 'Auditoría de stock' }).element();
      while (scroller && !['auto', 'scroll'].includes(getComputedStyle(scroller).overflowX)) scroller = scroller.parentElement;
      scroller.scrollLeft = scroller.scrollWidth;
      await frame();
      const infinite = screen.getByTitle('Con stock y sin ventas en 30 días').element();
      await expect.element(screen.getByTitle('Con stock y sin ventas en 30 días')).toBeVisible();
      for (const cell of document.querySelectorAll('[aria-label="Rotación (veces)"], [aria-label="Días de cobertura"]')) {
        expect(cell.getBoundingClientRect().height).toBeLessThan(24); // one line, never wrapped
      }
      expect(getComputedStyle(infinite).color).toBe(tokenColor('--text-primary'));
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(2000);
      window.scrollTo(0, 0);
      await frame();
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/rotacion-${theme}.png` });
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`2000x1750 ${theme}: the Marca level, a brand open into its categories and a category into its products (auditoria-stock-niveles S1, S3)`, async () => {
      publicacionesMlAPI.stockAudit.mockImplementation((params) => Promise.resolve({ data: stockAuditLevelResponse(params) }));
      const screen = await renderAudit({ theme, entry: '/ml-publicaciones?vista=auditoria', ready: 'DEMO' });
      await open(screen, 'DEMO');
      await expect.element(screen.getByText('INSUMOS', { exact: true })).toBeVisible();
      await open(screen, 'INSUMOS');
      await expect.element(screen.getByText('Cartucho Demo 01 negro', { exact: true })).toBeVisible();
      await expect.element(screen.getByRole('group', { name: 'Ver por' })).toBeVisible();
      // The ERP / Full line under each sales figure, one line, in the muted tone.
      const split = screen.getByText('ERP 12', { exact: true }).element();
      expect(split.getAttribute('title')).toBe('incluye 2 sin dato de envío');
      expect(split.parentElement.getBoundingClientRect().height).toBeLessThan(20);
      expect(getComputedStyle(split.parentElement).color).toBe(tokenColor('--cf-text-tertiary'));
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(2000);
      window.scrollTo(0, 0);
      await frame();
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/niveles-${theme}.png` });
      screen.unmount();
    });
  }

  it('2000x1750 light: the column picker lists every column, each one can be hidden', async () => {
    const screen = await renderAudit();
    await userEvent.click(screen.getByRole('button', { name: 'Columnas' }));
    const picker = screen.getByRole('group', { name: /columnas/i });
    await expect.element(picker.getByRole('checkbox', { name: 'Tendencia de ventas' })).toBeVisible();
    await expect.element(picker.getByRole('checkbox', { name: 'Tendencia de markup' })).toBeVisible();
    await expect.element(picker.getByRole('checkbox', { name: 'Estado' })).toBeVisible();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/auditoria-stock-columnas-light.png` });
    screen.unmount();
  });
});
