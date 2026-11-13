/**
 * Publicaciones ML -- the real page, real CSS, real Chromium, fixtures shaped
 * like the backend's `ItemsResponse` (publicaciones-ml-vista P11a.T7).
 *
 * Asserts the layout promises of the kit's `TableShell` on the real screen, at
 * the two widths operators use, in both themes:
 *  - the table scrolls INSIDE its own scroller, never the page;
 *  - the header stays on top and the Publicación column stays pinned while the
 *    scroller moves on both axes;
 *  - money and stock figures never wrap, and no cell content pokes out of its
 *    cell;
 *  - the honest-state banner and the filter band fit, with the theme's tokens.
 *
 *   pnpm exec vitest run --project=visual publicacionesMl
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { contrastRatio, rgba, setTheme, tokenColor } from './visualHelpers';
import PublicacionesML from '../../pages/PublicacionesML';
import { useTreeViewStore } from '../../store/treeViewStore';
import { resetPromoPulls } from '../../components/promociones/promoPullTtl';
import { equiposAPI, mlItemOverridesAPI, offsetsGananciaAPI, preciosAPI, productosAPI, productosPropiosAPI, promocionesAPI, publicacionesMlAPI, pxqAPI } from '../../services/api';
import { PRODUCTO_CON_REBATE_Y_OFERTA, SELL_IN_OUT } from '../../components/pricing/ProductPrices.fixtures';
import {
  BRAND_NODES,
  DATA_STATE_OK,
  DETAIL_RESPONSE,
  DETAIL_LINKED,
  DETAIL_LINKED_MARGIN,
  DETAIL_RESPONSE_MARGIN,
  EVENTS_RESPONSE,
  HISTORY_RESPONSE,
  HISTORY_TECNICOS_RESPONSE,
  FACETS,
  ITEMS,
  KPIS_RESPONSE,
  KPIS_RESPONSE_MARGIN,
  ITEMS_RESPONSE,
  PRODUCT_NODES,
  VARIATIONS_RESPONSE,
  VARIATION_ITEM,
  groupsResponse,
  makeNode,
  productsResponse,
  COST_LINES,
  PRODUCT_ROWS,
} from './publicacionesMlFixtures';

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
  publicacionesMlAPI: { items: vi.fn(), products: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), events: vi.fn(), history: vi.fn(), enqueue: vi.fn(), setItemStatus: vi.fn(), statusItemIds: vi.fn(), statusBulk: vi.fn(), kpis: vi.fn(), stats: vi.fn(() => Promise.resolve({ data: { stats: { total: 40, con_stock: 30, con_precio: 35, con_stock_sin_precio: 3, nuevos: 5, nuevos_sin_precio: 2, oferta_sin_rebate: 4 }, can_see_margin: false } })), productIds: vi.fn(() => Promise.resolve({ data: { item_ids: [4101, 4102], count: 2, sin_producto: 1 } })), productEnvio: vi.fn(() => new Promise(() => {})), saveProductEnvio: vi.fn(), productLinks: vi.fn(() => Promise.resolve({ data: { units: [] } })), setProductLink: vi.fn(), setProductLinkNone: vi.fn(), revertProductLinkAuto: vi.fn(), searchProducts: vi.fn() },
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

// 50 rows so the scroller really has something to scroll vertically.
// Each row carries an ERP stock apart from its ML one: a big figure, a real zero, unknown (no product), a small one.
const ERP_QUANTITIES = [12500, 0, null, 7];
// Métricas ML's figures of each row (`metrics`): big figures, a loss, a quiet publication, and none at all
// (a publication Métricas has no row for reads "—").
const METRICS = [
  {
    units_7d: 1234,
    units_30d: 12345,
    series_units_90d: Array.from({ length: 90 }, (_, d) => 100 + (d % 9) * 20),
    gross_30d: 123456789.5,
    last_sale_at: '2026-10-14T13:05:00Z',
    ageing_days: 0,
    total_gauss_30d: -12345678.9,
    markup_30d: -12.5,
    markup_delta_pp: -3.4,
    series_markup_90d: Array.from({ length: 90 }, (_, d) => (d % 7 === 0 ? null : 10 - (d % 5) * 4)),
  },
  {
    units_7d: 0,
    units_30d: 3,
    series_units_90d: Array.from({ length: 90 }, (_, d) => (d > 80 ? 1 : 0)),
    gross_30d: 45000,
    last_sale_at: '2026-09-20T15:00:00Z',
    ageing_days: 24,
    total_gauss_30d: 9000,
    markup_30d: 25.1,
    markup_delta_pp: 1.2,
    series_markup_90d: Array.from({ length: 90 }, (_, d) => (d > 80 ? 25.1 : null)),
  },
  {
    units_7d: 0,
    units_30d: 0,
    series_units_90d: Array.from({ length: 90 }, () => 0),
    gross_30d: 0,
    last_sale_at: '2026-06-01T15:00:00Z',
    ageing_days: 135,
    total_gauss_30d: 0,
    markup_30d: null,
    markup_delta_pp: null,
    series_markup_90d: Array.from({ length: 90 }, () => null),
  },
  null,
];
const stockTotal = (erp, full) => (erp == null && full == null ? null : (erp ?? 0) + (full ?? 0));
const MANY = Array.from({ length: 50 }, (_, i) => ({
  ...ITEMS[i % ITEMS.length],
  item_id: `MLA${1100000100 + i}`,
  erp_stock: { quantity: ERP_QUANTITIES[i % ERP_QUANTITIES.length] },
  // The backend's ERP + Full (`filters.stock_total_of`), unknown when both are.
  stock_total: stockTotal(ERP_QUANTITIES[i % ERP_QUANTITIES.length], ITEMS[i % ITEMS.length].stock?.full),
  metrics: METRICS[i % METRICS.length],
}));
const RESPONSE = {
  ...ITEMS_RESPONSE,
  items: MANY,
  facets: { ...FACETS, stock: { ...FACETS.stock, erp_sin_stock: 9 }, promo: { con_promo: 70, sin_promo: 165 } },
  data_state: {
    ...DATA_STATE_OK,
    degraded: true,
    degradations: [{ code: 'resource_not_collected', resource: 'stock', affects: ['stock.full', 'stock.own'] }],
  },
};

// Fixed TopBar + collapsed sidebar, as the operator sees it.
const Shell = ({ children }) => (
  <div
    data-shell
    style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}
  >
    {children}
  </div>
);

// The publication rows with Productos' price columns (owner, 2026-10-28).
const PRECIOS = '/ml-publicaciones?vista=precios';

const renderPage = async ({ width, height, theme, entry = '/ml-publicaciones' }) => {
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
  await expect.element(screen.getByText('MLA1100000100')).toBeVisible();
  return screen;
};

const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const scrollerOf = () => document.querySelector('[data-table-shell-scroller]');
const rect = (el) => el.getBoundingClientRect();

// A cell's content horizontally inside its own <td>.
// Inside a box of the cell that cuts what overflows it (a line cut with "…", whole in its tooltip): never drawn outside.
const clippedInside = (el, td) => {
  for (let box = el.parentElement; box && box !== td; box = box.parentElement) {
    if (['hidden', 'clip'].includes(getComputedStyle(box).overflowX)) return true;
  }
  return false;
};

const overflowingCells = (root) => {
  const offenders = [];
  for (const td of root.querySelectorAll('tbody td')) {
    const box = td.getBoundingClientRect();
    for (const child of td.querySelectorAll('*')) {
      const r = child.getBoundingClientRect();
      if (r.width === 0 || clippedInside(child, td)) continue;
      if (r.right > box.right + 0.5 || r.left < box.left - 0.5) {
        offenders.push(`${td.textContent.trim().slice(0, 40)} > ${child.textContent.trim().slice(0, 30)}`);
        break;
      }
    }
  }
  return offenders;
};

const lineHeightOf = (el) => {
  const style = getComputedStyle(el);
  return Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.3;
};
// On more than one line: its boxes sit at different heights. A line can hold several boxes of one element (a font
// fallback or letter spacing splits the text into runs), so the count of boxes alone is not a wrap.
const linesOf = (el) => new Set([...el.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top))).size;
const wrapped = (elements) =>
  [...elements]
    .filter((el) => linesOf(el) > 1 || rect(el).height > lineHeightOf(el) * 1.6)
    .map((el) => el.textContent.trim());

// Every suite shows the strip unless it says otherwise.
beforeEach(() => {
  // Promos opens first and pulls; the pull TTL is module-wide, so each test starts with none.
  resetPromoPulls();
  canSeeKpis = true;
  publicacionesMlAPI.kpis.mockReset();
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE });
});

const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
];
const THEMES = ['light', 'dark'];

describe('Publicaciones ML (visual)', () => {
  beforeEach(() => {
    canSeeMargin = false;
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockResolvedValue({ data: RESPONSE });
  });

  for (const { width, height } of VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the table scrolls inside its own scroller and the page does not scroll sideways`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        const box = rect(scroller);
        expect(box.right).toBeLessThanOrEqual(width + 0.5);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        // The scroller is bounded, and the rows really overflow it vertically.
        expect(getComputedStyle(scroller).overflowY).toBe('auto');
        expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight);
        // Its card follows the theme.
        expect(getComputedStyle(scroller).backgroundColor).toBe(tokenColor('--cf-bg-card'));
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the header stays on top and the Publicación column stays pinned while scrolling both axes`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        // The filters above can push the table below a short window, and elementFromPoint sees only the viewport.
        scroller.scrollIntoView({ block: 'start' });
        scroller.scrollTo({ top: 300, left: 120 });
        await frame();
        const scrollerBox = rect(scroller);
        const header = scroller.querySelector('thead th');
        const firstRow = scroller.querySelector('tbody tr');
        // Header pinned to the scroller's top edge, above every body row.
        expect(Math.abs(rect(header).top - scrollerBox.top)).toBeLessThanOrEqual(2);
        // ... and painted OVER the rows scrolling beneath it.
        const probe = document.elementFromPoint(rect(header).left + rect(header).width / 2, rect(header).top + rect(header).height / 2);
        expect(scroller.querySelector('thead').contains(probe)).toBe(true);
        // First column pinned to the scroller's left edge.
        const pinned = firstRow.querySelector('td[data-pinned]');
        expect(Math.abs(rect(pinned).left - scrollerBox.left)).toBeLessThanOrEqual(2);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: money, stock and chips stay on one line and nothing pokes out of its cell`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        const figures = [...scroller.querySelectorAll('td[data-align] span')].filter((el) =>
          /^[\d.,]+$/.test(el.textContent.trim()),
        );
        expect(figures.length).toBeGreaterThan(0);
        expect(wrapped(figures)).toEqual([]);
        expect(overflowingCells(scroller)).toEqual([]);

        const chips = [...document.querySelectorAll('section[aria-label="Filtros"] button')];
        expect(chips.length).toBeGreaterThan(10);
        for (const chip of chips) {
          expect(rect(chip).right, chip.textContent).toBeLessThanOrEqual(width);
        }
        for (const band of document.querySelectorAll('div[class*="filterBand"]')) {
          expect(band.scrollWidth).toBeLessThanOrEqual(band.clientWidth + 1);
        }
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the Precios view's stat cards keep every label and figure on one line, inside their card`, async () => {
        const screen = await renderPage({ width, height, theme, entry: PRECIOS });
        await expect.element(screen.getByRole('button', { name: 'Stock sin $: 3' })).toBeVisible();
        const strip = document.querySelector('section[aria-label="Totales de productos"]');
        const cards = [...strip.querySelectorAll('[role="group"]')];
        expect(cards.length).toBe(4);
        for (const card of cards) {
          expect(rect(card).right, card.getAttribute('aria-label')).toBeLessThanOrEqual(width);
          for (const button of card.querySelectorAll('button')) {
            expect(rect(button).right, button.getAttribute('aria-label')).toBeLessThanOrEqual(rect(card).right + 0.5);
          }
        }
        expect(wrapped([...strip.querySelectorAll('button span')])).toEqual([]);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/stat-cards-${width}-${theme}.png` });
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the Publicaciones view sums up publications: active, paused, with and without promo, one line each`, async () => {
        const screen = await renderPage({ width, height, theme });
        await expect.element(screen.getByRole('button', { name: 'Activas: 180' })).toBeVisible();
        const strip = document.querySelector('section[aria-label="Totales de publicaciones"]');
        const cards = [...strip.querySelectorAll('[role="group"]')];
        expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual(['Activas', 'Pausadas', 'Con promo', 'Sin promo']);
        for (const card of cards) expect(rect(card).right, card.getAttribute('aria-label')).toBeLessThanOrEqual(width);
        expect(wrapped([...strip.querySelectorAll('span')])).toEqual([]);
        expect(document.querySelector('section[aria-label="Totales de productos"]')).toBeNull();
        // Ventas 7D is the column right after Precio.
        const th = (key) => rect(scrollerOf().querySelector(`thead th[data-column="${key}"]`));
        expect(Math.abs(th('unidades_7d').left - th('precio').right)).toBeLessThanOrEqual(1);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/vista-publicaciones-${width}-${theme}.png` });
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the Precios view is the publication rows with Productos' price group right after Precio`, async () => {
        const screen = await renderPage({ width, height, theme, entry: PRECIOS });
        const scroller = scrollerOf();
        const groups = [...scroller.querySelectorAll('thead th[scope="colgroup"]')].map((th) => th.textContent);
        expect(groups).toEqual(['Precios de Productos', 'Ventas (unidades)', 'Resultado financiero', 'Rotación', 'Stock']);
        await expect.element(screen.getByRole('button', { name: 'Precios', pressed: true })).toBeVisible();
        expect(overflowingCells(scroller)).toEqual([]);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/vista-precios-${width}-${theme}.png` });
        screen.unmount();
      });

      // Owner, 2026-11-04: "en la vista de poner precios ... también tienen que estar los badges de Clásica, 3 cuotas,
      // etc y el orden también cuando estan varias publis del mismo producto juntas".
      for (const highContrast of width === 1366 ? [false, true] : []) {
        it(`${width}x${height} ${theme}${highContrast ? ', high contrast' : ''}: MODO PONER PRECIOS shows the Tipo badges, sorted by Código then Tipo`, async () => {
          document.documentElement.classList.toggle('high-contrast', highContrast);
          let screen;
          try {
            screen = await renderPage({ width, height, theme, entry: '/ml-publicaciones?orden=codigo&dir=asc' });
            await screen.getByRole('button', { name: 'MODO PONER PRECIOS' }).click();
            const tipo = () => scrollerOf().querySelector('thead th[data-column="tipo"]');
            await expect.poll(() => tipo()).toBeTruthy();
            expect(tipo().querySelector('[data-testid="sort-order"]')?.textContent).toBe('2');
            expect(scrollerOf().querySelector('tbody td[data-column="tipo"]')?.textContent).toBeTruthy();
            expect(overflowingCells(scrollerOf())).toEqual([]);
            if (PRODUCT_SHOTS_DIR) {
              // Tall enough for several rows, the Código column (the first sort) in view at the right.
              await page.viewport(1920, 1300);
              await frame();
              await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/poner-precios-tipo-${theme}${highContrast ? '-hc' : ''}.png` });
            }
          } finally {
            screen?.unmount();
            document.documentElement.classList.remove('high-contrast');
          }
        });
      }

      it(`${width}x${height} ${theme}: ERP, Full and total stock sit in three columns under STOCK, headers and figures on one line`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        const headers = ['stock_erp', 'stock_full', 'stock_total'].map((key) => scroller.querySelector(`thead th[data-column="${key}"]`));
        expect(headers.map((th) => th.textContent)).toEqual(['ERP', 'Full', 'Total']);
        expect(scroller.querySelector('thead th[data-column="stock_propio"]')).toBeNull();
        const group = [...scroller.querySelectorAll('thead th[scope="colgroup"]')].find((th) => th.textContent === 'Stock');
        expect(group.colSpan).toBe(3);
        expect(wrapped(headers.map((th) => th.querySelector('button')))).toEqual([]);
        // Never the available sum nor our own quantity: the first fixture row has 34 available, 20 Full, 14 of our own.
        const first = scroller.querySelector('tbody tr');
        expect(first.querySelector('td[data-column="stock_full"]').textContent).toBe('20');
        // 12.500 in the ERP + 20 in Full.
        const digits = (key) => first.querySelector(`td[data-column="${key}"]`).textContent.replace(/\D/g, '');
        expect(digits('stock_erp')).toBe('12500');
        expect(digits('stock_total')).toBe('12520');
        // The three figures read alike: thousands grouped, same font, size and weight.
        expect(first.querySelector('td[data-column="stock_erp"]').textContent).toBe('12.500');
        expect(first.querySelector('td[data-column="stock_total"]').textContent).toBe('12.520');
        const look = (key) => {
          const figure = [...first.querySelectorAll(`td[data-column="${key}"] span`)].find((el) => el.textContent.trim() && !el.children.length);
          const style = getComputedStyle(figure);
          return [style.fontFamily, style.fontSize, style.fontWeight].join(' / ');
        };
        expect(look('stock_erp')).toBe(look('stock_total'));
        expect(look('stock_full')).toBe(look('stock_total'));
        const notes = [...scroller.querySelectorAll('tbody td span')].filter((el) => el.textContent === 'Sin stock ERP');
        expect(notes.length).toBeGreaterThan(0);
        expect(wrapped(notes)).toEqual([]);
        expect(overflowingCells(scroller)).toEqual([]);
        await expect.element(screen.getByRole('button', { name: /Sin stock ERP/ })).toBeVisible();
        expect([...document.querySelectorAll('button')].some((b) => /Sin stock propio/.test(b.textContent))).toBe(false);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the grouped header reads like Métricas ML and stays pinned above the rows`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        const groups = [...scroller.querySelectorAll('thead th[scope="colgroup"]')];
        // The sales right after Precio: Productos' price columns live in the Precios view (owner, 2026-10-28).
        expect(groups.map((th) => th.textContent)).toEqual(['Ventas (unidades)', 'Resultado financiero', 'Rotación', 'Stock']);
        for (const th of groups) {
          expect(getComputedStyle(th).textAlign).toBe('center');
          expect(getComputedStyle(th).textTransform).toBe('uppercase');
          expect(getComputedStyle(th).backgroundColor).toBe(tokenColor('--metricas-head-bg'));
        }
        // Each group opens with a divider down to the last row.
        const lastRow = [...scroller.querySelectorAll('tbody tr')].at(-1);
        const opening = lastRow.querySelector('td[data-column="unidades_7d"]');
        expect(getComputedStyle(opening).borderLeftColor).toBe(tokenColor('--ventas-divider'));
        expect(getComputedStyle(opening).borderLeftWidth).toBe('1px');
        // Scrolled down, the group row and the leaf row both stay on top, in that order.
        scroller.scrollTo({ top: 400, left: 0 });
        await frame();
        const ventas = rect(groups[0]);
        const leaf = rect(scroller.querySelector('thead th[data-column="unidades_7d"]'));
        expect(Math.abs(ventas.top - rect(scroller).top)).toBeLessThanOrEqual(2);
        expect(Math.abs(leaf.top - ventas.bottom)).toBeLessThanOrEqual(2);
        // The title spans both header rows.
        const title = scroller.querySelector('thead th[data-column="titulo"]');
        expect(title.rowSpan).toBe(2);
        expect(Math.abs(rect(title).bottom - leaf.bottom)).toBeLessThanOrEqual(2);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: Métricas' figures, money and sparklines stay on one line inside their cells`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        const money = [...scroller.querySelectorAll('tbody [data-money]')];
        expect(money.length).toBeGreaterThan(0);
        expect(wrapped(money)).toEqual([]);
        const sparks = scroller.querySelectorAll('tbody td[data-column="units_trend"] svg');
        expect(sparks.length).toBeGreaterThan(0);
        const lastSales = [...scroller.querySelectorAll('tbody td[data-column="last_sale"] span')];
        expect(wrapped(lastSales)).toEqual([]);
        expect(overflowingCells(scroller)).toEqual([]);
        // The store and the link sit inside the Publicación cell, not in columns of their own.
        expect(scroller.querySelector('thead th[data-column="tienda"]')).toBeNull();
        expect(scroller.querySelector('thead th[data-column="vinculo"]')).toBeNull();
        await expect.element(screen.getByLabelText('Tienda: TP-Link').first()).toBeVisible();
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the state banner uses the theme's tone tokens`, async () => {
        const screen = await renderPage({ width, height, theme });
        const banner = document.querySelector('[role="status"][data-tone="warning"]');
        expect(banner).not.toBeNull();
        expect(getComputedStyle(banner).color).toBe(tokenColor('--tone-warning-fg'));
        expect(getComputedStyle(banner).backgroundColor).toBe(tokenColor('--tone-warning-bg'));
        expect(rect(banner).right).toBeLessThanOrEqual(width);
        screen.unmount();
      });
    }
  }
});

// Publicaciones with markup and an expanded row (publicaciones-ml-vista P11b.T4).
const MARGIN_ITEMS = [
  VARIATION_ITEM,
  ...MANY.slice(0, 30).map((item, i) => ({
    ...item,
    item_id: `MLA${1100000200 + i}`,
    markup: { min: 8.5, max: 21, worst: 8.5, any_negative: false, reason: 'ok', partial: 0, ads: null },
  })),
];
const MARGIN_RESPONSE = { ...RESPONSE, can_see_margin: true, items: MARGIN_ITEMS };

const renderMarginPage = async ({ width, height, theme, entry = '/ml-publicaciones', response = MARGIN_RESPONSE }) => {
  canSeeMargin = true;
  publicacionesMlAPI.items.mockResolvedValue({ data: response });
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
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
  await expect.element(screen.getByText('MLA1100000005')).toBeVisible();
  return screen;
};

describe('Publicaciones ML with markup and an expanded row (visual)', () => {
  beforeEach(() => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.variations.mockReset();
  });

  for (const { width, height } of VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: MARKUP's columns and its filters fit, "Actual" sortable on one line`, async () => {
        const screen = await renderMarginPage({ width, height, theme });
        const scroller = scrollerOf();
        const group = [...scroller.querySelectorAll('thead th[scope="colgroup"]')].find((th) => th.textContent === 'Markup');
        expect(group.colSpan).toBe(3);
        const header = scroller.querySelector('thead th[data-column="markup"]');
        expect(header.textContent).toBe('Actual');
        expect(wrapped([header.querySelector('button')])).toEqual([]);
        expect(scroller.querySelectorAll('tbody td[data-column="markup_trend"] svg').length).toBeGreaterThan(0);
        // The range sits on one line and inside its cell.
        const ranges = [...scroller.querySelectorAll('tbody td[data-align] span')].filter((el) => /%/.test(el.textContent) && !/parcial/.test(el.textContent));
        expect(ranges.length).toBeGreaterThan(0);
        expect(wrapped(ranges)).toEqual([]);
        expect(overflowingCells(scroller)).toEqual([]);
        // Filters: the new band stays inside the card.
        const band = [...document.querySelectorAll('div[class*="filterBand"]')].find((el) => el.textContent.includes('Markup:'));
        expect(band).toBeDefined();
        expect(band.scrollWidth).toBeLessThanOrEqual(band.clientWidth + 1);
        expect(rect(band).right).toBeLessThanOrEqual(width);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the clásica "markup con offsets" sits under its markup, on one line, inside the cell`, async () => {
        offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [{ id: 1, tipo_offset: 'porcentaje_costo', porcentaje: 10, marca: 'TP-LINK' }] });
        preciosAPI.tipoCambioActual.mockResolvedValue({ data: { venta: 1000 } });
        try {
          const screen = await renderMarginPage({ width, height, theme, entry: PRECIOS });
          await expect.element(screen.getByTitle('Markup con offsets aplicados').first()).toBeVisible();
          const scroller = scrollerOf();
          const lines = [...scroller.querySelectorAll('[title="Markup con offsets aplicados"]')];
          expect(lines.length).toBeGreaterThan(0);
          expect(lines[0].textContent).toMatch(/^→ [-\d.,]+%$/);
          expect(wrapped(lines)).toEqual([]);
          expect(overflowingCells(scroller)).toEqual([]);
          screen.unmount();
        } finally {
          offsetsGananciaAPI.vigentes.mockImplementation(() => new Promise(() => {}));
          preciosAPI.tipoCambioActual.mockImplementation(() => new Promise(() => {}));
        }
      });

      it(`${width}x${height} ${theme}: an expanded row shows its variations under it, inside the scroller, nothing poking out`, async () => {
        const screen = await renderMarginPage({ width, height, theme });
        await screen.getByRole('button', { name: /variaciones de MLA1100000005/ }).click();
        await expect.element(screen.getByText('Variación 9002')).toBeVisible();
        const scroller = scrollerOf();
        const rows = [...scroller.querySelectorAll('tbody tr')];
        const parent = rows.findIndex((row) => row.textContent.includes('MLA1100000005'));
        const subRows = rows.slice(parent + 1, parent + 4);
        expect(subRows.map((row) => row.textContent.match(/Variación (\d+)/)?.[1])).toEqual(['9001', '9002', '9003']);
        // Sub-rows are indented one level inside the pinned column, and fit their cells.
        const parentPinned = rows[parent].querySelector('td[data-pinned]');
        const subPinned = subRows[0].querySelector('td[data-pinned]');
        expect(Number.parseFloat(getComputedStyle(subPinned).paddingLeft)).toBeGreaterThan(Number.parseFloat(getComputedStyle(parentPinned).paddingLeft) - 1);
        expect(overflowingCells(scroller)).toEqual([]);
        expect(rect(scroller).right).toBeLessThanOrEqual(width + 0.5);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        // SKU/EAN, cost and markup are on one line each.
        const figures = subRows.flatMap((row) => [...row.querySelectorAll('td[data-align] span')]).filter((el) => /^[-\d.,%]+$/.test(el.textContent.trim()));
        expect(figures.length).toBeGreaterThan(0);
        expect(wrapped(figures)).toEqual([]);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the negative variation is tinted with the danger tone, the others are not`, async () => {
        const screen = await renderMarginPage({ width, height, theme });
        await screen.getByRole('button', { name: /variaciones de MLA1100000005/ }).click();
        await expect.element(screen.getByText('Variación 9002')).toBeVisible();
        const scroller = scrollerOf();
        const row = (id) => [...scroller.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(`Variación ${id}`));
        const cellColor = (id) => getComputedStyle(row(id).querySelectorAll('td')[2]).backgroundColor;
        expect(cellColor(9002)).toBe(tokenColor('--tone-danger-bg'));
        expect(cellColor(9001)).not.toBe(tokenColor('--tone-danger-bg'));
        const negative = [...row(9002).querySelectorAll('span')].find((el) => el.textContent === '-4,2%');
        expect(getComputedStyle(negative).color).toBe(tokenColor('--tone-danger-fg'));
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the sub-rows' pinned cell stays on the left edge while the table scrolls sideways`, async () => {
        const screen = await renderMarginPage({ width, height, theme });
        await screen.getByRole('button', { name: /variaciones de MLA1100000005/ }).click();
        await expect.element(screen.getByText('Variación 9002')).toBeVisible();
        const scroller = scrollerOf();
        scroller.scrollTo({ top: 0, left: 160 });
        await frame();
        const subPinned = [...scroller.querySelectorAll('tbody tr')]
          .find((tr) => tr.textContent.includes('Variación 9001'))
          .querySelector('td[data-pinned]');
        expect(Math.abs(rect(subPinned).left - rect(scroller).left)).toBeLessThanOrEqual(2);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: loading and error states of an expanded row stay inside the table`, async () => {
        const screen = await renderMarginPage({ width, height, theme });
        publicacionesMlAPI.variations.mockRejectedValue(Object.assign(new Error('boom'), { response: { status: 500 } }));
        await screen.getByRole('button', { name: /variaciones de MLA1100000005/ }).click();
        await expect.element(screen.getByText('No se pudieron cargar las variaciones.')).toBeVisible();
        const alert = document.querySelector('[role="alert"]');
        expect(rect(alert).right).toBeLessThanOrEqual(rect(scrollerOf()).right + 0.5);
        expect(getComputedStyle(alert).color).toBe(tokenColor('--cf-text-secondary'));
        screen.unmount();
      });
    }
  }
});

// The Agrupado tree (publicaciones-ml-vista P12a.T3): brand > category > subcategory > product > MLA.
// Its Tipo and Estado are the owner's own row (2026-11-12): five kinds and three states.
const CATEGORY = makeNode({
  kind: 'categoria',
  key: 'ROUTERS',
  label: 'ROUTERS',
  count: 137,
  params: { marcas: 'TP-LINK', categorias: 'ROUTERS' },
  negative_count: 4,
  markup_min: -6.5,
  markup_max: 38.2,
  kind_counts: { clasica: 33, cuotas_3: 30, cuotas_6: 26, cuotas_9: 24, cuotas_12: 24 },
  status_counts: { active: 111, under_review: 7, closed: 19 },
});
const SUBCATEGORY = makeNode({
  kind: 'subcategoria',
  key: '55',
  label: 'Routers WiFi',
  count: 90,
  params: { marcas: 'TP-LINK', categorias: 'ROUTERS', subcategorias: '55' },
  negative_count: 4,
  markup_min: -6.5,
  markup_max: 38.2,
});
// 250 brands in total so "Ver más" is on screen.
const MANY_BRANDS = [
  ...BRAND_NODES,
  ...Array.from({ length: 96 }, (_, i) => makeNode({ key: `MARCA${i}`, label: `MARCA ${i}`, count: 3, params: { marcas: `MARCA${i}` }, negative_count: 0, markup_min: 10, markup_max: 20 })),
];
const TREE = {
  '': groupsResponse('marca', MANY_BRANDS, { total: 250 }),
  'TP-LINK': groupsResponse('categoria', [CATEGORY]),
  'TP-LINK,ROUTERS': groupsResponse('subcategoria', [SUBCATEGORY]),
  'TP-LINK,ROUTERS,55': groupsResponse('producto', PRODUCT_NODES),
};

const renderTree = async ({ width, height, theme }) => {
  canSeeMargin = true;
  publicacionesMlAPI.items.mockResolvedValue({ data: { ...MARGIN_RESPONSE, items: MARGIN_ITEMS.slice(0, 3), total: 3 } });
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
  publicacionesMlAPI.groups.mockImplementation(({ path = '' }) => Promise.resolve({ data: TREE[path] }));
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  window.scrollTo(0, 0);
  const screen = await render(
    <MemoryRouter initialEntries={['/ml-publicaciones?vista=agrupado']}>
      <Shell>
        <PublicacionesML />
      </Shell>
    </MemoryRouter>,
  );
  await expect.element(screen.getByText('EPSON')).toBeVisible();
  return screen;
};

const openNode = async (screen, name) => {
  await screen.getByRole('button', { name }).click();
};

const openToLeaf = async (screen) => {
  await openNode(screen, /Abrir TP-LINK/);
  await openNode(screen, /Abrir ROUTERS/);
  await openNode(screen, /Abrir Routers WiFi/);
  await openNode(screen, /Abrir Router Archer AX55/);
  await expect.element(screen.getByText('Router TP-Link Archer AX55 por color')).toBeVisible();
};

const pinnedPadding = (row) => Number.parseFloat(getComputedStyle(row.querySelector('td[data-pinned]')).paddingLeft);
const rowWith = (scroller, text) => [...scroller.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(text));

describe('Publicaciones ML Agrupado tree (visual)', () => {
  beforeEach(() => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.variations.mockReset();
    publicacionesMlAPI.groups.mockReset();
  });

  for (const theme of THEMES) {
    const width = 1366;
    const height = 768;

    it(`${width}x${height} ${theme}: the tree fits the screen, the header controls included`, async () => {
      const screen = await renderTree({ width, height, theme });
      const scroller = scrollerOf();
      expect(rect(scroller).right).toBeLessThanOrEqual(width + 0.5);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      expect(getComputedStyle(scroller).backgroundColor).toBe(tokenColor('--cf-bg-card'));
      for (const control of document.querySelectorAll('header button, header [role="switch"]')) {
        expect(rect(control).right, control.textContent).toBeLessThanOrEqual(width);
      }
      // The markup filters are not offered in the tree; the store stays in the filter bar.
      expect(document.body.textContent).not.toContain('Markup:');
      expect(document.body.textContent).toContain('Tienda:');
      screen.unmount();
    });

    it(`${width}x${height} ${theme}: node figures stay on one line, negatives take the danger tone, nothing pokes out`, async () => {
      const screen = await renderTree({ width, height, theme });
      const scroller = scrollerOf();
      const figures = [...scroller.querySelectorAll('tbody td[data-align] span')].filter((el) => /^[-\d.,%\s–—]+$/.test(el.textContent.trim()));
      expect(figures.length).toBeGreaterThan(0);
      expect(wrapped(figures)).toEqual([]);
      expect(overflowingCells(scroller)).toEqual([]);
      // S6: the count and the negatives are the first cell's second line; no column is left for them.
      const negatives = [...rowWith(scroller, 'TP-LINK').querySelectorAll('td[data-pinned] span')].find((el) => el.textContent === '4 con markup negativo');
      expect(getComputedStyle(negatives).color).toBe(tokenColor('--tone-danger-fg'));
      expect(rowWith(scroller, 'TP-LINK').querySelector('td[data-pinned]').textContent).toContain('90 publicaciones');
      expect(rowWith(scroller, 'EPSON').textContent).not.toContain('markup negativo');
      expect(scroller.querySelector('thead th[data-column="publicaciones"], thead th[data-column="negativos"]')).toBeNull();
      screen.unmount();
    });

    // Owner (2026-11-12): "elijo filas finas y las filas son gigantes por eso ... pones badges y achicá los renglones".
    for (const [w, h, dense] of [[width, height, false], [width, height, true], [1440, 900, false], [1440, 900, true]]) {
      it(`${w}x${h} ${theme}${dense ? ', filas finas' : ''}: a node sums up Tipo and Estado in compact badges, never taller than its title`, async () => {
        if (dense) localStorage.setItem('publicaciones-ml.filas-finas', 'true');
        try {
          const screen = await renderTree({ width: w, height: h, theme });
          await openToLeaf(screen);
          const scroller = scrollerOf();
          expect(scroller.closest('[data-density]').dataset.density).toBe(dense ? 'dense' : 'normal');
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/arbol-badges-${w}-${theme}${dense ? '-finas' : ''}.png` });
          const cell = (row, key) => row.querySelector(`td[data-column="${key}"]`);
          const names = (row, key) => [...cell(row, key).querySelectorAll('[data-summary-chip]')].map((chip) => chip.getAttribute('title'));
          for (const label of ['TP-LINK', 'ROUTERS', 'Routers WiFi', 'Router Archer AX55']) {
            const row = rowWith(scroller, label);
            expect(names(row, 'tipo').join('|'), label).toMatch(/\d+ Clásica/);
            expect(cell(row, 'tipo').textContent, label).toMatch(/^C \d+/);
            expect(names(row, 'estado').join('|'), label).toMatch(/\d+ activas?/);
            expect(cell(row, 'precio').textContent, label).toMatch(/^[\d.,]+( –[\d.,]+)?$/);
            // S3: the badges never make the row taller than its title cell does.
            const title = cell(row, 'titulo') ?? row.querySelector('td[data-pinned]');
            const titleContent = title.firstElementChild;
            for (const key of ['tipo', 'estado']) {
              expect(rect(cell(row, key).firstElementChild).height, `${label} ${key}`).toBeLessThanOrEqual(rect(titleContent).height + 0.5);
            }
          }
          const tpLink = rowWith(scroller, 'TP-LINK');
          expect(names(tpLink, 'estado')).toEqual(['89 activas', '1 pausada']);
          expect(cell(tpLink, 'estado').textContent).toBe('891');
          const routers = rowWith(scroller, 'ROUTERS');
          // Real margin for a wider fallback font (CI's Chromium has DejaVu, ~8% wider): the owner's five kinds and three
          // states take at most 85% of their cell's content box, so they stay on one line there too.
          for (const key of ['tipo', 'estado']) {
            const td = cell(routers, key);
            const chipsOf = [...td.querySelectorAll('[data-summary-chip]')];
            const used = rect(chipsOf.at(-1)).right - rect(chipsOf[0]).left;
            const style = getComputedStyle(td);
            const room = td.clientWidth - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight);
            expect(used, `ROUTERS ${key}`).toBeLessThanOrEqual(room * 0.85);
          }
          expect(cell(routers, 'tipo').textContent).toBe('C 333 306 269 2412 24');
          expect(names(routers, 'estado')).toEqual(['111 activas', '7 en revisión', '19 cerradas']);
          // Every badge on one line, inside its cell.
          expect(wrapped(scroller.querySelectorAll('[data-summary-chip]'))).toEqual([]);
          expect(overflowingCells(scroller)).toEqual([]);
          expect(cell(rowWith(scroller, 'Router TP-Link Archer AX55 por color'), 'tipo').querySelector('[data-summary-chip]')).toBeNull();
          if (dense) {
            // "Filas finas": a parent row is as thin as a publication row; its second line is cut, whole in its tooltip.
            const note = rowWith(scroller, 'Router Archer AX55').querySelector('td[data-pinned] [data-node-note]');
            expect(note.getAttribute('title')).toBe('Producto · ARCHER-AX55 · 3 publicaciones · 1 con markup negativo');
            const leaf = rect(rowWith(scroller, 'Router TP-Link Archer AX55 por color')).height;
            for (const label of ['TP-LINK', 'ROUTERS', 'Routers WiFi', 'Router Archer AX55']) {
              expect(rect(rowWith(scroller, label)).height, label).toBeLessThanOrEqual(leaf + 0.5);
            }
          }
          screen.unmount();
        } finally {
          localStorage.removeItem('publicaciones-ml.filas-finas');
        }
      });
    }

    it(`${width}x${height} ${theme}: each level sits deeper than its parent and the pinned cell stays on the left edge`, async () => {
      const screen = await renderTree({ width, height, theme });
      await openToLeaf(screen);
      const scroller = scrollerOf();
      const depths = ['TP-LINK', 'ROUTERS', 'Routers WiFi', 'Router Archer AX55', 'Router TP-Link Archer AX55 por color'].map((text) =>
        pinnedPadding(rowWith(scroller, text)),
      );
      for (let i = 1; i < depths.length; i += 1) expect(depths[i]).toBeGreaterThan(depths[i - 1]);
      scroller.scrollTo({ top: 0, left: 160 });
      await frame();
      const pinned = rowWith(scroller, 'Router TP-Link Archer AX55 por color').querySelector('td[data-pinned]');
      expect(Math.abs(rect(pinned).left - rect(scroller).left)).toBeLessThanOrEqual(2);
      expect(overflowingCells(scroller)).toEqual([]);
      screen.unmount();
    });

    it(`${width}x${height} ${theme}: a leaf publication keeps its variation sub-rows, one level deeper`, async () => {
      const screen = await renderTree({ width, height, theme });
      await openToLeaf(screen);
      await screen.getByRole('button', { name: /variaciones de MLA1100000005/ }).click();
      await expect.element(screen.getByText('Variación 9002')).toBeVisible();
      const scroller = scrollerOf();
      expect(pinnedPadding(rowWith(scroller, 'Variación 9001'))).toBeGreaterThan(pinnedPadding(rowWith(scroller, 'Router TP-Link Archer AX55 por color')));
      expect(overflowingCells(scroller)).toEqual([]);
      screen.unmount();
    });

    it(`${width}x${height} ${theme}: the loading or error row of a leaf's variations is indented under its publication`, async () => {
      const screen = await renderTree({ width, height, theme });
      await openToLeaf(screen);
      publicacionesMlAPI.variations.mockRejectedValue(Object.assign(new Error('boom'), { response: { status: 500 } }));
      await screen.getByRole('button', { name: /variaciones de MLA1100000005/ }).click();
      await expect.element(screen.getByText('No se pudieron cargar las variaciones.')).toBeVisible();
      const scroller = scrollerOf();
      // The parent's toggle starts at its depth; the state starts one level in, like the variations' own rows.
      const toggle = rowWith(scroller, 'Router TP-Link Archer AX55 por color').querySelector('td[data-pinned] button');
      const step = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--table-shell-indent'));
      const alertLeft = rect(document.querySelector('tbody [role="alert"]')).left;
      expect(Math.abs(alertLeft - (rect(toggle).left + step))).toBeLessThanOrEqual(2);
      screen.unmount();
    });

    it(`${width}x${height} ${theme}: "Ver más" and "Sin producto" sit inside the table, in view of the scroller`, async () => {
      const screen = await renderTree({ width, height, theme });
      const scroller = scrollerOf();
      const more = [...scroller.querySelectorAll('button')].find((button) => /Ver más/.test(button.textContent));
      expect(more).toBeDefined();
      more.scrollIntoView({ block: 'center' });
      await frame();
      expect(rect(more).right).toBeLessThanOrEqual(rect(scroller).right + 0.5);
      expect(rect(more).left).toBeGreaterThanOrEqual(rect(scroller).left - 0.5);
      // The label is one line (a button's own height includes its padding, so the text is measured).
      const label = document.createRange();
      label.selectNodeContents(more);
      expect(label.getClientRects().length).toBe(1);
      screen.unmount();
    });

    it(`${width}x${height} ${theme}: the error row of a level stays inside the table, with its retry`, async () => {
      const screen = await renderTree({ width, height, theme });
      publicacionesMlAPI.groups.mockRejectedValueOnce(Object.assign(new Error('boom'), { response: { status: 503 } }));
      await openNode(screen, /Abrir EPSON/);
      await expect.element(screen.getByText(/La consulta tardó demasiado/)).toBeVisible();
      const alert = document.querySelector('tbody [role="alert"]');
      expect(rect(alert).right).toBeLessThanOrEqual(rect(scrollerOf()).right + 0.5);
      expect(getComputedStyle(alert).color).toBe(tokenColor('--cf-text-secondary'));
      screen.unmount();
    });
  }
});

// A product's panel opens on Precios (owner, 2026-11-02): these tests read its Resumen, so they open it first.
const openProductTab = async (screen, name) => {
  await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
  await screen.getByRole('complementary', { name: 'Detalle del producto' }).getByRole('tab', { name }).click();
};
const openProductResumen = (screen) => openProductTab(screen, 'Resumen');

const renderProducts = async ({ width, height, theme, rows, entry = '/ml-publicaciones?vista=producto' }) => {
  canSeeMargin = true;
  publicacionesMlAPI.items.mockResolvedValue({ data: { ...MARGIN_RESPONSE, items: MARGIN_ITEMS.slice(0, 3), total: 130 } });
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
  publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse(rows, { total: 1234, sin_mla_count: 12345 }) });
  publicacionesMlAPI.stats.mockResolvedValueOnce({
    data: {
      stats: {
        total: 1234, con_stock: 900, con_precio: 1100, con_stock_sin_precio: 30, nuevos: 12, nuevos_sin_precio: 4, oferta_sin_rebate: 9,
        sin_mla: 12345, sin_mla_con_stock: 10234, sin_mla_sin_stock: 2111, sin_mla_nuevos: 87,
        markup_negativo_clasica: 15, markup_negativo_rebate: 2, markup_negativo_oferta: 0, markup_negativo_web: 7,
      },
      can_see_margin: true,
    },
  });
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
  await expect.element(screen.getByText('Router Archer AX55')).toBeVisible();
  return screen;
};

// Screenshots of the product panel only with `VITE_PUBLICACIONES_SHOTS_DIR` (checked by hand, never committed).
const PRODUCT_SHOTS_DIR = import.meta.env.VITE_PUBLICACIONES_SHOTS_DIR;

// The shipping-cost options of RE200 (S7b): its production costs (MLA1173065146 = 7290, MLA2517958828 = 10890, one
// publication at 8290 whose id is unknown); the other ids, the units and the 9450 cost are synthetic. Ponderado stored.
const ENVIO_OPTIONS = {
  item_id: 4101,
  date_from: '2026-10-13',
  date_to: '2026-11-11',
  publicaciones: [
    { mla: 'MLA1173065146', costo: 7290, unidades: 42, mas_vendida: true, tipo: 'gold_special', logistica: 'drop_off' },
    { mla: 'MLA_A', costo: 8290, unidades: 18, mas_vendida: false, tipo: 'gold_pro', logistica: 'drop_off' },
    { mla: 'MLA_B', costo: 9450, unidades: 6, mas_vendida: false, tipo: 'gold_special', logistica: 'self_service' },
    { mla: 'MLA2517958828', costo: 10890, unidades: 4, mas_vendida: false, tipo: 'gold_special', logistica: 'cross_docking' },
    { mla: 'MLA_C', costo: null, unidades: 0, mas_vendida: false, tipo: 'gold_pro', logistica: 'fulfillment' },
  ],
  promedio: 8980,
  ponderado: 7938, // (7290·42 + 8290·18 + 9450·6 + 10890·4) / 70: the visible rows weighted
  max: 10890,
  eleccion: {
    modo: 'ponderado', mla: null, costo: 7938, warning: null, usuario_id: 7, usuario_nombre: 'Ana Pérez', updated_at: '2026-11-10T16:42:00',
  },
};

describe('Publicaciones ML Producto view (visual)', () => {
  beforeEach(() => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.variations.mockReset();
    publicacionesMlAPI.products.mockReset();
  });

  for (const theme of THEMES) {
    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product table fits the screen, the view picker and the pager included`, async () => {
        const screen = await renderProducts({ width, height, theme });
        const scroller = scrollerOf();
        expect(rect(scroller).right).toBeLessThanOrEqual(width + 0.5);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        expect(getComputedStyle(scroller).backgroundColor).toBe(tokenColor('--cf-bg-card'));
        for (const control of document.querySelectorAll('header button')) {
          expect(rect(control).right, control.textContent).toBeLessThanOrEqual(width);
        }
        await expect.element(screen.getByText(/de 1234 productos/)).toBeVisible();
        // Productos' Sin MLA card (S12d4c), with five-digit counts, keeps each figure on one line inside its card.
        const sinMla = screen.getByRole('group', { name: 'Sin MLA' }).element();
        await expect.element(screen.getByRole('button', { name: 'Total: 12.345' })).toBeVisible();
        expect(rect(sinMla).right).toBeLessThanOrEqual(width);
        expect(wrapped([...sinMla.querySelectorAll('button span')])).toEqual([]);
        for (const button of sinMla.querySelectorAll('button')) {
          expect(rect(button).right, button.getAttribute('aria-label')).toBeLessThanOrEqual(rect(sinMla).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/products-header-${width}-${theme}.png` });
        expect(document.body.textContent).not.toContain('Markup:');
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: a sort by several columns numbers each header, arrow and number on one line`, async () => {
        const entry = '/ml-publicaciones?vista=producto&orden=unidades_7d,titulo,facturado_30d&dir=desc,asc,desc';
        const screen = await renderProducts({ width, height, theme, entry });
        const marks = [...document.querySelectorAll('thead [data-testid="sort-order"]')];
        const order = Object.fromEntries(marks.map((mark) => [mark.closest('th').dataset.column, mark.textContent]));
        expect(order).toEqual({ unidades_7d: '1', titulo: '2', facturado_30d: '3' });
        const buttons = marks.map((mark) => mark.closest('button'));
        expect(wrapped(buttons)).toEqual([]);
        for (const button of buttons) {
          const cell = button.closest('th');
          expect(rect(button).right, button.textContent).toBeLessThanOrEqual(rect(cell).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) {
          const path = `${PRODUCT_SHOTS_DIR}/products-multisort-${width}-${theme}.png`;
          await page.screenshot({ path, element: document.querySelector('thead') });
        }
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: a product's figures, money and sparklines stay on one line inside their cells`, async () => {
        const screen = await renderProducts({ width, height, theme });
        const scroller = scrollerOf();
        const figures = [...scroller.querySelectorAll('tbody td[data-align] span')].filter((el) => el.textContent.trim());
        expect(figures.length).toBeGreaterThan(0);
        expect(wrapped(figures)).toEqual([]);
        expect(overflowingCells(scroller)).toEqual([]);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: a product row says its publications and summarizes them in Tipo, Estado and Precio`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await screen.getByRole('button', { name: /Abrir Router Archer AX55/ }).click();
        await expect.element(screen.getByText('Router TP-Link Archer AX55 por color')).toBeVisible();
        const scroller = scrollerOf();
        const row = rowWith(scroller, 'Router Archer AX55');
        const cell = (key) => row.querySelector(`td[data-column="${key}"]`);
        expect(cell('titulo').textContent).toContain('3 publicaciones');
        const names = (key) => [...cell(key).querySelectorAll('[data-summary-chip]')].map((chip) => chip.getAttribute('title'));
        expect(cell('tipo').textContent).toBe('C 26 1');
        expect(names('tipo')).toEqual(['2 Clásica', '1 6 cuotas']);
        expect(names('estado')).toEqual(['2 activas', '1 pausada']);
        expect(cell('precio').textContent).toBe('45.999,00 –189.999,50');
        expect(scroller.querySelector('thead th[data-column="publicaciones"]')).toBeNull();
        // The summary badges sit on one line inside their cell; the opened publications keep the list's own cells.
        expect(wrapped(scroller.querySelectorAll('[data-summary-chip]'))).toEqual([]);
        for (const key of ['tipo', 'estado']) {
          const chips = [...cell(key).querySelectorAll('[data-summary-chip]')];
          expect(new Set(chips.map((chip) => Math.round(rect(chip).top))).size, key).toBe(1);
        }
        expect(overflowingCells(scroller)).toEqual([]);
        const publication = rowWith(scroller, 'Router TP-Link Archer AX55 por color');
        expect(publication.querySelector('td[data-column="tipo"] [data-summary-chip]')).toBeNull();
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: a product row fills its code, brand, cost and ERP stock inside their cells`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await screen.getByRole('button', { name: 'Columnas' }).click();
        for (const name of ['Código', 'Marca', 'Costo']) await screen.getByRole('checkbox', { name }).click();
        await screen.getByRole('button', { name: 'Columnas' }).click();
        const row = rowWith(scrollerOf(), 'Router Archer AX55');
        for (const text of ['TP-LINK', 'USD 45,50', '12']) {
          expect([...row.querySelectorAll('td')].some((cell) => cell.textContent.trim() === text), text).toBe(true);
        }
        expect(overflowingCells(scrollerOf())).toEqual([]);
        if (PRODUCT_SHOTS_DIR) {
          [...row.querySelectorAll('td')].find((cell) => cell.textContent.trim() === 'USD 45,50').scrollIntoView({ inline: 'center' });
          await frame();
          await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-rows-fields-${width}-${theme}.png` });
        }
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the cost cell of a product row is one line, as tall as a row without sell in (S10b)`, async () => {
        const showCost = async (screen) => {
          await screen.getByRole('button', { name: 'Columnas' }).click();
          await screen.getByRole('checkbox', { name: 'Costo' }).click();
          await screen.getByRole('button', { name: 'Columnas' }).click();
        };
        // The same row without PPP nor sell in first: the height the cost cell must not add to.
        const plain = await renderProducts({ width, height, theme, rows: PRODUCT_ROWS });
        await showCost(plain);
        const plainHeight = rowWith(scrollerOf(), 'Router Archer AX55').getBoundingClientRect().height;
        plain.unmount();

        const rows = [{ ...PRODUCT_ROWS[0], ...COST_LINES }, ...PRODUCT_ROWS.slice(1)];
        const screen = await renderProducts({ width, height, theme, rows });
        await showCost(screen);
        const row = rowWith(scrollerOf(), 'Router Archer AX55');
        const cell = [...row.querySelectorAll('td')].find((td) => td.textContent.includes('USD 45,50'));
        // The owner's case: a USD cost, its cost with sell in in USD too, inline; the PPP and pesos in the tooltip.
        expect(cell.textContent).toBe('USD 45,50 c/ sell in USD 43,27');
        // The whole line shows: the cell is as wide as its content, no ellipsis cuts the cost with sell in.
        const content = cell.firstElementChild.getBoundingClientRect();
        const box = cell.getBoundingClientRect();
        const padding = parseFloat(getComputedStyle(cell).paddingLeft);
        expect(content.left).toBeGreaterThanOrEqual(box.left + padding - 0.5);
        expect(content.right).toBeLessThanOrEqual(box.right - padding + 0.5);
        expect(cell.querySelector('[title]').getAttribute('title')).toContain('ppp: USD $41.20');
        expect(row.getBoundingClientRect().height).toBeCloseTo(plainHeight, 0);
        expect(overflowingCells(scrollerOf())).toEqual([]);
        if (PRODUCT_SHOTS_DIR) {
          cell.scrollIntoView({ inline: 'center' });
          await frame();
          await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-rows-cost-lines-${width}-${theme}.png` });
        }
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: a click on a product opens its panel beside the table, its figures and publications inside it`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await openProductResumen(screen);
        await expect.element(screen.getByRole('complementary', { name: 'Detalle del producto' }).getByText('Cifras')).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        // The product's publications are Productos' tree; a publication with nothing under it has only its "Abrir".
        await expect.element(screen.getByRole('button', { name: 'Abrir MLA1100000005' })).toBeVisible();
        expect(screen.getByRole('button', { name: 'Expandir Router TP-Link Archer AX55 por color' }).query()).toBeNull();
        const box = rect(panel);
        const scroller = scrollerOf();
        // Side by side: the table ends where the panel starts, and nothing scrolls the page sideways.
        expect(rect(scroller).right).toBeLessThanOrEqual(box.left + 0.5);
        expect(box.right).toBeLessThanOrEqual(width + 0.5);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        for (const el of panel.querySelectorAll('*')) {
          const r = el.getBoundingClientRect();
          if (r.width === 0) continue;
          expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(box.right + 0.5);
        }
        // Every piece of text keeps to one line. A value may stack two of them on purpose (the last sale's date over
        // "hace N días", a header figure over its note), so each innermost element is measured, not the whole <dd>.
        const figures = [...panel.querySelectorAll('dd')]
          .flatMap((dd) => (dd.children.length === 0 ? [dd] : [...dd.querySelectorAll('*')].filter((el) => el.children.length === 0)))
          .filter((el) => el.textContent.trim());
        expect(figures.length).toBeGreaterThan(0);
        expect(wrapped(figures)).toEqual([]);
        // The product row is the highlighted one, and it was not expanded.
        expect(rowWith(scroller, 'Router Archer AX55').getAttribute('aria-current')).toBe('true');
        expect(scroller.textContent).not.toContain('Router TP-Link Archer AX55 por color');
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product's SKU and EAN, and their edit, fit inside the panel`, async () => {
        productosPropiosAPI.get.mockResolvedValueOnce({
          data: {
            item_id: 4101,
            codigo: '6935364099589',
            descripcion: 'Router Archer AX55',
            ean: '6935364099589',
            ean_manual: true,
            sku: null,
            sku_manual: false,
            sku_candidatos: ['ARCHER-AX55', 'ARCHER-AX55-V2'],
            can_edit: true,
            datos: {
              fuente_mla: 'MLA1100000001',
              titulo: 'Router TP-Link Archer AX55 Wi-Fi 6 Dual Band 3000 Mbps',
              descripcion: 'Router Wi-Fi 6 de doble banda.\nHasta 3000 Mbps, con OneMesh y 4 antenas de alta ganancia que cubren toda la casa sin cortes.',
              fotos: [1, 2, 3, 4, 5, 6, 7].map((n) => ({ id: `P${n}`, url: `data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>` })),
              atributos: [
                { id: 'BRAND', name: 'Marca', value_name: 'TP-Link' },
                { id: 'MODEL', name: 'Modelo', value_name: 'Archer AX55' },
                { id: 'WIFI', name: 'Estándares Wi-Fi compatibles', value_name: '802.11 a/b/g/n/ac/ax' },
              ],
              copiado_at: '2026-10-26T15:00:00Z',
            },
          },
        });
        const screen = await renderProducts({ width, height, theme });
        await openProductResumen(screen);
        const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
        await expect.element(aside.getByText('Las publicaciones tienen SKUs distintos: ARCHER-AX55, ARCHER-AX55-V2')).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-identity-${width}-${theme}.png` });
        // The copied data: the pictures' grid and the description stay inside the panel.
        const data = document.querySelector('section[aria-labelledby] img')?.closest('section');
        expect(data, 'the copied data section with its pictures').not.toBeNull();
        data.scrollIntoView();
        for (const el of data.querySelectorAll('img, p, dd')) {
          expect(rect(el).right, el.tagName).toBeLessThanOrEqual(rect(panel).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-data-${width}-${theme}.png` });
        // Editing the copy: every field and button of the form stays inside the panel.
        await aside.getByRole('button', { name: 'Editar datos' }).click();
        await expect.element(aside.getByLabelText('Título')).toBeVisible();
        const form = aside.getByLabelText('Título').element().closest('form');
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        for (const control of form.querySelectorAll('input, textarea, button, img')) {
          expect(rect(control).right, control.getAttribute('aria-label') || control.textContent || control.tagName).toBeLessThanOrEqual(rect(panel).right + 0.5);
        }
        // Each picture's buttons stay inside its own tile, not over the next one.
        for (const tile of form.querySelectorAll('li')) {
          for (const button of tile.querySelectorAll('button')) {
            expect(rect(button).left, button.getAttribute('aria-label')).toBeGreaterThanOrEqual(rect(tile).left - 0.5);
            expect(rect(button).right, button.getAttribute('aria-label')).toBeLessThanOrEqual(rect(tile).right + 0.5);
          }
        }
        form.scrollIntoView();
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-data-edit-${width}-${theme}.png` });
        form.querySelector('.btn-tesla.primary').scrollIntoView({ block: 'end' });
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-data-edit-end-${width}-${theme}.png` });
        await aside.getByRole('button', { name: 'Cancelar' }).click();
        await expect.element(aside.getByRole('button', { name: 'Editar datos' })).toBeVisible();
        panel.querySelector('section').scrollIntoView();
        await aside.getByRole('button', { name: 'Editar', exact: true }).click();
        await expect.element(aside.getByLabelText('SKU')).toBeVisible();
        const box = rect(panel);
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        for (const control of panel.querySelectorAll('input, button')) {
          expect(rect(control).right, control.textContent || control.getAttribute('aria-label')).toBeLessThanOrEqual(box.right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-identity-edit-${width}-${theme}.png` });
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product panel's Cambios tab lists the app's changes inside the panel`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await openProductResumen(screen);
        const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
        await aside.getByRole('tab', { name: 'Cambios' }).click();
        await expect.element(aside.getByText('Precio Clásica')).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        for (const el of panel.querySelectorAll('article, article span, article p, article time')) {
          expect(rect(el).right, el.textContent).toBeLessThanOrEqual(rect(panel).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-cambios-${width}-${theme}.png` });
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product's last purchases fit inside the panel`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await openProductResumen(screen);
        const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
        await expect.element(aside.getByText('Distribuidora Norte')).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        const section = aside.getByText('Distribuidora Norte').element().closest('section');
        section.scrollIntoView();
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        for (const el of section.querySelectorAll('li, li span')) {
          expect(rect(el).right, el.textContent).toBeLessThanOrEqual(rect(panel).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-compras-${width}-${theme}.png` });
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product's sell-in lots fit inside the panel`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await openProductResumen(screen);
        const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
        const next = aside.getByText(/^La próxima venta descuenta \$ 980,33 por unidad \(lote 2\)/);
        await expect.element(next).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        const section = next.element().closest('section');
        section.scrollIntoView();
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        for (const el of section.querySelectorAll('li, li span, li button')) {
          expect(rect(el).right, el.textContent).toBeLessThanOrEqual(rect(panel).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-lotes-${width}-${theme}.png` });
        screen.unmount();
      });
    }

    // Resumen of a product in blocks (S5, design approved 2026-11-11): Ficha, Cifras as tiles, Compras y sell in with
    // the cost mode collapsed behind its chip, Publicaciones, the banlist last. Captured whole, then with the mode open.
    it(`1440x2600 ${theme}: the product Resumen reads as blocks, the cost mode opens from its chip, nothing pokes out (S5)`, async () => {
      const screen = await renderProducts({ width: 1440, height: 2600, theme });
      await openProductResumen(screen);
      const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
      await expect.element(aside.getByText(/^La próxima venta descuenta/)).toBeVisible();
      await expect.element(aside.getByText('Distribuidora Norte')).toBeVisible();
      const panel = document.querySelector('[data-split-panel]');
      const modo = aside.getByRole('region', { name: 'Modo de costo' });
      await expect.element(modo.getByRole('button', { name: /^(Cambiar|Ver)$/ })).toBeVisible();
      await frame();
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-resumen-s5-${theme}.png`, element: panel });
      const titles = [...panel.querySelectorAll('[role="tabpanel"] h3')].map((h) => h.textContent);
      const order = ['Ficha', 'Cifras', 'Compras y sell in', 'Publicaciones'].map((title) => titles.indexOf(title));
      expect(order.every((index) => index >= 0), titles.join(' | ')).toBe(true);
      expect([...order].sort((a, b) => a - b)).toEqual(order);
      const box = rect(panel);
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      for (const el of panel.querySelectorAll('[role="tabpanel"] section, [role="tabpanel"] dd, [role="tabpanel"] button')) {
        if (rect(el).width === 0) continue;
        expect(rect(el).right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(box.right + 0.5);
      }
      await modo.getByRole('button', { name: /^(Cambiar|Ver)$/ }).click();
      await expect.element(aside.getByText('Modo actual')).toBeVisible();
      await frame();
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-resumen-s5-modo-${theme}.png`, element: panel });
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      screen.unmount();
    });

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the catalog competition of a product's publication fits inside the panel`, async () => {
        promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
          data: {
            fetch_status: 'ok',
            fecha_consulta: '2026-10-27T15:00:00Z',
            our_price: 98500,
            competitor_count: 2,
            undercutting: [
              { item_id: 'MLA1999000001', seller_nickname: 'DISTRIBUIDORA DE REDES DEL LITORAL SRL', price: 96999, markup: 10.42 },
              { item_id: 'MLA1999000002', seller_nickname: 'OTRO VENDEDOR', price: 95500, markup: -2.1 },
            ],
          },
        });
        try {
          const screen = await renderProducts({ width, height, theme });
          // renderProducts sets the list's items; the product panel fetches its own after the click, with these
          publicacionesMlAPI.items.mockResolvedValue({
            data: { ...MARGIN_RESPONSE, items: MARGIN_ITEMS.slice(0, 3).map((item, i) => ({ ...item, catalog_listing: i === 0 })), total: 3 },
          });
          await openProductTab(screen, 'Promos');
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          await aside.getByRole('button', { name: /^Competencia de catálogo de / }).click();
          await expect.element(aside.getByText('DISTRIBUIDORA DE REDES DEL LITORAL SRL')).toBeVisible();
          const panel = document.querySelector('[data-split-panel]');
          const section = aside.getByText('DISTRIBUIDORA DE REDES DEL LITORAL SRL').element().closest('section');
          section.scrollIntoView();
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          for (const el of section.querySelectorAll('li, li span, button')) {
            expect(rect(el).right, el.textContent).toBeLessThanOrEqual(rect(panel).right + 0.5);
          }
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-catalogo-${width}-${theme}.png` });
          screen.unmount();
        } finally {
          // the next tests read the page's own items and no stored snapshot
          promocionesAPI.getCompetenciaCatalogo.mockReset();
          publicacionesMlAPI.items.mockReset();
        }
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: a product row's prearmadas and PxQ badges stay inside its name cell`, async () => {
        const screen = await renderProducts({ width, height, theme });
        const table = screen.getByRole('table', { name: /por producto/ });
        await expect.element(table.getByText('3 tramos · desde $37.800')).toBeVisible();
        const row = rowWith(scrollerOf(), 'Sistema Mesh Deco X20');
        const cell = row.querySelector('td');
        for (const text of ['3 tramos · desde $37.800', '2 listas']) {
          const badge = [...row.querySelectorAll('span')].find((el) => el.textContent.trim() === text);
          expect(badge, text).toBeTruthy();
          expect(rect(badge).right, text).toBeLessThanOrEqual(rect(cell).right + 0.5);
        }
        expect(overflowingCells(scrollerOf())).toEqual([]);
        if (PRODUCT_SHOTS_DIR) {
          row.scrollIntoView({ block: 'center' });
          await frame();
          await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-row-badges-${width}-${theme}.png` });
        }
        screen.unmount();
      });
    }

    // "Filas finas" (vistas-tipo-publicacion S5): a long name is cut, never its badges; the name is in its tooltip.
    // Narrower screens too: the badges never squeeze the name to nothing (it keeps a place to hover).
    // `wider` stands in for a wider fallback font (the CI runner has no Inter either): the badges grow, and the name
    // still keeps its minimum; the badges then go to a second line instead of squeezing it.
    for (const { width, height, wider } of VIEWPORTS.flatMap((v) => [{ ...v, wider: false }, { ...v, wider: true }])) {
    it(`${width}x${height} ${theme}: dense, a long product name is cut with its tooltip and its badges stay whole${wider ? ' (wider font)' : ''}`, async () => {
      localStorage.setItem('publicaciones-ml.filas-finas', 'true');
      try {
        const screen = await renderProducts({ width, height, theme });
        const table = screen.getByRole('table', { name: /por producto/ });
        await expect.element(table.getByText('3 tramos · desde $37.800')).toBeVisible();
        expect(scrollerOf().closest('[data-density]').dataset.density).toBe('dense');
        const row = rowWith(scrollerOf(), 'Sistema Mesh Deco X20');
        const cell = row.querySelector('td');
        const name = [...cell.querySelectorAll('span[title]')].find((el) => el.textContent.startsWith('Sistema Mesh Deco X20'));
        const badges = ['3 tramos · desde $37.800', '2 listas'].map((text) => [
          text,
          [...row.querySelectorAll('span')].find((el) => el.textContent.trim() === text),
        ]);
        if (wider) {
          for (const [, badge] of badges) badge.style.letterSpacing = '3px';
          await frame();
        }
        // Cut or whole, the name is in its tooltip and never squeezed under a few characters.
        expect(name.getAttribute('title')).toBe(name.textContent);
        expect(rect(name).width).toBeGreaterThanOrEqual(Math.min(40, name.scrollWidth));
        if (!wider) expect(name.scrollWidth).toBeGreaterThan(name.clientWidth);
        for (const [text, badge] of badges) {
          expect(name.contains(badge), text).toBe(false);
          expect(rect(badge).width, text).toBeGreaterThan(0);
          expect(rect(badge).right, text).toBeLessThanOrEqual(rect(cell).right + 0.5);
          expect(badge.scrollWidth, text).toBeLessThanOrEqual(badge.clientWidth + 1);
        }
        expect(overflowingCells(scrollerOf())).toEqual([]);
        if (PRODUCT_SHOTS_DIR) {
          await page.screenshot({
            path: `${PRODUCT_SHOTS_DIR}/filas-finas-producto-${width}-${theme}${wider ? '-wider' : ''}.png`,
            element: row,
          });
        }
        screen.unmount();
      } finally {
        localStorage.removeItem('publicaciones-ml.filas-finas');
      }
    });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: a product row's catalog-competition badge sits beside its name, inside the cell`, async () => {
        const screen = await renderProducts({ width, height, theme });
        const table = screen.getByRole('table', { name: /por producto/ });
        const trophy = table.getByRole('img', { name: /^Catálogo: ganando/ }).first();
        await expect.element(trophy).toBeVisible();
        const badge = trophy.element();
        expect(badge).toHaveAttribute('title', 'Ganando a $189999.00');
        const cell = badge.closest('td');
        expect(rect(badge).right).toBeLessThanOrEqual(rect(cell).right + 0.5);
        expect(cell.textContent).toContain('Router Archer AX55');
        expect(overflowingCells(scrollerOf())).toEqual([]);
        if (PRODUCT_SHOTS_DIR) {
          badge.closest('tr').scrollIntoView({ block: 'center' });
          await frame();
          await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-row-catalog-${width}-${theme}.png` });
        }
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product's prearmadas badge fits in the panel header`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await openProductResumen(screen);
        const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
        await expect.element(aside.getByText('2 listas')).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        const badge = aside.getByText('2 listas').element();
        expect(rect(badge).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-prearmadas-${width}-${theme}.png` });
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the wholesale prices of a product's publication fit inside the panel`, async () => {
        pxqAPI.getLive.mockResolvedValue({
          data: {
            item_id: 'MLA1100000005',
            live_status: 'ok',
            live_tiers: [
              { id: 'p1', quantity: 3, amount: 95000 },
              { id: 'p2', quantity: 10, amount: 91500.5 },
            ],
            mirror_tiers: [
              { id: 1, cantidad_minima: 3, precio_unitario: 95000, costo_envio_total: 15000, estado: 'sincronizado', ml_price_id: 'p1' },
              { id: 2, cantidad_minima: 10, precio_unitario: 91500.5, costo_envio_total: null, estado: 'sincronizado', ml_price_id: 'p2' },
            ],
          },
        });
        pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA1100000005', tiers: [] } });
        try {
          const screen = await renderProducts({ width, height, theme });
          await openProductTab(screen, 'PxQ');
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          await aside.getByRole('button', { name: /^Precios mayoristas de / }).first().click();
          const section = aside.getByRole('heading', { name: 'Precios mayoristas' }).element().closest('section');
          await expect.poll(() => section.querySelectorAll('table, li').length).toBeGreaterThan(1);
          const panel = document.querySelector('[data-split-panel]');
          section.scrollIntoView();
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-pxq-${width}-${theme}.png` });
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          for (const el of section.querySelectorAll('li, button, table, input')) {
            expect(rect(el).right, el.textContent).toBeLessThanOrEqual(rect(panel).right + 0.5);
          }
          screen.unmount();
        } finally {
          pxqAPI.getLive.mockReset();
          pxqAPI.getMarkup.mockReset();
        }
      });
      it(`${width}x${height} ${theme}: the promotions of a product's publication read by section on Promos, inside the panel`, async () => {
        promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: PROMOTIONS } });
        promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
        try {
          const screen = await renderProducts({ width, height, theme });
          await openProductTab(screen, 'Promos');
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          await aside.getByRole('button', { name: /^Promociones de / }).first().click();
          await expect.element(aside.getByText('Oferta del día')).toBeVisible();
          const promos = aside.getByRole('region', { name: 'Promociones' }).element();
          const sections = [...promos.querySelectorAll('section[aria-label]')];
          expect(sections.map((section) => section.getAttribute('aria-label'))).toEqual(['Activa ahora', 'Disponibles para activar', 'Cupones']);
          const panel = document.querySelector('[data-split-panel]');
          promos.scrollIntoView();
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-promos-${width}-${theme}.png` });
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          for (const el of promos.querySelectorAll('li, li *, button, a')) {
            const r = rect(el);
            if (r.width === 0) continue;
            expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(rect(panel).right + 0.5);
          }
          screen.unmount();
        } finally {
          promocionesAPI.getPromocionesItem.mockReset();
          promocionesAPI.refreshItemPromociones.mockReset();
        }
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product's instalment settings and their edit fit under its prices`, async () => {
        preciosAPI.obtenerProducto.mockResolvedValue({
          data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, sell_in_out: SELL_IN_OUT, recalcular_cuotas_auto: false, markup_adicional_cuotas_custom: 6.5, markup_adicional_cuotas_pvp_custom: null },
        });
        offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
        try {
          const screen = await renderProducts({ width, height, theme });
          await openProductResumen(screen);
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          await aside.getByRole('tab', { name: 'Precios' }).click();
          await expect.element(aside.getByText('Nunca recalcular')).toBeVisible();
          const panel = document.querySelector('[data-split-panel]');
          const section = aside.getByText('Nunca recalcular').element().closest('section');
          section.scrollIntoView();
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-cuotas-${width}-${theme}.png` });
          await aside.getByRole('button', { name: 'Editar cuotas' }).click();
          await expect.element(aside.getByLabelText('Recalcular cuotas')).toBeVisible();
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          for (const control of section.querySelectorAll('select, input, button')) {
            expect(rect(control).right, control.textContent || control.tagName).toBeLessThanOrEqual(rect(panel).right + 0.5);
          }
          section.scrollIntoView({ block: 'end' });
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-cuotas-edit-${width}-${theme}.png` });
          screen.unmount();
        } finally {
          preciosAPI.obtenerProducto.mockImplementation(() => new Promise(() => {}));
          offsetsGananciaAPI.vigentes.mockImplementation(() => new Promise(() => {}));
        }
      });

      it(`${width}x${height} ${theme}: the product's shipping-cost choice (S7b) fits the panel, amounts on one line`, async () => {
        preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, sell_in_out: SELL_IN_OUT } });
        offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
        publicacionesMlAPI.productEnvio.mockResolvedValue({ data: ENVIO_OPTIONS });
        try {
          const screen = await renderProducts({ width, height, theme });
          await openProductResumen(screen);
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          await aside.getByRole('tab', { name: 'Precios' }).click();
          await expect.element(aside.getByText('Ponderado por ventas')).toBeVisible();
          const panel = document.querySelector('[data-split-panel]');
          const card = aside.getByText('Ponderado por ventas').element().closest('section');
          card.scrollIntoView();
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          expect(getComputedStyle(card).backgroundColor).toBe(tokenColor('--cf-bg-card'));
          const figures = [...card.querySelectorAll('label > span:last-child')];
          expect(figures.length).toBe(7);
          expect(wrapped(figures)).toEqual([]);
          for (const control of card.querySelectorAll('label, button')) {
            expect(rect(control).right, control.textContent).toBeLessThanOrEqual(rect(card).right + 0.5);
          }
          if (PRODUCT_SHOTS_DIR) {
            // A taller window, so the whole card shows below the panel's pinned header.
            await page.viewport(width, 1600);
            card.scrollIntoView({ block: 'end' });
            await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-envio-${width}-${theme}.png`, element: card });
          }
          screen.unmount();
        } finally {
          preciosAPI.obtenerProducto.mockImplementation(() => new Promise(() => {}));
          offsetsGananciaAPI.vigentes.mockImplementation(() => new Promise(() => {}));
          publicacionesMlAPI.productEnvio.mockImplementation(() => new Promise(() => {}));
        }
      });

      it(`${width}x${height} ${theme}: the product's ban and its confirmation fit inside the panel`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await openProductResumen(screen);
        const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
        await aside.getByRole('button', { name: 'Agregar a la banlist' }).click();
        await expect.element(aside.getByLabelText('Palabra de verificación')).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        const confirm = aside.getByLabelText('Palabra de verificación').element().closest('section');
        confirm.scrollIntoView({ block: 'end' });
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        for (const control of confirm.querySelectorAll('input, textarea, button, strong')) {
          expect(rect(control).right, control.textContent || control.tagName).toBeLessThanOrEqual(rect(panel).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-ban-${width}-${theme}.png` });
        screen.unmount();
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product panel's Precios tab shows the product's prices inside the panel`, async () => {
        preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, sell_in_out: SELL_IN_OUT } });
        offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
        try {
          const screen = await renderProducts({ width, height, theme });
          await openProductResumen(screen);
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          await aside.getByRole('tab', { name: 'Precios' }).click();
          await expect.element(aside.getByText('$ 64.000,00')).toBeVisible();
          const panel = document.querySelector('[data-split-panel]');
          const box = rect(panel);
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
          const tabs = [...panel.querySelectorAll('[role="tab"]')];
          expect(tabs.map((tab) => tab.textContent)).toEqual(['Precios', 'Resumen', 'Promos', 'PxQ', 'Cambios']);
          for (const tab of tabs) expect(rect(tab).right).toBeLessThanOrEqual(box.right + 0.5);
          expect(panel.textContent).not.toContain('Cifras');
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-precios-${width}-${theme}.png` });
          screen.unmount();
        } finally {
          preciosAPI.obtenerProducto.mockImplementation(() => new Promise(() => {}));
          offsetsGananciaAPI.vigentes.mockImplementation(() => new Promise(() => {}));
        }
      });
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product's publication tree fits inside the panel, collapsed and expanded`, async () => {
        const publication = (mla, label, extra = {}) => ({
          level: 2, kind: 'publicacion', mla, label, pricelist_id: 4, lista_nombre: 'Clásica', publication_status: 'active',
          official_store_id: null, children: [], ...extra,
        });
        productosAPI.getProductoTree.mockResolvedValue({
          data: {
            item_id: 4101,
            tree: {
              level: 0,
              kind: 'producto',
              label: 'Router Archer AX55',
              children: [
                {
                  level: 1, kind: 'familia', family_id: 'FAM-ARCHER-AX55', label: 'Familia Router Archer AX55 Wi-Fi 6 doble banda',
                  children: [
                    publication('MLA1100000001', 'Router Archer AX55 Wi-Fi 6 negro, con una descripción bastante larga para ver cómo corta'),
                    publication('MLA1100000002', 'Router Archer AX55 Wi-Fi 6 blanco', { publication_status: 'paused', publication_sub_status: ['paused_by_seller'] }),
                  ],
                },
                publication('MLA1100000003', 'Router Archer AX55 (catálogo)', { level: 1, kind: 'catalogo', catalog_product_id: 'MLA23456789' }),
                publication('MLA1100000009', 'Router Archer AX55 eliminado', { level: 1, publication_status: 'closed', publication_sub_status: ['deleted'] }),
              ],
            },
            skipped_anomalous_edges: 0,
            skipped_edges: [],
          },
        });
        // In Productos "Expandir todo" also opens each publication's promos, catalog competition and wholesale prices;
        // the panel's tree carries none of them (they have their own tabs), mocked here in case one slipped back in.
        promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
        promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
        promocionesAPI.confirmarSinPromosML.mockResolvedValue({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } });
        promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({ data: { fetch_status: 'ok', fecha_consulta: '2026-10-27T15:00:00Z', our_price: 98500, competitor_count: 0, undercutting: [] } });
        pxqAPI.getLive.mockResolvedValue({ data: { item_id: 'MLA1100000001', live_status: 'ok', live_tiers: [], mirror_tiers: [] } });
        pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA1100000001', tiers: [] } });
        try {
          const screen = await renderProducts({ width, height, theme });
          await openProductResumen(screen);
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          const section = aside.getByRole('region', { name: 'Publicaciones' });
          await expect.element(section.getByRole('button', { name: 'Expandir todo' })).toBeVisible();
          await expect.element(section.getByRole('button', { name: 'Ver eliminadas (1)' })).toBeVisible();
          const panel = document.querySelector('[data-split-panel]');
          const fits = () => {
            expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
            expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
            const right = rect(panel).right;
            for (const el of section.element().querySelectorAll('*')) {
              const r = rect(el);
              if (r.width === 0) continue;
              expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(right + 0.5);
            }
          };
          section.element().scrollIntoView();
          fits();
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-arbol-colapsado-${width}-${theme}.png` });

          await section.getByRole('button', { name: 'Ver familias' }).click();
          await section.getByRole('button', { name: 'Ver eliminadas (1)' }).click();
          await section.getByRole('button', { name: 'Expandir todo' }).click();
          await expect.element(section.getByText('Router Archer AX55 Wi-Fi 6 blanco')).toBeVisible();
          await expect.element(section.getByText('Router Archer AX55 eliminado')).toBeVisible();
          // Each publication opens its own panel from its "Abrir" button, inside the panel too.
          await expect.element(section.getByRole('button', { name: 'Abrir MLA1100000002' })).toBeVisible();
          const disclosures = [...section.element().querySelectorAll('button')].filter((button) =>
            /^(Promociones|Competencia catálogo|Precios mayoristas)/.test(button.textContent.trim()),
          );
          expect(disclosures).toEqual([]);
          section.element().scrollIntoView();
          fits();
          if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/product-arbol-expandido-${width}-${theme}.png` });
          screen.unmount();
        } finally {
          productosAPI.getProductoTree.mockResolvedValue(DEFAULT_TREE);
          for (const fn of [promocionesAPI.getPromocionesItem, promocionesAPI.refreshItemPromociones, promocionesAPI.confirmarSinPromosML, promocionesAPI.getCompetenciaCatalogo, pxqAPI.getLive, pxqAPI.getMarkup]) fn.mockReset();
          // The tree's view is a shared store: the next test starts closed, families hidden.
          useTreeViewStore.setState({ showFamilia: false, collapseEpoch: 0, collapseMode: 'manual' });
        }
      });
    }

    it(`1366x768 ${theme}: an open product shows its publications one level deeper, "Ver más" inside the table`, async () => {
      const screen = await renderProducts({ width: 1366, height: 768, theme });
      await screen.getByRole('button', { name: /Abrir Router Archer AX55/ }).click();
      await expect.element(screen.getByText('Router TP-Link Archer AX55 por color')).toBeVisible();
      const scroller = scrollerOf();
      expect(pinnedPadding(rowWith(scroller, 'Router TP-Link Archer AX55 por color'))).toBeGreaterThan(
        pinnedPadding(rowWith(scroller, 'Router Archer AX55')),
      );
      const more = [...scroller.querySelectorAll('button')].find((button) => /Ver más/.test(button.textContent));
      expect(more).toBeDefined();
      more.scrollIntoView({ block: 'center' });
      await frame();
      expect(rect(more).right).toBeLessThanOrEqual(rect(scroller).right + 0.5);
      scroller.scrollTo({ top: 0, left: 160 });
      await frame();
      const pinned = rowWith(scroller, 'Router TP-Link Archer AX55 por color').querySelector('td[data-pinned]');
      expect(Math.abs(rect(pinned).left - rect(scroller).left)).toBeLessThanOrEqual(2);
      expect(overflowingCells(scroller)).toEqual([]);
      screen.unmount();
    });
  }
});

// Same shape as the per-item mirror read (`GET /promociones/item/{mla}`), long names included.
const PROMOTIONS = [
  {
    promotion_id: 'P1',
    promotion_type: 'SMART',
    name: 'Promoción inteligente con un nombre bastante largo para ver cómo corta',
    status: 'candidate',
    price: 0,
    suggested_discounted_price: 1234567,
    original_price: 1500000,
    nuestro_markup: 12.5,
    application_status: null,
    start_date: '2026-10-01T00:00:00Z',
    finish_date: '2026-10-31T00:00:00Z',
    payload: { seller_percentage: 30, meli_percentage: 20 },
  },
  { promotion_id: 'P2', promotion_type: 'DOD', name: 'Oferta del día', price: 50000, original_price: 60000, nuestro_markup: -2, application_status: 'active', payload: {} },
  // A seller coupon as ML sends it (backend/tests/fixtures/ml_publications/history_events_MLA1402898289_20261016.json).
  {
    promotion_id: 'C-MLA1713876',
    promotion_type: 'SELLER_COUPON_CAMPAIGN',
    sub_type: 'FIXED_PERCENTAGE',
    name: 'Cupón de recompra',
    status: 'candidate',
    price: 0,
    original_price: 91193,
    start_date: '2026-10-10T00:00:00',
    finish_date: '2026-10-31T23:59:59',
    payload: {
      id: 'C-MLA1713876',
      name: 'Cupón de recompra',
      type: 'SELLER_COUPON_CAMPAIGN',
      price: 0,
      status: 'candidate',
      sub_type: 'FIXED_PERCENTAGE',
      start_date: '2026-10-10T00:00:00',
      finish_date: '2026-10-31T23:59:59',
      original_price: 91193,
      fixed_percentage: 10,
    },
  },
];

// The detail panel open beside the table (publicaciones-ml-vista P13a.T5, S61.1/S62.1).
const SELECTED = MANY[0].item_id;
const PANEL_VIEWPORTS = [
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
];

// The panel opens on Promos (owner, 2026-11-02); these tests read Resumen unless they ask for another tab.
const renderWithPanel = async ({ width, height, theme, margin = false, tab = 'resumen', linked = false, detailExtra = {}, rowExtra = {}, promotions = PROMOTIONS }) => {
  canSeeMargin = margin;
  const base = { ...MANY[0], is_full: true, variations_count: 3 };
  publicacionesMlAPI.items.mockResolvedValue({
    data: margin ? { ...MARGIN_RESPONSE, items: [{ ...base, markup: MARGIN_ITEMS[1].markup }, ...MANY.slice(1)] } : { ...RESPONSE, items: [base, ...MANY.slice(1)] },
  });
  const detail = linked ? (margin ? DETAIL_LINKED_MARGIN : DETAIL_LINKED) : margin ? DETAIL_RESPONSE_MARGIN : DETAIL_RESPONSE;
  // The detail's row carries the same figures as the list row (with ver_ganancia, its markup).
  const row = { ...base, ...(margin ? { markup: MARGIN_ITEMS[1].markup } : {}), ...rowExtra };
  publicacionesMlAPI.detail.mockResolvedValue({ data: { ...detail, ...detailExtra, row } });
  publicacionesMlAPI.events.mockResolvedValue({ data: EVENTS_RESPONSE });
  publicacionesMlAPI.history.mockImplementation((itemId, params) =>
    Promise.resolve({ data: params?.tecnicos ? HISTORY_TECNICOS_RESPONSE : HISTORY_RESPONSE }),
  );
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
  promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
  promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions } });
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  window.scrollTo(0, 0);
  const query = new URLSearchParams({ sel: SELECTED, ...(tab ? { tab } : {}) });
  const screen = await render(
    <MemoryRouter initialEntries={[`/ml-publicaciones?${query}`]}>
      <Shell>
        <PublicacionesML />
      </Shell>
    </MemoryRouter>,
  );
  await expect.element(screen.getByRole('tab', { name: 'Resumen' })).toBeVisible();
  return screen;
};
const panelOf = () => document.querySelector('[data-split-panel]');

describe('Publicaciones ML with the detail panel open (visual)', () => {
  beforeEach(() => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.detail.mockReset();
    publicacionesMlAPI.variations.mockReset();
    publicacionesMlAPI.events.mockReset();
    publicacionesMlAPI.history.mockReset();
  });

  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the header's Costo card and the markup with sell in / sell out fit inside the panel (S6, S9)`, async () => {
        const sellIn = { compra_item_id: 7, descuento_unit: 1500, costo: 62500, unidades_restantes: 12 };
        const screen = await renderWithPanel({
          width,
          height,
          theme,
          margin: true,
          // One consistent set (L11): the breakdown's unit (limpio 81.002,93, costo 64.000 -> 26,5%) is the only one,
          // sell in 62.500 -> 29,6%, plus a 2.000 sell out -> 32,8%.
          rowExtra: { markup: { min: 26.5, max: 26.5, worst: 26.5, any_negative: false, reason: 'ok', partial: 0 } },
          detailExtra: {
            sell_in_out: {
              sell_in: sellIn,
              sell_out: { monto_unit: 2000, campana_ids: [3] },
              markups_sell_in: { publicacion: 29.6 },
              markups_sell_in_out: { publicacion: 32.8 },
            },
          },
        });
        const figures = screen.getByRole('region', { name: 'Cifras de la publicación' });
        await expect.element(figures.getByText('Costo', { exact: true })).toBeVisible();
        await expect.element(figures.getByText('c/ sell in/out', { exact: false })).toBeVisible();
        const region = figures.element();
        const panel = panelOf();
        expect(rect(region).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        for (const card of region.querySelectorAll('dl > div')) {
          expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth + 1);
          expect(rect(card).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/header-costo-sellin-${width}-${theme}.png`, element: panel });
      });

      it(`${width}x${height} ${theme}: the panel shrinks the table beside it, 460-560px wide, and nothing overlaps (S61.1)`, async () => {
        const screen = await renderWithPanel({ width, height, theme });
        const panel = panelOf();
        const scroller = scrollerOf();
        expect(rect(panel).width).toBeGreaterThanOrEqual(460 - 0.5);
        expect(rect(panel).width).toBeLessThanOrEqual(560 + 0.5);
        // The table ends where the panel starts: side by side, never one over the other.
        expect(rect(scroller).right).toBeLessThanOrEqual(rect(panel).left + 0.5);
        expect(rect(panel).right).toBeLessThanOrEqual(width + 0.5);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        // The panel is a column of the layout, not a fixed sheet over the page.
        expect(getComputedStyle(panel).position).toBe('sticky');
        expect(getComputedStyle(panel).backgroundColor).toBe(tokenColor('--cf-bg-card'));
        // The selected row is still on screen, not hidden behind the panel.
        const selected = [...scroller.querySelectorAll('tbody tr')].find((row) => row.textContent.includes(SELECTED));
        expect(selected).toBeDefined();
        // ... inside the scroller's box, which itself ends before the panel.
        expect(rect(selected).top).toBeGreaterThanOrEqual(rect(scroller).top);
        expect(rect(selected).left).toBeGreaterThanOrEqual(rect(scroller).left - 0.5);
        expect(rect(selected).left).toBeLessThan(rect(panel).left);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the table still scrolls on both axes inside its scroller and keeps its pinned column (S62.1)`, async () => {
        const screen = await renderWithPanel({ width, height, theme });
        const scroller = scrollerOf();
        expect(scroller.scrollWidth).toBeGreaterThan(scroller.clientWidth);
        scroller.scrollTo({ top: 300, left: 120 });
        await frame();
        const scrollerBox = rect(scroller);
        const header = scroller.querySelector('thead th');
        expect(Math.abs(rect(header).top - scrollerBox.top)).toBeLessThanOrEqual(2);
        const pinned = scroller.querySelector('tbody tr td[data-pinned]');
        expect(Math.abs(rect(pinned).left - scrollerBox.left)).toBeLessThanOrEqual(2);
        expect(rect(scroller).right).toBeLessThanOrEqual(rect(panelOf()).left + 0.5);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the panel's content fits its width, the tabs stay on one line and the footer stays in view`, async () => {
        const screen = await renderWithPanel({ width, height, theme });
        const panel = panelOf();
        const box = rect(panel);
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        // The tab strip scrolls sideways by design when the tabs outgrow the panel, so its tabs may sit
        // past the edge (clipped, not overflowing); the strip itself must stay inside the panel.
        const strip = panel.querySelector('[role="tablist"]');
        expect(rect(strip).right).toBeLessThanOrEqual(box.right + 0.5);
        for (const el of panel.querySelectorAll('*')) {
          if (strip.contains(el)) continue;
          const r = el.getBoundingClientRect();
          if (r.width === 0) continue;
          expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(box.right + 0.5);
        }
        const tabs = [...panel.querySelectorAll('[role="tab"]')];
        expect(tabs.map((tab) => tab.textContent)).toEqual(['Promos', 'Resumen', 'Datos', 'Variaciones', 'Full', 'Eventos', 'Historial', 'Producto']);
        // One row of tabs: they all start at the same height.
        expect(new Set(tabs.map((tab) => Math.round(rect(tab).top))).size).toBe(1);
        // The footer sits inside the panel's box even though the content is taller than the panel.
        const footer = panel.querySelector('footer');
        // On a laptop the content is taller than the panel (the footer must not scroll away); on a big screen it fits.
        if (height < 900) expect(panel.scrollHeight).toBeGreaterThan(panel.clientHeight);
        expect(rect(footer).bottom).toBeLessThanOrEqual(box.bottom + 0.5);
        expect(rect(footer).top).toBeGreaterThanOrEqual(box.top);
        panel.scrollTo({ top: panel.scrollHeight });
        await frame();
        expect(rect(footer).bottom).toBeLessThanOrEqual(box.bottom + 0.5);
        expect(rect(footer).top).toBeGreaterThanOrEqual(box.top);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: without a tab in the URL the panel opens on Promos, first in the strip (S1)`, async () => {
        const screen = await renderWithPanel({ width, height, theme, tab: '' });
        const promos = screen.getByRole('tab', { name: 'Promos' });
        await expect.element(promos).toHaveAttribute('aria-selected', 'true');
        const strip = panelOf().querySelector('[role="tablist"]');
        expect(strip.querySelector('[role="tab"]').textContent).toBe('Promos');
        expect(rect(strip).right).toBeLessThanOrEqual(rect(panelOf()).right + 0.5);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-opens-promos-${width}-${theme}.png` });
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the money, stock and dates of Resumen stay on one line`, async () => {
        const screen = await renderWithPanel({ width, height, theme });
        const values = [...panelOf().querySelectorAll('dd')].filter((el) => /^[\d.,/: ]+(ARS|%)?$/.test(el.textContent.trim()));
        expect(values.length).toBeGreaterThan(4);
        expect(wrapped(values)).toEqual([]);
        screen.unmount();
      });
    }
  }

  // The panel shows the table's stock (owner, 2026-11-10, S7): the header the total ERP + Full, Resumen ERP and Full,
  // the Full tab Full; the published quantity ("Propio", 12.514 here) nowhere. Captured before asserting, for the PR.
  const STOCK_ROW = {
    stock: { available: 12534, full: 20, own: 12514, as_of: '2026-10-08T09:30:00Z' },
    erp_stock: { quantity: 12500 },
    stock_total: 12520,
  };
  for (const theme of THEMES) {
    it(`1440x900 ${theme}: the panel's stock is the table's: total in the header, ERP and Full below, no Propio (S7)`, async () => {
      const screen = await renderWithPanel({ width: 1440, height: 900, theme, rowExtra: STOCK_ROW });
      await frame();
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-resumen-stock-1440-${theme}.png`, element: panelOf() });
      const figures = screen.getByRole('region', { name: 'Cifras de la publicación' }).element();
      expect(figures.textContent).toContain('12.520');
      expect(figures.textContent).not.toContain('12534');
      const stock = screen.getByRole('region', { name: 'Stock', exact: true }).element();
      expect([...stock.querySelectorAll('dt')].map((el) => el.textContent)).toEqual(['ERP', 'Full']);
      expect(stock.textContent).toContain('Actualizado');
      expect(stock.textContent).toContain('12.500');
      expect(panelOf().textContent).not.toContain('Propio');
      await screen.getByRole('tab', { name: 'Full' }).click();
      await expect.element(screen.getByRole('region', { name: 'Stock ML' })).toBeVisible();
      await frame();
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-full-stock-1440-${theme}.png`, element: panelOf() });
      expect(panelOf().textContent).not.toContain('Propio');
      screen.unmount();
    });
  }

  // Resumen as grouped blocks (S5, design approved 2026-11-11): attention box, Rentabilidad waterfall with its Markup
  // band, Stock and Producto vinculado cards, the Ficha in three groups, then "Más datos de Mercado Libre" collapsed;
  // opened, its tiles, groups, chips, attributes and pictures. Captured closed and open, for the PR.
  const RESUMEN_SELL_IN = {
    sell_in: { compra_item_id: 7, descuento_unit: 1500, costo: 62500, unidades_restantes: 12 },
    sell_out: { monto_unit: 2000, campana_ids: [3] },
    markups_sell_in: { publicacion: 29.6 },
    markups_sell_in_out: { publicacion: 32.8 },
  };
  for (const theme of THEMES) {
    it(`1440x2400 ${theme}: Resumen reads as grouped blocks and the ML data opens inside the panel, nothing pokes out (S5)`, async () => {
      const screen = await renderWithPanel({
        width: 1440,
        height: 2400,
        theme,
        margin: true,
        linked: true,
        rowExtra: STOCK_ROW,
        detailExtra: { sub_status: ['out_of_stock'], sell_in_out: RESUMEN_SELL_IN },
      });
      await expect.element(screen.getByRole('region', { name: 'Rentabilidad' })).toBeVisible();
      await frame();
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-resumen-s5-${theme}.png`, element: panelOf() });
      const toggle = screen.getByRole('button', { name: /Más datos de Mercado Libre/ });
      await expect.element(toggle).toHaveAttribute('aria-expanded', 'false');
      await toggle.click();
      await expect.element(screen.getByRole('list', { name: 'Opciones' })).toBeVisible();
      await frame();
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-resumen-s5-ml-${theme}.png`, element: panelOf() });
      const panel = rect(panelOf());
      const blocks = [...panelOf().querySelectorAll('[role="tabpanel"] section')];
      expect(blocks.length).toBeGreaterThan(5);
      expect(blocks.filter((el) => rect(el).right > panel.right + 0.5 || rect(el).left < panel.left - 0.5).map((el) => el.textContent.slice(0, 40))).toEqual([]);
      // The figures of the waterfall, the Markup band and the stock never wrap.
      const figures = [...panelOf().querySelectorAll('[role="tabpanel"] dd')].filter((el) => /^[\d.,$ %]+$/.test(el.textContent.trim()));
      expect(figures.length).toBeGreaterThan(4);
      expect(wrapped(figures)).toEqual([]);
      screen.unmount();
    });
  }

  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the header keeps the price over its markup, and stays while Resumen scrolls (S1)`, async () => {
        const screen = await renderWithPanel({ width, height, theme, margin: true, linked: true });
        await expect.element(screen.getByRole('region', { name: 'Cifras de la publicación' }).getByTitle('Markup')).toBeVisible();
        const panel = panelOf();
        const strip = panel.querySelector('section[aria-label="Cifras de la publicación"]');
        const price = strip.querySelector('[title="Precio"]');
        const markup = strip.querySelector('[title="Markup"]');
        // One block: the markup right under the price, both inside the panel.
        expect(rect(markup).top).toBeGreaterThanOrEqual(rect(price).bottom - 0.5);
        expect(Math.abs(rect(markup).left - rect(price).left)).toBeLessThan(1);
        expect(getComputedStyle(markup).color).not.toBe(getComputedStyle(price).color);
        for (const el of [price, markup]) expect(rect(el).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-resumen-${width}-${theme}.png`, element: panel });
        // The header stays at the top of the panel while the body scrolls under it (the panel really scrolls).
        const header = panel.querySelector('header');
        const top = rect(header).top;
        expect(panel.scrollHeight).toBeGreaterThan(panel.clientHeight);
        panel.scrollTo({ top: panel.scrollHeight });
        await frame();
        expect(panel.scrollTop).toBeGreaterThan(0);
        expect(Math.abs(rect(header).top - top)).toBeLessThan(1);
        expect(rect(price).top).toBeGreaterThanOrEqual(rect(panel).top - 0.5);
        screen.unmount();
      });
    }
  }

  for (const theme of THEMES) {
    it(`1366x768 ${theme}: big amounts stay whole inside their header figure`, async () => {
      const screen = await renderWithPanel({
        width: 1366,
        height: 768,
        theme,
        margin: true,
        rowExtra: {
          price: { ...MANY[0].price, amount: 12345678.9 },
          stock: { available: 123456, full: 100000, own: 23456 },
          sales_30d: { units: 123456, gross: 98765432.1 },
        },
      });
      const strip = screen.getByRole('region', { name: 'Cifras de la publicación' });
      await expect.element(strip.getByTitle('Markup')).toBeVisible();
      for (const box of strip.element().querySelectorAll('dd')) {
        const edge = rect(box.parentElement).right;
        for (const part of box.querySelectorAll('span')) {
          expect(rect(part).right, part.textContent).toBeLessThanOrEqual(edge + 0.5);
        }
      }
      expect(wrapped([strip.element().querySelector('[title="Precio"]')])).toEqual([]);
      screen.unmount();
    });
  }

  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: Pausar and its confirmation sit in the footer, inside the panel`, async () => {
        const screen = await renderWithPanel({ width, height, theme, detailExtra: { can_resync: true, can_change_status: true } });
        await screen.getByRole('button', { name: 'Pausar', exact: true }).click();
        await expect.element(screen.getByText('¿Pausar la publicación en Mercado Libre?')).toBeVisible();
        const panel = panelOf();
        const footer = panel.querySelector('footer');
        for (const name of ['Confirmar', 'Cancelar', 'Resincronizar']) {
          const button = [...footer.querySelectorAll('button')].find((el) => el.textContent.trim() === name);
          expect(button, name).toBeDefined();
          expect(rect(button).right, name).toBeLessThanOrEqual(rect(panel).right + 0.5);
          expect(rect(button).bottom, name).toBeLessThanOrEqual(rect(panel).bottom + 0.5);
        }
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/publication-pausar-${width}-${theme}.png` });
        screen.unmount();
      });
    }
  }

  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the Eventos tab lists the events inside the panel, with icons, chips and tags`, async () => {
        const screen = await renderWithPanel({ width, height, theme, tab: 'eventos' });
        await expect.element(screen.getByText('Publicación reactivada')).toBeVisible();
        const panel = panelOf();
        const entries = [...panel.querySelectorAll('[role="tabpanel"] li')];
        // 22 captured events; ML's offers of the same minute fold into one line each
        expect(entries).toHaveLength(18);
        for (const entry of entries) expect(rect(entry).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        expect(getComputedStyle(entries[0]).borderTopColor).toBe(tokenColor('--cf-border-default'));
        expect(getComputedStyle(entries[0].querySelector('time')).color).toBe(tokenColor('--cf-text-secondary'));
        const icon = entries[0].querySelector('[data-icon]');
        expect(icon.getAttribute('data-icon')).toBe('promotion');
        expect(rect(icon).width).toBeGreaterThan(0);
        const [offered] = [...panel.querySelectorAll('span')].filter((el) => el.textContent === 'Disponible para activar');
        expect(getComputedStyle(offered).color).toBe(tokenColor('--tone-warning-fg'));
        const chips = [...panel.querySelector('[role="tabpanel"]').querySelectorAll('button[aria-pressed]')];
        expect(chips.map((chip) => chip.textContent.replace(/\d+$/, ''))).toEqual(['Todos', 'Hechos por nosotros', 'Cambios de ML', 'Solo importantes']);
        for (const chip of chips) expect(rect(chip).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the Historial tab shows readable cards, the technical lines only after "Mostrar datos técnicos"`, async () => {
        const screen = await renderWithPanel({ width, height, theme, tab: 'historial' });
        await expect.element(screen.getByText('Visitas de los últimos 30 días')).toBeVisible();
        const panel = panelOf();
        expect(panel.textContent).not.toContain('Inicio del período de visitas');
        expect(panel.textContent).not.toMatch(/[{}]/);
        await expect.element(screen.getByText(/^Ocultos 74 cambios técnicos/)).toBeVisible();

        await screen.getByRole('button', { name: 'Promociones', exact: true }).click();
        const cards = [...panel.querySelectorAll('[data-entry]')];
        expect(cards).toHaveLength(4);
        for (const card of cards) expect(rect(card).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        await screen.getByRole('button', { name: 'Todo', exact: true }).click();

        await screen.getByRole('button', { name: 'Mostrar datos técnicos', exact: true }).click();
        // With tecnicos the label is on two cards (34965 and 148600, the visits change made only of technical
        // lines): the one that appears only now is 148600, so the check is on that card.
        await expect.poll(() => panel.querySelector('[data-entry="148600"]')).not.toBeNull();
        const technicalOnly = panel.querySelector('[data-entry="148600"]');
        expect(technicalOnly.textContent).toContain('Inicio del período de visitas');
        expect(rect(technicalOnly).height).toBeGreaterThan(0);
        expect(rect(technicalOnly).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        const periodStarts = [...panel.querySelectorAll('[data-line]')].filter((line) => line.textContent.startsWith('Inicio del período de visitas'));
        expect(periodStarts).toHaveLength(2);
        expect(panel.textContent).not.toContain('Ocultos 74');
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the Datos tab shows the applied data and the original apart, and its edit form, inside the panel`, async () => {
        const original = {
          titulo: 'Router TP-Link Archer AX55 WiFi 6 AX3000 Dual Band Gigabit con OneMesh y control parental',
          descripcion: 'Router WiFi 6 de doble banda.\nHasta 3 Gbps combinados, cuatro antenas y puertos Gigabit para toda la casa.',
          fotos: [1, 2, 3, 4, 5].map((n) => ({ id: `P${n}`, url: `data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"/>#${n}` })),
          atributos: [
            { id: 'BRAND', name: 'Marca', value_name: 'TP-Link' },
            { id: 'MODEL', name: 'Modelo', value_name: 'Archer AX55 Pro edición internacional' },
          ],
        };
        mlItemOverridesAPI.get.mockResolvedValue({
          data: {
            item_id: SELECTED,
            original,
            override: { titulo: 'Router Archer AX55 WiFi 6', descripcion: null, fotos: original.fotos.slice(1), atributos: null },
            aplicado: { ...original, titulo: 'Router Archer AX55 WiFi 6', fotos: original.fotos.slice(1) },
            editable: true,
            updated_at: '2026-10-27T15:00:00Z',
            can_edit: true,
          },
        });
        const screen = await renderWithPanel({ width, height, theme, tab: 'datos' });
        await expect.element(screen.getByRole('region', { name: 'Original en Mercado Libre' })).toBeVisible();
        const panel = panelOf();
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        const box = rect(panel);
        for (const img of panel.querySelectorAll('section img')) {
          expect(rect(img).right).toBeLessThanOrEqual(box.right + 0.5);
          expect(rect(img).left).toBeGreaterThanOrEqual(box.left - 0.5);
        }
        expect(panel.querySelectorAll('section img')).toHaveLength(9);
        // The edit form: every field and button stays inside the panel, each picture's buttons inside its tile.
        await screen.getByRole('button', { name: 'Editar datos' }).click();
        await expect.element(screen.getByRole('button', { name: 'Volver al original' })).toBeVisible();
        const form = panel.querySelector('form');
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        for (const control of form.querySelectorAll('input, textarea, button, img')) {
          expect(rect(control).right, control.getAttribute('aria-label') || control.textContent || control.tagName).toBeLessThanOrEqual(box.right + 0.5);
        }
        for (const tile of form.querySelectorAll('li')) {
          for (const button of tile.querySelectorAll('button')) {
            expect(rect(button).left, button.getAttribute('aria-label')).toBeGreaterThanOrEqual(rect(tile).left - 0.5);
            expect(rect(button).right, button.getAttribute('aria-label')).toBeLessThanOrEqual(rect(tile).right + 0.5);
          }
        }
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: "Actualizar en ML" shows each field's state inside the panel, in the theme's tones`, async () => {
        const datos = { titulo: 'Router TP-Link Archer AX55', descripcion: 'Router WiFi 6', fotos: [], atributos: [] };
        mlItemOverridesAPI.get.mockResolvedValue({
          data: {
            item_id: SELECTED,
            original: datos,
            override: { titulo: 'Router Archer AX55 WiFi 6', descripcion: null, fotos: null, atributos: null },
            aplicado: { ...datos, titulo: 'Router Archer AX55 WiFi 6' },
            editable: true,
            updated_at: '2026-10-27T15:00:00Z',
            can_edit: true,
          },
        });
        mlItemOverridesAPI.pushToMl.mockResolvedValue({
          data: {
            status: 'sent',
            message: null,
            partes: [
              { campo: 'fotos', estado: 'submitted', motivo: null },
              { campo: 'atributos', estado: 'rejected', motivo: 'The attribute MODEL_WITH_A_VERY_LONG_IDENTIFIER_FROM_ML cannot be modified for items with sales' },
              { campo: 'descripcion', estado: 'ambiguous', motivo: 'No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar.' },
              { campo: 'titulo', estado: 'omitted', motivo: 'La publicación tiene ventas: Mercado Libre no deja cambiar el título.' },
            ],
          },
        });
        const screen = await renderWithPanel({ width, height, theme, tab: 'datos' });
        await screen.getByRole('button', { name: 'Actualizar en ML' }).click();
        await screen.getByRole('button', { name: 'Confirmar' }).click();
        await expect.element(screen.getByRole('region', { name: 'Resultado en Mercado Libre' })).toBeVisible();
        const panel = panelOf();
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        const lines = [...panel.querySelectorAll('li[data-estado]')];
        expect(lines).toHaveLength(4);
        for (const line of lines) expect(rect(line).right).toBeLessThanOrEqual(rect(panel).right + 0.5);
        const tone = (estado) => getComputedStyle(lines.find((line) => line.dataset.estado === estado)).color;
        expect(tone('submitted')).toBe(tokenColor('--tone-success-fg'));
        expect(tone('rejected')).toBe(tokenColor('--tone-danger-fg'));
        expect(tone('ambiguous')).toBe(tokenColor('--tone-warning-fg'));
        expect(tone('omitted')).toBe(tokenColor('--cf-text-primary'));
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the Producto vinculado tab fits the panel and shows the cost only with the margin permission`, async () => {
        const screen = await renderWithPanel({ width, height, theme, tab: 'producto', linked: true });
        await expect.element(screen.getByText('Precios de lista')).toBeVisible();
        const panel = panelOf();
        expect(panel.textContent).not.toContain('64.000');
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        const prices = [...panel.querySelectorAll('dd')].filter((el) => /^[\d.,]+$/.test(el.textContent.trim()));
        expect(prices.length).toBeGreaterThan(3);
        expect(wrapped(prices)).toEqual([]);
        screen.unmount();

        const withCost = await renderWithPanel({ width, height, theme, tab: 'producto', linked: true, margin: true });
        await expect.element(withCost.getByText('64.000,00 ARS')).toBeVisible();
        withCost.unmount();
      });
    }
  }

  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the Promociones tab shows the promotions by section, coupons last, inside the panel`, async () => {
        const screen = await renderWithPanel({ width, height, theme, tab: 'promociones' });
        await expect.element(screen.getByText('Oferta del día')).toBeVisible();
        const panel = panelOf();
        const box = rect(panel);
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        const sections = [...panel.querySelectorAll('[role="tabpanel"] section')];
        expect(sections.map((section) => section.getAttribute('aria-label'))).toEqual(['Activa ahora', 'Disponibles para activar', 'Cupones']);
        // Top to bottom in that order.
        for (let index = 1; index < sections.length; index += 1) expect(rect(sections[index]).top).toBeGreaterThan(rect(sections[index - 1]).bottom - 0.5);
        const coupons = sections.at(-1);
        expect(coupons.querySelector('button')).toBeNull();
        await expect.element(screen.getByRole('link', { name: 'Ver promociones en Mercado Libre' })).toBeVisible();
        const rows = [...panel.querySelectorAll('[role="tabpanel"] li')];
        expect(rows).toHaveLength(3);
        // A negative markup VALUE reads in the danger tone, never in the default text grey.
        const markup = rows.flatMap((row) => [...row.querySelectorAll('span')]).find((el) => el.textContent === 'Tu markup: -2.0%');
        expect(markup).toBeDefined();
        expect(getComputedStyle(markup).color).toBe(tokenColor('--tone-danger-fg'));
        expect(getComputedStyle(markup).color).not.toBe(tokenColor('--cf-text-secondary'));
        expect(getComputedStyle(markup).color).not.toBe(tokenColor('--cf-text-primary'));
        // The type column hugs its badges: the name starts right after them, top-aligned with the first one.
        for (const row of rows.filter((li) => !li.closest('section[aria-label="Cupones"]'))) {
          const [typeCell, main] = row.children;
          const badges = [...typeCell.children];
          const badgesRight = Math.max(...badges.map((badge) => rect(badge).right));
          expect(rect(main).left - badgesRight, row.textContent.slice(0, 40)).toBeLessThanOrEqual(16);
          expect(Math.abs(rect(badges[0]).top - rect(main).top), row.textContent.slice(0, 40)).toBeLessThanOrEqual(4);
        }
        for (const el of rows.flatMap((row) => [row, ...row.querySelectorAll('*')])) {
          const r = rect(el);
          if (r.width === 0) continue;
          expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(box.right + 0.5);
        }
        screen.unmount();
      });
    }
  }

  // Precios (S2): one table, a row per plan with Lista ML and PVP side by side; Calcular ends the reference line and
  // the Tienda Nube price sits by the web transfer. Every price once, none wrapping, all inside the panel.
  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the Precios tab is one table, a row per plan, every price once and on one line`, async () => {
        preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, sell_in_out: SELL_IN_OUT } });
        offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
        try {
          const screen = await renderWithPanel({ width, height, theme, tab: 'precios', linked: true, margin: true });
          const table = screen.getByRole('table', { name: 'Precios por plan' });
          await expect.element(table.getByText('$ 98.500,50')).toBeVisible();
          const panel = panelOf();
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          expect(screen.getByRole('region', { name: 'Precios de la lista' }).query()).toBeNull();
          const references = screen.getByRole('group', { name: 'Referencias del producto' });
          await expect.element(references.getByRole('button', { name: 'Calcular el precio de Router Archer AX55' })).toBeVisible();
          const transfer = screen.getByRole('row', { name: /^Web transferencia/ });
          await expect.element(transfer).toHaveTextContent('249.999,00');
          // No price or markup breaks over two lines. Whether the table fits the panel's width depends on the host's
          // typeface (see the markup chips test below): that fit is checked by hand on a screenshot.
          expect(wrapped(table.element().querySelectorAll('td[data-entry] > div:first-child > span:first-child, td[data-entry] [data-tone]'))).toEqual([]);
          const amounts = panel.querySelector('[role="tabpanel"]').textContent.match(/\$ ?[\d.]+,\d{2}/g) ?? [];
          expect(amounts.filter((amount, index) => amounts.indexOf(amount) !== index)).toEqual([]);
          if (PRODUCT_SHOTS_DIR) {
            table.element().scrollIntoView({ block: 'start' });
            await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-precios-plan-${width}-${theme}.png`, element: panel });
          }
          screen.unmount();
        } finally {
          preciosAPI.obtenerProducto.mockImplementation(() => new Promise(() => {}));
          offsetsGananciaAPI.vigentes.mockImplementation(() => new Promise(() => {}));
        }
      });
    }
  }

  // Precios: the reference line with the cost, each plan's markups as chips by the app scale (markupTone).
  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the Precios tab shows the cost with sell in, every markup of each plan as toned chips and fits the panel`, async () => {
        preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, sell_in_out: SELL_IN_OUT } });
        offsetsGananciaAPI.vigentes.mockResolvedValue({
          data: [{ id: 7, marca: 'TP-LINK', tipo_offset: 'porcentaje_costo', porcentaje: 10, descripcion: 'Rebate TP-Link con una descripción larga', grupo_id: null }],
        });
        try {
          const screen = await renderWithPanel({ width, height, theme, tab: 'precios', linked: true, margin: true });
          await expect.element(screen.getByRole('table', { name: 'Precios por plan' })).toBeVisible();
          const panel = panelOf();
          const facts = panel.querySelector('[aria-label="Referencias del producto"]');
          const table = panel.querySelector('table[aria-label="Precios por plan"]');
          const chip = (label, col) => table.querySelector(`[data-entry-label="${label}"] [data-col="${col}"] [data-tone]`);
          // The offsets load after the prices: wait for the markup with offset before measuring.
          await expect.poll(() => chip('Clásica', 'markup-offset')?.textContent).toBe('31,56%');
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          // The "Costo con offset" fact is gone; the cost with sell in stays.
          expect(facts).not.toHaveTextContent('Costo con offset');
          expect(facts).toHaveTextContent('Costo c/ sell in');

          expect(getComputedStyle(chip('Clásica', 'markup')).color).toBe(tokenColor('--tone-success-fg'));
          expect(getComputedStyle(chip('12 cuotas', 'markup')).color).toBe(tokenColor('--tone-danger-fg'));
          expect(getComputedStyle(chip('12 cuotas', 'markup')).backgroundColor).toBe(tokenColor('--tone-danger-bg'));
          expect(chip('Clásica', 'markup-offset').textContent).toBe('31,56%');
          expect(chip('Clásica', 'markup-sell-in-out').textContent).toBe('28,80%');
          expect(facts).toHaveTextContent('$ 60.000,00');
          // Readable on the panel in both themes: the table paints nothing of its own.
          let backdrop = table;
          while (getComputedStyle(backdrop).backgroundColor === 'rgba(0, 0, 0, 0)') backdrop = backdrop.parentElement;
          const card = getComputedStyle(backdrop).backgroundColor;
          for (const label of ['Clásica', '12 cuotas']) {
            expect(contrastRatio(getComputedStyle(chip(label, 'markup')).color, card)).toBeGreaterThanOrEqual(3);
          }

          // Figures on one line. Whether every list fits the panel's width depends on the typeface the host
          // resolves (the suite loads none, see pxqPanel.visual.test.jsx): the CI runner's fallback is about a
          // quarter wider than a desktop's, so that fit is checked by hand on a screenshot, not here.
          expect(wrapped(table.querySelectorAll('td[data-entry] [data-tone]'))).toEqual([]);
          // Rebate, best offer and web transferencia: chips by the same scale, details wrap under the label.
          const extras = [...panel.querySelectorAll('section[data-list="extras"] tbody tr')];
          expect(getComputedStyle(extras[0].querySelector('[data-tone]')).color).toBe(tokenColor('--tone-success-fg'));
          expect(extras.some((tr) => tr.querySelector('th').textContent.includes('Hasta 31/12'))).toBe(true);
          // Editing by markup is offered on every row, not hidden behind the price editor.
          expect(panel.querySelectorAll('button[aria-label$=" por markup"]')).toHaveLength(10);
          screen.unmount();
        } finally {
          preciosAPI.obtenerProducto.mockImplementation(() => new Promise(() => {}));
          offsetsGananciaAPI.vigentes.mockImplementation(() => new Promise(() => {}));
        }
      });
    }
  }

  // The strip must survive a panel too narrow for its tabs; CI fonts are wider than local ones, so force it.
  for (const theme of THEMES) {
    it(`1366x768 ${theme}: when the tabs outgrow the panel the strip scrolls on one line and keeps the open tab in view`, async () => {
      const squeeze = document.createElement('style');
      squeeze.textContent = '[data-split-panel] [role="tablist"] { max-width: 240px; }';
      document.head.append(squeeze);
      try {
        // A tab at the far end of the strip, so keeping it in view takes a scroll.
        const screen = await renderWithPanel({ width: 1366, height: 768, theme, tab: 'historial' });
        const strip = panelOf().querySelector('[role="tablist"]');
        const tabs = [...strip.querySelectorAll('[role="tab"]')];
        expect(strip.scrollWidth).toBeGreaterThan(strip.clientWidth + 1);
        expect(new Set(tabs.map((tab) => Math.round(rect(tab).top))).size).toBe(1);
        const open = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true');
        expect(open.textContent).toBe('Historial');
        expect(strip.scrollLeft).toBeGreaterThan(0);
        expect(rect(open).left).toBeGreaterThanOrEqual(rect(strip).left - 0.5);
        expect(rect(open).right).toBeLessThanOrEqual(rect(strip).right + 0.5);
        screen.unmount();
      } finally {
        squeeze.remove();
      }
    });
  }

  // S9b: the "Hay candidatas mejores" block is a suggestion card above the tabs; the Promos tab marks its row "Sugerida".
  for (const theme of THEMES) {
    it(`1366x768 ${theme}: the suggested promo is a card with Aplicar sugerencia, and its Promos row says Sugerida`, async () => {
      const suggested = {
        promotion_id: 'P-SUG',
        promotion_type: 'SMART',
        name: 'Potencia tus ventas',
        status: 'candidate',
        price: 57920.55,
        original_price: 86539,
        nuestro_markup: -28.34,
        payload: { seller_percentage: 30.4, meli_percentage: 2.7 },
      };
      promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: -28.74 } });
      const screen = await renderWithPanel({
        width: 1366,
        height: 768,
        theme,
        tab: 'promociones',
        promotions: [suggested, ...PROMOTIONS],
        rowExtra: { hay_mejores_ofertas: true, price: { ...MANY[0].price, amount: 59999 } },
      });
      await expect.element(screen.getByRole('button', { name: 'Aplicar sugerencia' })).toBeVisible();
      await expect.element(screen.getByText('Sugerida', { exact: true })).toBeVisible();
      const panel = panelOf();
      const box = rect(panel);
      const card = panel.querySelector('[role="group"][aria-label="Promo sugerida SMART"]');
      expect(card).not.toBeNull();
      expect(getComputedStyle(card).borderTopColor).toBe(tokenColor('--cf-border-default'));
      // The card sits above the tab strip, inside the panel, on one row.
      expect(rect(card).bottom).toBeLessThanOrEqual(rect(panel.querySelector('[role="tablist"]')).top);
      for (const el of [card, ...card.querySelectorAll('*')]) {
        const r = rect(el);
        if (r.width === 0) continue;
        expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(box.right + 0.5);
      }
      const markup = [...card.querySelectorAll('span')].find((el) => el.textContent === '-28,34%');
      expect(getComputedStyle(markup).color).toBe(tokenColor('--tone-danger-fg'));
      // The tab no longer repeats the banner.
      const walker = document.createTreeWalker(panel, NodeFilter.SHOW_TEXT);
      let banners = 0;
      while (walker.nextNode()) if (walker.currentNode.textContent.includes('Hay candidatas mejores')) banners += 1;
      expect(banners).toBe(1);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/sugerencia-1366-${theme}.png`, element: panel });
      screen.unmount();
    });
  }

  it('1366x768 light: the Variaciones tab flags the negative variation with the danger tone and fits the panel', async () => {
    const screen = await renderWithPanel({ width: 1366, height: 768, theme: 'light', margin: true, tab: 'variaciones' });
    await expect.element(screen.getByText('Variación 9002')).toBeVisible();
    const panel = panelOf();
    const cardOf = (id) => [...panel.querySelectorAll('li')].find((li) => li.textContent.includes(`Variación ${id}`));
    expect(getComputedStyle(cardOf(9002)).backgroundColor).toBe(tokenColor('--tone-danger-bg'));
    expect(getComputedStyle(cardOf(9001)).backgroundColor).not.toBe(tokenColor('--tone-danger-bg'));
    expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
    expect(rect(scrollerOf()).right).toBeLessThanOrEqual(rect(panel).left + 0.5);
    screen.unmount();
  });

  it('1366x768 dark: the Full tab shows a complete report without the partial badge, its figures on one line', async () => {
    const screen = await renderWithPanel({ width: 1366, height: 768, theme: 'dark', tab: 'full' });
    await expect.element(screen.getByText('Últimos 30 días')).toBeVisible();
    expect(screen.getByText('Datos parciales').elements()).toHaveLength(0);
    const panel = panelOf();
    const figures = [...panel.querySelectorAll('dd')].filter((el) => /^[\d.,]+( ARS)?$/.test(el.textContent.trim()));
    expect(figures.length).toBeGreaterThan(5);
    expect(wrapped(figures)).toEqual([]);
    expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
    screen.unmount();
  });

  it('1366x768 light: the footer of a manager shows the Resincronizar button inside the panel', async () => {
    const screen = await renderWithPanel({ width: 1366, height: 768, theme: 'light', margin: true });
    const button = screen.getByRole('button', { name: 'Resincronizar' });
    await expect.element(button).toBeVisible();
    const box = rect(button.element());
    expect(box.right).toBeLessThanOrEqual(rect(panelOf()).right + 0.5);
    expect(box.left).toBeGreaterThanOrEqual(rect(panelOf()).left - 0.5);
    screen.unmount();
  });

  for (const theme of THEMES) {
    it(`1366x768 ${theme}: dragging the divider gives the panel more room and the table less, side by side`, async () => {
      localStorage.removeItem('split-panel-width:publicaciones-ml');
      const screen = await renderWithPanel({ width: 1366, height: 768, theme });
      const handle = document.querySelector('[role="separator"][aria-label="Ancho del panel"]');
      const before = rect(panelOf()).width;
      const x = rect(handle).left + rect(handle).width / 2;
      handle.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, clientX: x, clientY: 300 }));
      window.dispatchEvent(new PointerEvent('pointermove', { buttons: 1, clientX: x - 160, clientY: 300 }));
      window.dispatchEvent(new PointerEvent('pointerup', { clientX: x - 160, clientY: 300 }));
      await frame();
      const panel = rect(panelOf());
      expect(panel.width).toBeCloseTo(before + 160, 0);
      expect(panel.width).toBeGreaterThan(1366 * 0.42);
      expect(rect(scrollerOf()).right).toBeLessThanOrEqual(panel.left + 0.5);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
      if (PRODUCT_SHOTS_DIR) {
        await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/panel-resized-1366-${theme}.png`, element: document.querySelector('[data-split-grid]') });
      }
      localStorage.removeItem('split-panel-width:publicaciones-ml');
      screen.unmount();
    });
  }
});

describe('Publicaciones ML KPI strip (visual, P12b)', () => {
  const strip = () => document.querySelector('section[aria-label="Indicadores de las publicaciones"]');

  beforeEach(() => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockResolvedValue({ data: RESPONSE });
  });

  // 1280 is the narrowest the page is used at; CI's wider fonts need the slack the assertions leave.
  for (const { width, height } of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 1280, height: 720 }]) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: every tile fits its card and the strip fits the page, with the profit tiles too`, async () => {
        canSeeMargin = true;
        publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE_MARGIN });
        const screen = await renderPage({ width, height, theme });
        await expect.element(screen.getByText('Markup promedio')).toBeVisible();
        const box = rect(strip());
        expect(box.right).toBeLessThanOrEqual(width + 0.5);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        const cards = [...strip().querySelectorAll('[class*="cards"] > *')];
        expect(cards).toHaveLength(6);
        for (const card of cards) {
          expect(card.scrollWidth, card.textContent).toBeLessThanOrEqual(card.clientWidth + 1);
          expect(rect(card).right).toBeLessThanOrEqual(box.right + 0.5);
        }
        // The big figures never wrap, whatever the font.
        expect(wrapped(strip().querySelectorAll('[data-kpi-value]'))).toEqual([]);
        expect(getComputedStyle(cards[0]).backgroundColor).toBe(tokenColor('--cf-bg-card'));
        screen.unmount();
      });
    }
  }

  it('narrow: the markup notice and the period selector wrap inside the strip', async () => {
    canSeeMargin = true;
    publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE_MARGIN });
    await page.viewport(900, 720);
    setTheme('light');
    const screen = await render(
      <MemoryRouter initialEntries={['/ml-publicaciones?markup_neg=1']}>
        <Shell>
          <PublicacionesML />
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByText('Los KPIs no aplican el filtro de markup')).toBeVisible();
    const box = rect(strip());
    for (const child of strip().querySelectorAll('[class*="toolbar"] > *')) {
      expect(rect(child).right).toBeLessThanOrEqual(box.right + 0.5);
    }
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(900);
    screen.unmount();
  });

  it('without ml_metricas.ver there is no strip and the table renders', async () => {
    canSeeKpis = false;
    const screen = await renderPage({ width: 1366, height: 768, theme: 'light' });
    expect(strip()).toBeNull();
    expect(publicacionesMlAPI.kpis).not.toHaveBeenCalled();
    expect(scrollerOf()).not.toBeNull();
    screen.unmount();
  });
});

describe('Publicaciones ML bulk pause / activate (visual)', () => {
  beforeEach(() => {
    canSeeMargin = false;
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockResolvedValue({ data: RESPONSE });
    publicacionesMlAPI.statusItemIds.mockReset();
    publicacionesMlAPI.statusItemIds.mockResolvedValue({
      data: { item_ids: ['MLA1100000100', 'MLA1100000104'], count: 2, no_aplican: 3 },
    });
  });

  for (const { width, height } of VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the toolbar keeps its buttons inside the page and the confirmation fits the screen`, async () => {
        const screen = await renderPage({ width, height, theme });
        const button = screen.getByRole('button', { name: 'Pausar / activar' });
        await expect.element(button).toBeVisible();
        expect(rect(button.element()).right).toBeLessThanOrEqual(width + 0.5);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        await button.click();
        await screen.getByRole('menuitem', { name: 'Pausar las del filtro' }).click();
        const region = screen.getByRole('region', { name: 'Pausar o activar publicaciones' });
        await expect.element(region).toHaveTextContent('Se van a pausar 2 publicaciones en Mercado Libre.');
        const box = rect(region.element());
        expect(box.right).toBeLessThanOrEqual(width + 0.5);
        expect(box.bottom).toBeLessThanOrEqual(height + 0.5);
        await expect.element(screen.getByRole('button', { name: 'Confirmar' })).toBeVisible();
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/bulk-status-${width}-${theme}.png` });
        screen.unmount();
      });
    }
  }
});

describe('row colors and the color layer (S8)', () => {
  beforeEach(() => {
    canSeeMargin = false;
    equiposAPI.listar.mockResolvedValue({ data: [{ id: 1, nombre: 'U', es_global: true }, { id: 12, nombre: 'Ventas', es_global: false }] });
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockResolvedValue({
      data: {
        ...RESPONSE,
        items: RESPONSE.items.map((item, index) =>
          index === 0 ? { ...item, color_marcado: 'rojo' } : index === 1 ? { ...item, color_hint_global: 'azul' } : item,
        ),
      },
    });
  });

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: the layer selector fits the filter band and a painted row reads on its color`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme });
      await expect.element(screen.getByRole('combobox', { name: 'Capa de color' })).toBeVisible();
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
      const [painted, hinted] = document.querySelectorAll('tbody tr');
      const cell = painted.querySelector('td:nth-child(2)');
      expect(getComputedStyle(cell).backgroundColor).toBe(tokenColor('--product-urgent-bg'));
      const background = getComputedStyle(cell).backgroundColor;
      // The texts a cell draws with the theme's tokens (the title, the MLA) read on the tone in both themes.
      for (const text of [painted.querySelector('td'), screen.getByText('MLA1100000100').element()]) {
        expect(contrastRatio(getComputedStyle(text).color, background)).toBeGreaterThanOrEqual(4.5);
      }
      expect(getComputedStyle(hinted.querySelector('td')).boxShadow).toContain('inset');
      painted.scrollIntoView({ block: 'center' });
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/row-colors-1366-${theme}.png` });
      // With a publication checked, the Pintar button joins the band and still fits it.
      await screen.getByRole('checkbox', { name: /Seleccionar la publicación/ }).first().click();
      await expect.element(screen.getByRole('button', { name: 'Pintar 1 publicación' })).toBeVisible();
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
      if (PRODUCT_SHOTS_DIR) {
        window.scrollTo(0, 0);
        await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/paint-menu-1366-${theme}.png` });
      }
      screen.unmount();
    });
  }

  // Owner (2026-11-03): "los badges no tienen fondo, entonces, por ejemplo el de clásica en verde casi no se lee, el de
  // activa sobre verde casi no se lee, los días en verde casi no se leen, los colores en naranja casi no se leen, y eso
  // que tengo el modo alto contraste activado". Every text a painted row shows reads at AA on what paints right
  // behind it: the row's tone, or a badge's (or a colored figure's) own solid surface, never a tint over the tone.
  const PALETTE = ['rojo', 'naranja', 'amarillo', 'verde', 'azul', 'purpura', 'gris'];
  // Only an rgb()/rgba() value is read for its alpha: any other serialization (color(), oklch()) is not taken as solid.
  const isRgb = (color) => /^rgba?\(/.test(color);
  const isOpaque = (color) => isRgb(color) && rgba(color)[3] === 1;
  const paintedBehind = (el) => {
    for (let node = el; node; node = node.parentElement) {
      const { backgroundColor } = getComputedStyle(node);
      if (!isRgb(backgroundColor) || rgba(backgroundColor)[3] > 0) return backgroundColor;
    }
    return null;
  };
  // Owner (2026-11-04): "los badges con fondo blanco y letras negras en las filas con color quedaron horribles, fijate
  // de medir los contrastes con cada color y ponerle el color acorde". A badge (any element with a solid surface of its
  // own) stands out from its row's color at the WCAG non-text minimum, 3:1, besides its text reading at AA on it.
  // A badge is a bordered box or a box with a surface of its own; one that blends into the row (its surface the row's
  // color, or none at all) is still a badge and must be reported, not skipped. Controls (checkbox, expand button)
  // and the thumbnail frame are not badges.
  const THUMBNAIL = '[class*="thumbnail"]';
  const surfacesOf = (row) =>
    [...row.querySelectorAll('td *')].filter((el) => {
      if (['INPUT', 'BUTTON'].includes(el.tagName) || el.matches(THUMBNAIL) || el.closest(THUMBNAIL)) return false;
      const { backgroundColor, borderTopWidth } = getComputedStyle(el);
      const cell = getComputedStyle(el.closest('td')).backgroundColor;
      const box = el.getBoundingClientRect();
      const bordered = parseFloat(borderTopWidth) > 0;
      return box.width > 1 && box.height > 1 && (bordered || (isOpaque(backgroundColor) && backgroundColor !== cell));
    });
  const textsOf = (row) =>
    [...row.querySelectorAll('*')].filter((el) => {
      const own = [...el.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
      const box = el.getBoundingClientRect();
      return own && box.width > 1 && box.height > 1 && getComputedStyle(el).visibility !== 'hidden';
    });

  for (const [theme, highContrast] of [['light', false], ['dark', false], ['light', true], ['dark', true]]) {
    const mode = highContrast ? ', high contrast' : '';
    it(`1366x768 ${theme}${mode}: badges, days and colored figures read on every palette color and badges stand out from it`, async () => {
      publicacionesMlAPI.items.mockResolvedValue({
        data: {
          ...RESPONSE,
          items: RESPONSE.items.map((item, index) => (index < PALETTE.length ? { ...item, color_marcado: PALETTE[index] } : item)),
        },
      });
      document.documentElement.classList.toggle('high-contrast', highContrast);
      let screen;
      try {
        screen = await renderPage({ width: 1366, height: 768, theme });
        const rows = [...document.querySelectorAll('tbody tr[data-tone]')];
        expect(rows).toHaveLength(PALETTE.length);
        const unreadable = [];
        for (const row of rows) {
          for (const el of textsOf(row)) {
            const behind = paintedBehind(el);
            const { color } = getComputedStyle(el);
            const label = `${row.title} "${el.textContent.trim()}"`;
            if (!behind || !isOpaque(behind)) unreadable.push(`${label}: no solid surface (${behind})`);
            else if (contrastRatio(color, behind) < 4.5) unreadable.push(`${label}: ${contrastRatio(color, behind).toFixed(2)}`);
          }
        }
        const blending = [];
        for (const row of rows) {
          for (const el of surfacesOf(row)) {
            const cell = getComputedStyle(el.closest('td')).backgroundColor;
            const { backgroundColor } = getComputedStyle(el);
            const label = `${row.title} "${el.textContent.trim()}"`;
            if (!isOpaque(backgroundColor)) blending.push(`${label}: no surface of its own (${backgroundColor})`);
            else if (contrastRatio(backgroundColor, cell) < 3) blending.push(`${label}: ${contrastRatio(backgroundColor, cell).toFixed(2)}`);
          }
          // The thumbnail frame keeps the row's color (an image holder, not a dark block).
          for (const frameEl of row.querySelectorAll(`td ${THUMBNAIL}`)) {
            const cell = getComputedStyle(frameEl.closest('td')).backgroundColor;
            const { backgroundColor } = getComputedStyle(frameEl);
            if (backgroundColor !== cell) blending.push(`${row.title} thumbnail frame: ${backgroundColor}, row ${cell}`);
          }
        }
        if (PRODUCT_SHOTS_DIR) {
          // Tall enough for the seven painted rows, the table scrolled to them.
          await page.viewport(1920, 1400);
          scrollerOf().scrollTop = rows[0].offsetTop - 80;
          await frame();
          await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/palette-rows-${theme}${highContrast ? '-hc' : ''}.png` });
        }
        expect(unreadable).toEqual([]);
        expect(blending).toEqual([]);
      } finally {
        screen?.unmount();
        document.documentElement.classList.remove('high-contrast');
      }
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: a price edited in place keeps its input inside the cell`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme, entry: PRECIOS });
      const edit = screen.getByRole('button', { name: /^Editar Precio Clásica/ }).first();
      await expect.element(edit).toBeVisible();
      await edit.click();
      const input = screen.getByRole('textbox', { name: 'Precio Clásica' });
      await expect.element(input).toBeVisible();
      const box = input.element().getBoundingClientRect();
      const cellBox = input.element().closest('td').getBoundingClientRect();
      expect(box.left).toBeGreaterThanOrEqual(cellBox.left);
      expect(box.right).toBeLessThanOrEqual(cellBox.right);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
      // The first row is painted: what is typed reads on the input in both themes.
      const style = getComputedStyle(input.element());
      expect(contrastRatio(style.color, style.backgroundColor)).toBeGreaterThanOrEqual(4.5);
      input.element().closest('td').scrollIntoView({ block: 'center', inline: 'center' });
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/price-edit-1366-${theme}.png` });
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: the best offer's details sit under its price, each on one line inside the cell`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme, entry: PRECIOS });
      await expect.element(screen.getByText('Hasta 30/11').first()).toBeVisible();
      // The best offer's cell only (the web transfer's % line is a price detail too).
      const cell = screen.getByText('Hasta 30/11').first().element().closest('td');
      const lines = [...cell.querySelectorAll('[data-price-detail]')];
      expect(lines.map((line) => line.textContent)).toEqual(['Aporte 12,50%', 'Rebate $ 5.174,88', 'Hasta 30/11', 'PVP $ 47.999,00']);
      const cellBox = cell.getBoundingClientRect();
      for (const line of lines) {
        const box = line.getBoundingClientRect();
        expect(box.left).toBeGreaterThanOrEqual(cellBox.left);
        expect(box.right).toBeLessThanOrEqual(cellBox.right);
      }
      expect(wrapped(lines)).toEqual([]);
      const style = getComputedStyle(lines[0]);
      expect(contrastRatio(style.color, getComputedStyle(cell).backgroundColor)).toBeGreaterThanOrEqual(4.5);
      cell.scrollIntoView({ block: 'center', inline: 'center' });
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/offer-details-1366-${theme}.png` });
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: the Tienda Nube price and its transfer hint sit over the web transfer, inside the cell`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme, entry: PRECIOS });
      await expect.element(screen.getByText('$183.999,20 transf.').first()).toBeVisible();
      const lines = [...document.querySelectorAll('[data-tn-price]')];
      // The fixture's products repeat down the page.
      expect(new Set(lines.map((line) => line.textContent))).toEqual(new Set(['$ 229.999,00$183.999,20 transf.$ 249.999,00', '$ 52.999,00$42.399,20 transf.']));
      for (const line of lines) {
        const cell = line.closest('td');
        const cellBox = cell.getBoundingClientRect();
        // As `overflowingCells`: half a pixel of rounding, never more.
        for (const part of line.querySelectorAll('span, s')) {
          const box = part.getBoundingClientRect();
          expect(box.left).toBeGreaterThanOrEqual(cellBox.left - 0.5);
          expect(box.right).toBeLessThanOrEqual(cellBox.right + 0.5);
        }
        const hint = getComputedStyle(line.querySelector('div span:last-child'));
        expect(contrastRatio(hint.color, getComputedStyle(cell).backgroundColor)).toBeGreaterThanOrEqual(4.5);
      }
      // The amounts never wrap; the hint may put "transf." on its own line.
      expect(wrapped(document.querySelectorAll('[data-tn-price] > div > span:first-child, [data-tn-price] s'))).toEqual([]);
      lines[1].closest('td').scrollIntoView({ block: 'center', inline: 'center' });
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/tn-price-1366-${theme}.png` });
      screen.unmount();
    });
  }

  for (const [width, height, theme] of [[1366, 768, 'light'], [1366, 768, 'dark'], [1920, 1080, 'light'], [1920, 1080, 'dark']]) {
    it(`${width}x${height} ${theme}: the web transfer's % and its lock sit under the price, inside the cell`, async () => {
      const screen = await renderPage({ width, height, theme, entry: PRECIOS });
      const lock = screen.getByRole('img', { name: '% conservado en cambios masivos' }).first();
      await expect.element(lock).toBeVisible();
      const line = lock.element().closest('[data-price-detail]');
      expect(line.textContent).toBe('(+6,5%)');
      const cell = line.closest('td');
      const cellBox = cell.getBoundingClientRect();
      for (const part of [line, lock.element()]) {
        const box = part.getBoundingClientRect();
        expect(box.left).toBeGreaterThanOrEqual(cellBox.left - 0.5);
        expect(box.right).toBeLessThanOrEqual(cellBox.right + 0.5);
      }
      expect(wrapped([line])).toEqual([]);
      expect(contrastRatio(getComputedStyle(line).color, getComputedStyle(cell).backgroundColor)).toBeGreaterThanOrEqual(4.5);
      cell.scrollIntoView({ block: 'center', inline: 'center' });
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/web-transf-percent-${width}-${theme}.png` });
      screen.unmount();
    });
  }

  // "Filas finas" (vistas-tipo-publicacion S5) shrinks the sparklines only: the lock icon keeps its 10px.
  for (const theme of ['light', 'dark']) {
    it(`1920x1080 ${theme}: dense Precios view, sparklines shrink but the lock icon keeps its size`, async () => {
      localStorage.setItem('publicaciones-ml.filas-finas', 'true');
      try {
        const screen = await renderPage({ width: 1920, height: 1080, theme, entry: PRECIOS });
        const lock = screen.getByRole('img', { name: '% conservado en cambios masivos' }).first();
        await expect.element(lock).toBeVisible();
        expect(scrollerOf().closest('[data-density]').dataset.density).toBe('dense');
        expect(lock.element().getBoundingClientRect().height).toBeLessThanOrEqual(10.5);
        const sparks = [...scrollerOf().querySelectorAll('td svg[aria-label$="90 días"]')];
        expect(sparks.length).toBeGreaterThan(0);
        for (const spark of sparks) expect(spark.getBoundingClientRect().height).toBeLessThanOrEqual(16.5);
        // What dense mode hides (struck price, promotion, "Sin stock ERP") takes no room on the line.
        const hidden = [...scrollerOf().querySelectorAll('[data-dense-hidden]')];
        expect(hidden.length).toBeGreaterThan(0);
        for (const el of hidden) expect(el.getClientRects().length, el.textContent).toBe(0);
        // The meta line is cut inside its own box (whole in the title's tooltip): no cell spills, nothing cut lacks a title.
        const spilling = [...scrollerOf().querySelectorAll('tbody td')].filter((td) => td.scrollWidth > td.clientWidth + 1);
        expect(spilling.map((td) => td.textContent.trim().slice(0, 40))).toEqual([]);
        const cut = [...scrollerOf().querySelectorAll('td[data-column="titulo"] span')].filter((el) => el.scrollWidth > el.clientWidth + 1);
        for (const el of cut) expect(el.getAttribute('title'), el.textContent).toBeTruthy();
        lock.element().closest('td').scrollIntoView({ block: 'center', inline: 'center' });
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/filas-finas-precios-1920-${theme}.png` });
        screen.unmount();
      } finally {
        localStorage.removeItem('publicaciones-ml.filas-finas');
      }
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: the rebate and web transfer editors open inside their cell, every control in view`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme, entry: PRECIOS });
      for (const [button, group] of [
        [/^Editar Precio Rebate/, 'Rebate'],
        [/^Editar Web Transf\./, 'Web transferencia'],
      ]) {
        const edit = screen.getByRole('button', { name: button }).first();
        await expect.element(edit).toBeVisible();
        // The filters have a "Rebate" group of their own: the editor is the one in this cell.
        const cell = edit.element().closest('td');
        await edit.click();
        await expect.poll(() => cell.querySelector(`form[aria-label="${group}"]`)).not.toBeNull();
        const editor = cell.querySelector(`form[aria-label="${group}"]`);
        const cellBox = cell.getBoundingClientRect();
        for (const control of editor.querySelectorAll('input, button, label')) {
          const box = control.getBoundingClientRect();
          expect(box.left).toBeGreaterThanOrEqual(cellBox.left);
          expect(box.right).toBeLessThanOrEqual(cellBox.right);
        }
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
        // The first row is painted: the typed % reads on its input in both themes.
        const percent = getComputedStyle(editor.querySelector('input[type="text"]'));
        expect(contrastRatio(percent.color, percent.backgroundColor)).toBeGreaterThanOrEqual(4.5);
        cell.scrollIntoView({ block: 'center', inline: 'center' });
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/toggle-edit-${group.split(' ')[0].toLowerCase()}-1366-${theme}.png` });
        editor.querySelector('button[type="button"]').click();
        await expect.poll(() => cell.querySelector('form')).toBeNull();
      }
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: Calcular fits its cell and opens Productos' pricing modal inside the screen`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme, entry: PRECIOS });
      const calculate = screen.getByRole('button', { name: 'Calcular el precio de Router Archer AX55' }).first();
      await expect.element(calculate).toBeVisible();
      const box = calculate.element().getBoundingClientRect();
      const cellBox = calculate.element().closest('td').getBoundingClientRect();
      expect(box.left).toBeGreaterThanOrEqual(cellBox.left);
      expect(box.right).toBeLessThanOrEqual(cellBox.right);
      calculate.element().scrollIntoView({ block: 'center', inline: 'center' });
      // Nothing covers it (the pinned title column, the sticky header): the point at its center is the button.
      const center = calculate.element().getBoundingClientRect();
      expect(document.elementFromPoint(center.left + center.width / 2, center.top + center.height / 2)?.closest('button')).toBe(calculate.element());
      calculate.element().click();
      const modal = screen.getByText(/TP-LINK \| REDES \| Stock: 12/);
      await expect.element(modal).toBeVisible();
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/pricing-modal-1366-${theme}.png` });
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: the page's checkbox sits on the title header's line, before its sort button, and is clickable`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme });
      const all = screen.getByRole('checkbox', { name: 'Seleccionar las filas de la página' });
      await expect.element(all).toBeVisible();
      all.element().scrollIntoView({ block: 'center', inline: 'nearest' });
      const header = all.element().closest('th');
      const sort = header.querySelector('button');
      const box = all.element().getBoundingClientRect();
      const sortBox = sort.getBoundingClientRect();
      const headerBox = header.getBoundingClientRect();
      // One line: the checkbox and the sort button share a vertical band, the checkbox first, both inside the cell.
      expect(Math.abs(box.top + box.height / 2 - (sortBox.top + sortBox.height / 2))).toBeLessThanOrEqual(3);
      expect(box.right).toBeLessThanOrEqual(sortBox.left);
      expect(box.left).toBeGreaterThanOrEqual(headerBox.left);
      expect(sortBox.right).toBeLessThanOrEqual(headerBox.right);
      expect(document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)).toBe(all.element());
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/select-page-1366-${theme}.png` });
      screen.unmount();
    });
  }
});

describe('Publicaciones ML Auditoría panel (visual)', () => {
  beforeEach(() => {
    canSeeMargin = false;
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockResolvedValue({ data: RESPONSE });
  });

  for (const { width, height } of VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the users and kinds show whole, with no sideways scroll, inside the screen`, async () => {
        const screen = await renderPage({ width, height, theme });
        await screen.getByRole('button', { name: 'Filtros de auditoría' }).click();
        const panel = screen.getByRole('group', { name: 'Filtros de auditoría' });
        await expect.element(panel.getByText('leandrorochagausson')).toBeVisible();
        await expect.element(panel.getByText('Modificar Porcentaje Rebate')).toBeVisible();
        const lists = [...panel.element().querySelectorAll('fieldset')].slice(0, 2).map((fieldset) => fieldset.lastElementChild);
        expect(lists).toHaveLength(2);
        for (const list of lists) {
          expect(list.scrollWidth, list.textContent.slice(0, 30)).toBeLessThanOrEqual(list.clientWidth);
          for (const option of list.children) expect(rect(option).right, option.textContent).toBeLessThanOrEqual(rect(list).right + 0.5);
        }
        expect(rect(panel.element()).right).toBeLessThanOrEqual(width);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/auditoria-${width}-${theme}.png`, element: panel.element() });
        screen.unmount();
      });
    }
  }
});

describe('Publicaciones ML hideable KPI cards (visual)', () => {
  beforeEach(() => {
    localStorage.removeItem('publicaciones-ml.kpis-ocultos');
    canSeeMargin = true;
    publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE_MARGIN });
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockResolvedValue({ data: RESPONSE });
  });
  // The browser's storage outlives the file: leave every card visible for the suites that run next.
  afterEach(() => localStorage.removeItem('publicaciones-ml.kpis-ocultos'));

  for (const theme of THEMES) {
    it(`1920x1080 ${theme}: hidden cards leave the row with no gap, and with every card hidden the Período stays`, async () => {
      const screen = await renderPage({ width: 1920, height: 1080, theme });
      const strip = document.querySelector('section[aria-label="Indicadores de las publicaciones"]');
      const cards = () => strip.querySelector('div[class*="cards"]');
      await expect.poll(() => cards()?.children.length).toBe(6);
      await screen.getByRole('button', { name: 'Indicadores' }).click();
      const group = screen.getByRole('group', { name: 'Elegir indicadores visibles' });
      await group.getByRole('checkbox', { name: 'Markup promedio' }).click();
      const row = [...cards().children];
      expect(row).toHaveLength(5);
      expect(new Set(row.map((card) => rect(card).top)).size).toBe(1);
      expect(Math.abs(rect(row.at(-1)).right - rect(cards()).right)).toBeLessThan(1);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/kpis-hidden-one-${theme}.png` });

      for (const checkbox of document.querySelectorAll('[aria-label="Elegir indicadores visibles"] input:checked')) checkbox.click();
      await expect.poll(() => cards()).toBeNull();
      await expect.element(screen.getByRole('group', { name: 'Período' })).toBeVisible();
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/kpis-hidden-all-${theme}.png` });
      screen.unmount();
    });
  }
});

describe('Publicaciones ML "Filas finas" (visual, vistas-tipo-publicacion S5)', () => {
  const KEY = 'publicaciones-ml.filas-finas';
  beforeEach(() => {
    localStorage.removeItem(KEY);
    canSeeMargin = false;
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.items.mockResolvedValue({ data: RESPONSE });
  });
  // The browser's storage outlives the file: leave the normal density for the suites that run next.
  afterEach(() => localStorage.removeItem(KEY));

  for (const theme of THEMES) {
    it(`1920x1080 ${theme}: thin rows, titles on one line, nothing wraps or overflows`, async () => {
      const screen = await renderPage({ width: 1920, height: 1080, theme });
      const scroller = scrollerOf();
      const firstRow = () => scroller.querySelector('tbody tr');
      const normalHeight = rect(firstRow()).height;

      await screen.getByRole('button', { name: 'Filas finas' }).click();
      await expect.element(screen.getByRole('button', { name: 'Filas finas', pressed: true })).toBeVisible();
      await frame();
      expect(scroller.closest('[data-density]').dataset.density).toBe('dense');
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/filas-finas-1920-${theme}.png` });
      // Thinner than the current density, at most two short lines (title and its MLA line).
      expect(rect(firstRow()).height).toBeLessThan(normalHeight * 0.75);
      expect(rect(firstRow()).height).toBeLessThanOrEqual(44);

      // Anything cut in the Publicación cell (title or meta line) is readable in its own tooltip. At 1920 px the
      // column takes the room the figures leave (pubml-tabla-columnas S5), so a title may well fit whole.
      const cut = [...scroller.querySelectorAll('td[data-column="titulo"] span')].filter((el) => el.scrollWidth > el.clientWidth + 1);
      for (const el of cut) expect(el.getAttribute('title'), el.textContent).toBeTruthy();
      const titles = [...scroller.querySelectorAll('td[data-column="titulo"] span[title]')];
      expect(titles.length).toBeGreaterThan(0);
      expect(wrapped(titles)).toEqual([]);
      const figures = [...scroller.querySelectorAll('td[data-align] span')].filter((el) =>
        /^[\d.,]+$/.test(el.textContent.trim()),
      );
      expect(figures.length).toBeGreaterThan(0);
      expect(wrapped(figures)).toEqual([]);
      expect(overflowingCells(scroller)).toEqual([]);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1920);
      screen.unmount();
    });
  }
});

// Owner (2026-11-03): "fijate que pusieron un selector para ver todas las filas, cargué 26k de filas en el
// explorador, tendríamos que usar una carga lazy como usamos en envíos flex". A long list renders only the rows in
// view (plus a margin), like Envíos Flex; scrolling, the keyboard and the pinned header keep working over all of them.
describe('Publicaciones ML "Todos" (visual, filtros S4)', () => {
  const ALL = Array.from({ length: 9999 }, (_, i) => ({
    ...ITEMS[i % ITEMS.length],
    item_id: `MLA${1200000000 + i}`,
    metrics: METRICS[i % METRICS.length],
  }));
  beforeEach(() => {
    canSeeMargin = false;
    publicacionesMlAPI.items.mockReset();
    // The backend's paging over the 9999 rows: each request gets its `limit` rows from its `offset`, and the total.
    publicacionesMlAPI.items.mockImplementation(({ limit, offset }) =>
      Promise.resolve({ data: { ...RESPONSE, items: ALL.slice(offset, offset + limit), total: ALL.length, limit, offset } }),
    );
  });

  const renderedRows = () => scrollerOf().querySelectorAll('tbody tr[data-row-key]');

  it('1366x768 light: 9999 rows render only what is in view, and scroll, End and the arrows reach every row', async () => {
    const started = performance.now();
    await page.viewport(1366, 768);
    setTheme('light');
    const screen = await render(
      <MemoryRouter initialEntries={['/ml-publicaciones?limite=9999']}>
        <Shell>
          <PublicacionesML />
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByText('MLA1200000000'), { timeout: 170_000 }).toBeVisible();
    const firstPaint = Math.round(performance.now() - started);
    const heap = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null;
    console.info(`[S4] 9999 rows: first row after ${firstPaint} ms, ${renderedRows().length} rows in the DOM, heap ${heap} MB`);
    expect(renderedRows().length).toBeLessThan(100);
    // "Todos" asks its first 500 rows, not the 9999 (filtros S4 T3b).
    expect(publicacionesMlAPI.items.mock.calls[0][0]).toMatchObject({ limit: 500, offset: 0 });

    // The header stays pinned, and scrolling to the end again and again brings the next 500 each time, to the last row.
    const scroller = scrollerOf();
    const headerTop = rect(scroller.querySelector('thead th')).top;
    await expect
      .poll(
        () => {
          scroller.scrollTop = scroller.scrollHeight;
          return scroller.querySelector('tr[data-row-key="MLA1200009998"]') !== null;
        },
        { timeout: 60_000, interval: 50 },
      )
      .toBe(true);
    await expect.element(screen.getByText('MLA1200009998')).toBeVisible();
    expect(publicacionesMlAPI.items.mock.calls.map(([params]) => params.offset)).toEqual(
      Array.from({ length: 20 }, (_, i) => i * 500),
    );
    expect(rect(scroller.querySelector('thead th')).top).toBe(headerTop);
    expect(renderedRows().length).toBeLessThan(100);

    // Home goes back to the first row, End to the last one, and an arrow steps to the next row of the whole list.
    const last = scroller.querySelector('tr[data-row-key="MLA1200009998"]');
    last.focus();
    await userEvent.keyboard('{Home}');
    await expect.poll(() => document.activeElement?.dataset.rowKey).toBe('MLA1200000000');
    await userEvent.keyboard('{ArrowDown}');
    await expect.poll(() => document.activeElement?.dataset.rowKey).toBe('MLA1200000001');
    await userEvent.keyboard('{End}');
    await expect.poll(() => document.activeElement?.dataset.rowKey).toBe('MLA1200009998');
    await userEvent.keyboard('{ArrowUp}');
    await expect.poll(() => document.activeElement?.dataset.rowKey).toBe('MLA1200009997');
    screen.unmount();
  }, 180_000); // room for the before measurement: every row in the DOM took far longer than the default 15 s
});

// Shaped like MLA1506729443 (2026-11-06, the item of the approved S9 design): one active, several
// available (SELLER_CAMPAIGN, DEAL at its max, two SMART, a LIGHTNING at its suggestion), two ML manages
// and three coupons. Prices from that capture; markups are the design's figures (the DEAL takes the SMART's at the
// same price; the LIGHTNING's at its suggestion was not captured, so it has none).
const S9_ORIGINAL = 86539;
const s9Coupon = (id, name, pct) => ({
  promotion_id: id,
  promotion_type: 'SELLER_COUPON_CAMPAIGN',
  sub_type: 'FIXED_PERCENTAGE',
  name,
  status: 'candidate',
  price: 0,
  original_price: S9_ORIGINAL,
  start_date: '2026-11-04T00:00:00',
  finish_date: '2026-11-30T23:59:59',
  payload: { id, name, type: 'SELLER_COUPON_CAMPAIGN', status: 'candidate', sub_type: 'FIXED_PERCENTAGE', fixed_percentage: pct },
});
const S9_PROMOTIONS = [
  { promotion_id: 'P-MLA18100001', promotion_type: 'SELLER_CAMPAIGN', name: 'TO C500-C520WS 2-11 4-12', status: 'started', price: 59999, original_price: S9_ORIGINAL, nuestro_markup: -28.7, application_status: 'active', start_date: '2026-11-02T00:00:00Z', finish_date: '2026-12-02T00:00:00Z', payload: {} },
  { promotion_id: 'P-MLA18100002', promotion_type: 'SELLER_CAMPAIGN', name: 'PVP LYONN', status: 'candidate', price: 0, suggested_discounted_price: 59514, original_price: S9_ORIGINAL, nuestro_markup: -29.5, application_status: null, start_date: '2026-10-15T00:00:00Z', finish_date: '2026-11-14T00:00:00Z', payload: {} },
  { promotion_id: 'P-MLA18145042', promotion_type: 'DEAL', name: 'MKP T1 CYBER MONDAY NOV', status: 'candidate', price: 0, original_price: S9_ORIGINAL, max_discounted_price: 57920.55, min_discounted_price: 17307.81, suggested_discounted_price: 49266.65, nuestro_markup: -28.3, application_status: null, start_date: '2026-11-02T00:00:00Z', finish_date: '2026-11-12T00:00:00Z', payload: {} },
  { promotion_id: 'P-MLA18100003', promotion_type: 'SMART', name: 'Ofertas compartidas CM', status: 'candidate', price: 63050, original_price: S9_ORIGINAL, nuestro_markup: -19.2, application_status: null, payload: { seller_percentage: 23.5, meli_percentage: 3.6 } },
  { promotion_id: 'P-MLA18100004', promotion_type: 'SMART', name: 'Potencia tus ventas', status: 'candidate', price: 57920.55, original_price: S9_ORIGINAL, nuestro_markup: -28.3, application_status: null, payload: { seller_percentage: 30.4, meli_percentage: 2.7 } },
  { promotion_id: 'LGH-MLA1000', promotion_type: 'LIGHTNING', name: 'LIGHTNING', status: 'candidate', price: 57920.55, original_price: S9_ORIGINAL, min_discounted_price: 17307.81, max_discounted_price: 77885.1, suggested_discounted_price: 73558.15, nuestro_markup: null, application_status: null, payload: { stock: { min: 5, max: 112 } } },
  { promotion_id: 'P-MLA18169016', promotion_type: 'SMART_LIGHTNING', name: 'Relampago compartidas', status: 'started', price: 57341.34, original_price: S9_ORIGINAL, nuestro_markup: -32.8, application_status: null, payload: {} },
  { promotion_id: 'PRICE_DISCOUNT-1', promotion_type: 'PRICE_DISCOUNT', name: 'PRICE_DISCOUNT', status: 'started', price: 59514, original_price: S9_ORIGINAL, nuestro_markup: -29.5, application_status: null, payload: {} },
  s9Coupon('C-MLA1800001', 'Cupón de recompra', 10),
  s9Coupon('C-MLA1800002', 'Cupón para carritos abandonados', 12),
  s9Coupon('C-MLA1800003', 'TO TP-LINK NEW FOLL', 15),
  // Just refreshed from ML, like the design's Estado column.
].map((promo) => (promo.promotion_type === 'SELLER_COUPON_CAMPAIGN' ? promo : { ...promo, updated_at: new Date().toISOString() }));

// The header figures of that capture: the active promotion's price and markup, its stock and 30-day sales.
const S9_ROW = {
  price: { ...MANY[0].price, amount: 59999 },
  markup: { min: -28.7, max: -28.7, worst: -28.7, any_negative: true, reason: 'ok', partial: 0 },
  stock: { available: 71, full: 0, own: 71 },
  sales_30d: { units: 75, gross: 4693617.16 },
};
const renderS9 = (theme) =>
  renderWithPanel({ width: 1920, height: 2200, theme, tab: '', margin: true, promotions: S9_PROMOTIONS, rowExtra: S9_ROW, detailExtra: { can_resync: true, can_change_status: true } });

describe('Publicaciones ML panel, Promos tab of the S9 design (visual)', () => {
  const widthKey = 'split-panel-width:publicaciones-ml';
  afterEach(() => localStorage.removeItem(widthKey));

  for (const theme of THEMES) {
    it(`1920x2200 ${theme}: at its default width a stacked row shows its markup without the "Tu markup:" label, in its tone`, async () => {
      localStorage.removeItem(widthKey);
      const screen = await renderS9(theme);
      await expect.element(screen.getByText('MKP T1 CYBER MONDAY NOV')).toBeVisible();
      const panel = panelOf();
      const rows = [...panel.querySelectorAll('section[aria-label="Disponibles para activar"] li')];
      expect(rows.length).toBeGreaterThan(0);
      for (const row of rows) {
        const label = [...row.querySelectorAll('span')].find((el) => el.textContent === 'Tu markup: ');
        if (!label) continue;
        // Still named for screen readers, not drawn (owner: no label on each row).
        expect(rect(label).width, row.textContent.slice(0, 30)).toBeLessThanOrEqual(1);
        const value = label.parentElement;
        expect(rect(value).width).toBeGreaterThan(1);
      }
      const negative = [...panel.querySelectorAll('span')].find((el) => el.textContent === 'Tu markup: -29.5%');
      expect(getComputedStyle(negative).color).toBe(tokenColor('--tone-danger-fg'));
      // In a narrow card the billed amount wraps whole, never between its "$" and its digits.
      const billed = [...panel.querySelectorAll('header dd span')].find((el) => el.textContent === '$ 4.693.617,16');
      expect(wrapped([billed])).toEqual([]);
      screen.unmount();
    });

    it(`1920x2200 ${theme}: the header reads as the approved design: labelled KPI cards, the ML link on the MLA line`, async () => {
      localStorage.setItem(widthKey, '1040');
      const screen = await renderS9(theme);
      const strip = screen.getByRole('region', { name: 'Cifras de la publicación' });
      await expect.element(strip.getByTitle('Markup')).toBeVisible();
      await frame();
      const panel = panelOf();
      const cards = [...strip.element().querySelectorAll('dl > div')];
      // PRECIO, COSTO (S6), STOCK and VENTAS 30 DÍAS side by side, each label drawn over its value.
      expect(cards.map((card) => card.querySelector('dt').textContent)).toEqual(['Precio', 'Costo', 'Stock', 'Ventas 30 días']);
      expect(new Set(cards.map((card) => Math.round(rect(card).top))).size).toBe(1);
      for (const card of cards) {
        const term = card.querySelector('dt');
        expect(rect(term).width).toBeGreaterThan(10);
        expect(getComputedStyle(term).textTransform).toBe('uppercase');
        expect(getComputedStyle(term).color).toBe(tokenColor('--cf-text-secondary'));
        const amount = card.querySelector('dd > span');
        expect(rect(amount).top).toBeGreaterThanOrEqual(rect(term).bottom - 0.5);
        // The figure is the big line of its card.
        expect(Number.parseFloat(getComputedStyle(amount).fontSize)).toBeGreaterThan(Number.parseFloat(getComputedStyle(term).fontSize) * 1.4);
      }
      // "Markup -28,7%": the word drawn in the label's grey, the value in its tone.
      const markup = strip.element().querySelector('[title="Markup"]');
      const word = [...markup.querySelectorAll('span')].find((el) => el.textContent === 'Markup ');
      expect(rect(word).width).toBeGreaterThan(10);
      expect(getComputedStyle(word).color).toBe(tokenColor('--cf-text-secondary'));
      expect(getComputedStyle(markup).color).toBe(tokenColor('--tone-danger-fg'));
      expect(cards[3].textContent).toContain('Facturado $ 4.693.617,16'); // VENTAS 30 DÍAS, after the Costo card
      // MLA, its badges and "Ver en Mercado Libre" on one line under the title.
      const mla = [...panel.querySelectorAll('header span')].find((el) => el.textContent === SELECTED);
      const link = [...panel.querySelectorAll('header a[href]')].find((el) => el.textContent.includes('Ver en Mercado Libre'));
      expect(link).toBeDefined();
      expect(Math.abs(rect(link).top + rect(link).height / 2 - (rect(mla).top + rect(mla).height / 2))).toBeLessThan(4);
      expect(getComputedStyle(link).textDecorationLine).toBe('none');
      // The open tab is marked in the text colour, as the design.
      const open = panel.querySelector('[role="tab"][aria-selected="true"]');
      expect(getComputedStyle(open).borderBottomColor).toBe(tokenColor('--cf-text-primary'));
      // The footer: freshness in columns, each name with its time at the right; the actions beside it.
      const footer = panel.querySelector('footer');
      const freshness = footer.querySelector('ul');
      const entries = [...freshness.querySelectorAll('li')];
      expect(new Set(entries.map((li) => Math.round(rect(li).top))).size).toBeLessThan(entries.length);
      for (const li of entries) {
        const [name, ago] = li.children;
        expect(rect(ago).right).toBeGreaterThan(rect(li).right - 1);
        expect(rect(name).left).toBeLessThan(rect(li).left + 1);
      }
      const pause = [...footer.querySelectorAll('button')].find((el) => el.textContent.trim() === 'Pausar');
      expect(rect(pause).left).toBeGreaterThanOrEqual(rect(freshness).right - 0.5);
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/s9-header-wide-${theme}.png`, element: panel });
      screen.unmount();
    });

    it(`1920x2200 ${theme}: at its default width the panel stacks each row under the name, no column header`, async () => {
      localStorage.removeItem(widthKey);
      const screen = await renderS9(theme);
      await expect.element(screen.getByText('MKP T1 CYBER MONDAY NOV')).toBeVisible();
      const panel = panelOf();
      expect(rect(panel).width).toBeLessThanOrEqual(560 + 0.5);
      expect(getComputedStyle(panel.querySelector('[data-testid="promo-columns"]')).display).toBe('none');
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/s9-panel-default-${theme}.png`, element: panel });
      screen.unmount();
    });

    it(`1920x2200 ${theme}: widened with the divider, the rows line up under the column header`, async () => {
      localStorage.setItem(widthKey, '1040');
      const screen = await renderS9(theme);
      await expect.element(screen.getByText('MKP T1 CYBER MONDAY NOV')).toBeVisible();
      await frame();
      const panel = panelOf();
      expect(rect(panel).width).toBeGreaterThan(900);
      const header = panel.querySelector('[data-testid="promo-columns"]');
      expect(getComputedStyle(header).display).not.toBe('none');
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/s9-panel-wide-${theme}.png`, element: panel });
      screen.unmount();
    });

    // The LIGHTNING apply card of the approved design: "Cerrar" stays in the row's action column, the card
    // opens under the row with Precio | Tu markup | Stock side by side when wide, stacked at the default width.
    for (const [variant, width] of [['wide', '1040'], ['default', null]]) {
      it(`1920x2200 ${theme}: the LIGHTNING apply card fits the ${variant} panel`, async () => {
        if (width) localStorage.setItem(widthKey, width);
        else localStorage.removeItem(widthKey);
        // The markup at the suggestion is not in the capture: pinned to none, never an earlier test's answer.
        promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: null } });
        const screen = await renderS9(theme);
        await expect.element(screen.getByText('MKP T1 CYBER MONDAY NOV')).toBeVisible();
        await frame();
        const panel = panelOf();
        const section = panel.querySelector('section[aria-label="Disponibles para activar"]');
        const lightningRow = [...section.querySelectorAll('li')].find((li) => li.textContent.startsWith('LIGHTNING'));
        const aplicar = [...lightningRow.querySelectorAll('button')].find((el) => el.textContent === 'Aplicar');
        await userEvent.click(aplicar);
        const card = screen.getByRole('group', { name: 'Aplicar LIGHTNING' });
        await expect.element(card).toBeVisible();
        await frame();
        const close = [...lightningRow.querySelectorAll('button')].find((el) => el.textContent === 'Cerrar');
        expect(close).toBeDefined();
        const cardEl = card.element();
        // The trigger stays on the row's line, right of the card's top; the card spans the row under it.
        expect(rect(close).bottom).toBeLessThanOrEqual(rect(cardEl).top + 0.5);
        expect(rect(close).right).toBeGreaterThan(rect(cardEl).right - 40);
        const price = screen.getByLabelText('Precio').element();
        const stock = screen.getByLabelText('Stock a reservar').element();
        const markup = cardEl.querySelector('output');
        expect(price.value).toBe('73558.15');
        // The shot shows the markup once the debounced lookup settles.
        await expect.poll(() => markup.textContent, { timeout: 3000 }).toBe('—');
        await frame();
        for (const el of [price, stock, markup, cardEl.querySelector('[role="note"]')]) {
          expect(rect(el).left).toBeGreaterThanOrEqual(rect(cardEl).left - 0.5);
          expect(rect(el).right).toBeLessThanOrEqual(rect(cardEl).right + 0.5);
        }
        if (width) {
          // Side by side, markup between price and stock.
          expect(rect(markup).left).toBeGreaterThan(rect(price).right);
          expect(rect(stock).left).toBeGreaterThan(rect(markup).right);
        } else {
          expect(rect(panel).width).toBeLessThanOrEqual(560 + 0.5);
          expect(rect(stock).top).toBeGreaterThan(rect(price).bottom);
        }
        expect(rect(cardEl).right).toBeLessThanOrEqual(rect(lightningRow).right + 0.5);
        const note = cardEl.querySelector('[role="note"]');
        expect(getComputedStyle(note).color).toBe(tokenColor('--tone-warning-fg'));
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        if (PRODUCT_SHOTS_DIR) {
          lightningRow.scrollIntoView({ block: 'start' });
          await frame();
          await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/s9-lightning-${variant}-${theme}.png`, element: panel });
        }
        screen.unmount();
      });
    }
  }
});

// The whole approved panel at once (S9 + S9b): the "Hay candidatas mejores" card above the tabs, the
// Promos sections and the LIGHTNING apply card open.
describe('Publicaciones ML panel, the whole S9 design (visual)', () => {
  const widthKey = 'split-panel-width:publicaciones-ml';
  afterEach(() => localStorage.removeItem(widthKey));

  for (const theme of THEMES) {
    for (const variant of ['wide', 'default']) {
      it(`1920x2700 ${theme} ${variant}: suggestion card, Promos sections and the LIGHTNING card fit the panel`, async () => {
        if (variant === 'wide') localStorage.setItem(widthKey, '1040');
        else localStorage.removeItem(widthKey);
        // Only the current price's markup is in the capture (-28,74%); the suggestion's is not, so it has none.
        promocionesAPI.getMarkupParaPrecio.mockImplementation((_mla, price) =>
          Promise.resolve({ data: { nuestro_markup: Number(price) === 59999 ? -28.74 : null } }),
        );
        const screen = await renderWithPanel({
          width: 1920,
          height: 2700,
          theme,
          tab: '',
          margin: true,
          promotions: S9_PROMOTIONS,
          rowExtra: { ...S9_ROW, hay_mejores_ofertas: true },
          detailExtra: { can_resync: true, can_change_status: true },
        });
        await expect.element(screen.getByRole('button', { name: 'Aplicar sugerencia' }).first()).toBeVisible();
        await expect.element(screen.getByText('MKP T1 CYBER MONDAY NOV').first()).toBeVisible();
        const panel = panelOf();
        const section = panel.querySelector('section[aria-label="Disponibles para activar"]');
        const lightningRow = [...section.querySelectorAll('li')].find((li) => li.textContent.startsWith('LIGHTNING'));
        await userEvent.click([...lightningRow.querySelectorAll('button')].find((el) => el.textContent === 'Aplicar'));
        const card = screen.getByRole('group', { name: 'Aplicar LIGHTNING' });
        await expect.element(card).toBeVisible();
        await expect.poll(() => card.element().querySelector('output').textContent, { timeout: 3000 }).toBe('—');
        await frame();
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        // The suggestion sits above the tab strip.
        const suggestion = screen.getByRole('button', { name: 'Aplicar sugerencia' }).first().element();
        expect(rect(suggestion).bottom).toBeLessThanOrEqual(rect(panel.querySelector('[role="tablist"]')).top);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/s9-completo-${variant}-${theme}.png`, element: panel });
        screen.unmount();
      });
    }
  }
});

// promos-markup-sell-in-out: the same panel with the markup with sell in / sell out next to every promo markup
// (rows, the suggestion card and its "Markup vigente" line, the LIGHTNING card). The figures are the S9 markups
// plus a sell out credit worth 6.4 points of markup, as the backend sends them.
describe('Publicaciones ML panel, promo markups with sell in / sell out (visual)', () => {
  const widthKey = 'split-panel-width:publicaciones-ml';
  const conSellInOut = (markup) => (markup == null ? null : Math.round((markup + 6.4) * 100) / 100);
  afterEach(() => localStorage.removeItem(widthKey));

  for (const theme of THEMES) {
    for (const variant of ['wide', 'default']) {
      it(`1920x2700 ${theme} ${variant}: the c/ sell in/out figure sits under each markup and fits the panel`, async () => {
        if (variant === 'wide') localStorage.setItem(widthKey, '1040');
        else localStorage.removeItem(widthKey);
        promocionesAPI.getMarkupParaPrecio.mockImplementation((_mla, price) => {
          const markup = Number(price) === 59999 ? -28.74 : -24.1;
          return Promise.resolve({ data: { nuestro_markup: markup, markup_sell_in_out: conSellInOut(markup) } });
        });
        const screen = await renderWithPanel({
          width: 1920,
          height: 2700,
          theme,
          tab: '',
          margin: true,
          promotions: S9_PROMOTIONS.map((p) => ({ ...p, markup_sell_in_out: conSellInOut(p.nuestro_markup) })),
          rowExtra: { ...S9_ROW, hay_mejores_ofertas: true },
          detailExtra: { can_resync: true, can_change_status: true },
        });
        await expect.element(screen.getByRole('button', { name: 'Aplicar sugerencia' }).first()).toBeVisible();
        await expect.element(screen.getByText(/Markup vigente ~ -28,74% · c\/ sell in\/out -22,34%/)).toBeVisible();
        const panel = panelOf();
        const section = panel.querySelector('section[aria-label="Disponibles para activar"]');
        const lightningRow = [...section.querySelectorAll('li')].find((li) => li.textContent.startsWith('LIGHTNING'));
        await userEvent.click([...lightningRow.querySelectorAll('button')].find((el) => el.textContent === 'Aplicar'));
        const card = screen.getByRole('group', { name: 'Aplicar LIGHTNING' });
        await expect.element(card).toBeVisible();
        await expect.poll(() => card.element().textContent, { timeout: 3000 }).toContain('c/ sell in/out -17.7%');
        await frame();
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/s9-sell-in-out-${variant}-${theme}.png`, element: panel });
        screen.unmount();
      });
    }
  }
});

// Columns sized by their content (pubml-tabla-columnas S1, S2, S5): the measured width of each figure column against
// what its header and widest value need, their alignment, and the Publicación column taking the room left.
const FIGURE_COLUMNS = [
  'precio',
  'unidades_7d',
  'unidades_30d',
  'units_trend',
  'markup',
  'markup_30d',
  'markup_trend',
  'facturado_30d',
  'total_gauss_30d',
  'last_sale',
  'ageing',
  'stock_erp',
  'stock_full',
  'stock_total',
];
const COLUMN_SLACK = 12;
// What a cell's or header's content needs on one line: a copy of it laid out at max-content inside the same cell
// (same classes, same inherited font), plus the cell's own horizontal padding.
const neededWidth = (cell) => {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;left:0;top:0;width:max-content;visibility:hidden;';
  for (const child of cell.childNodes) probe.appendChild(child.cloneNode(true));
  cell.appendChild(probe);
  const width = probe.getBoundingClientRect().width;
  probe.remove();
  const style = getComputedStyle(cell);
  return width + Number.parseFloat(style.paddingLeft) + Number.parseFloat(style.paddingRight);
};
const columnWidths = (scroller) =>
  Object.fromEntries(
    [...scroller.querySelectorAll('thead th[data-column]')].map((th) => [th.dataset.column, Math.round(rect(th).width)]),
  );
const LONG_TITLE =
  'Router Inalámbrico TP-Link Archer AX55 Wi-Fi 6 AX3000 Doble Banda Gigabit con OneMesh y HomeShield, Negro, Garantía Oficial';

describe('Publicaciones ML columns sized by their content (visual)', () => {
  beforeEach(() => {
    publicacionesMlAPI.items.mockReset();
    publicacionesMlAPI.variations.mockReset();
    try {
      localStorage.clear();
    } catch {
      // no storage: nothing saved
    }
  });

  // The app uses the system's fonts: a browser with a wider one (CI's runner, another OS) must not push a figure out
  // of its column. Wider letters stand in for that font here.
  it('1440x900 light: in a wider font every figure column grows to hold its values, none pokes out of its cell', async () => {
    const wider = document.createElement('style');
    wider.textContent = '[data-table-shell-scroller] td, [data-table-shell-scroller] th { letter-spacing: 0.12em; }';
    document.head.append(wider);
    try {
      const screen = await renderMarginPage({ width: 1440, height: 900, theme: 'light' });
      await frame();
      const scroller = scrollerOf();
      const widths = columnWidths(scroller);
      expect(widths.facturado_30d).toBeGreaterThan(140);
      expect(overflowingCells(scroller)).toEqual([]);
      expect(wrapped(scroller.querySelectorAll('tbody [data-money]'))).toEqual([]);
      screen.unmount();
    } finally {
      wider.remove();
    }
  });

  // Before/after captures for the PR (only with VITE_PUBLICACIONES_SHOTS_DIR): the list, the Producto view, the tree.
  for (const theme of THEMES) {
    it.runIf(PRODUCT_SHOTS_DIR)(`1440x900 ${theme}: captures of the three views`, async () => {
      let screen = await renderMarginPage({ width: 1440, height: 1800, theme });
      await frame();
      await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/tabla-lista-1440-${theme}.png`, element: scrollerOf() });
      // The stock filter chips, above the table.
      await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/filtros-stock-1440-${theme}.png`, element: document.querySelector('[role="group"][aria-label="Filtrar por stock"]') });
      // The figures past the first screen (Resultado, Rotación, Stock): the same table scrolled to its right end.
      scrollerOf().scrollTo({ left: scrollerOf().scrollWidth });
      await frame();
      await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/tabla-lista-derecha-1440-${theme}.png`, element: scrollerOf() });
      screen.unmount();
      screen = await renderProducts({ width: 1440, height: 1800, theme });
      await frame();
      await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/tabla-producto-1440-${theme}.png`, element: scrollerOf() });
      // A product opened into its publications: the parent row and its children, column by column.
      await screen.getByRole('button', { name: /Abrir Router Archer AX55/ }).click();
      await expect.element(screen.getByText('Router TP-Link Archer AX55 por color')).toBeVisible();
      await frame();
      await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/tabla-producto-abierta-1440-${theme}.png`, element: scrollerOf() });
      screen.unmount();
      // The Agrupado tree opened down to a product's publications.
      screen = await renderTree({ width: 1440, height: 1800, theme });
      await openToLeaf(screen);
      await frame();
      await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/tabla-agrupado-1440-${theme}.png`, element: scrollerOf() });
      screen.unmount();
    });
  }

  for (const theme of THEMES) {
    it(`1440x900 ${theme}: figure columns no wider than their content, centered with their header`, async () => {
      // Four-digit Full and own stock, as the units columns already carry (1.234): the widest figure each column holds.
      const wide = MARGIN_RESPONSE.items.map((item, i) =>
        i === 2 ? { ...item, stock: { ...item.stock, available: 2468, full: 1234, own: 1234 } } : item,
      );
      const screen = await renderMarginPage({ width: 1440, height: 900, theme, response: { ...MARGIN_RESPONSE, items: wide } });
      await frame();
      const scroller = scrollerOf();
      const widths = columnWidths(scroller);
      const visible = FIGURE_COLUMNS.filter((key) => widths[key] != null);
      expect(visible.length).toBeGreaterThan(8);
      const tooWide = [];
      const misaligned = [];
      for (const key of visible) {
        const header = scroller.querySelector(`thead th[data-column="${key}"]`);
        const cells = [...scroller.querySelectorAll(`tbody td[data-column="${key}"]`)];
        const need = Math.max(neededWidth(header), ...cells.map(neededWidth));
        if (widths[key] > need + COLUMN_SLACK) tooWide.push(`${key}: ${widths[key]} > ${Math.round(need)} + ${COLUMN_SLACK}`);
        const align = getComputedStyle(header).textAlign;
        const cellAligns = new Set(cells.map((td) => getComputedStyle(td).textAlign));
        if (align !== 'center' || cellAligns.size !== 1 || !cellAligns.has('center')) {
          misaligned.push(`${key}: header ${align}, cells ${[...cellAligns].join('/')}`);
        }
      }
      expect(tooWide).toEqual([]);
      expect(misaligned).toEqual([]);
      // A centered stack centers its lines too (a markup range over its "(parcial)" note, an ERP stock).
      const stacks = [...scroller.querySelectorAll('tbody td[data-column="markup"] > div, tbody td[data-column="stock_erp"] > div')];
      for (const stack of stacks) expect(getComputedStyle(stack).alignItems).toBe('center');
      // An ERP stock at zero reads in the danger tone (its note is the tooltip).
      const erpZero = [...scroller.querySelectorAll('tbody td[data-column="stock_erp"] [title="Sin stock ERP"] span')][0];
      expect(getComputedStyle(erpZero).color).toBe(tokenColor('--tone-danger-fg'));
      // Stock reads like Ventas: similar figures, no wider columns.
      const ventas = Math.max(widths.unidades_7d, widths.unidades_30d);
      for (const key of ['stock_erp', 'stock_full', 'stock_total']) {
        expect(widths[key], key).toBeLessThanOrEqual(ventas + 1);
      }
      expect(overflowingCells(scroller)).toEqual([]);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/columnas-1440-${theme}.png` });
      screen.unmount();
    });

    it(`1440x900 ${theme}: Publicación takes the room left and reads a long title whole`, async () => {
      canSeeMargin = true;
      publicacionesMlAPI.items.mockResolvedValue({
        data: { ...MARGIN_RESPONSE, items: MARGIN_RESPONSE.items.map((item, i) => (i === 1 ? { ...item, title: LONG_TITLE } : item)) },
      });
      publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
      await page.viewport(1440, 900);
      setTheme(theme);
      const screen = await render(
        <MemoryRouter initialEntries={['/ml-publicaciones']}>
          <Shell>
            <PublicacionesML />
          </Shell>
        </MemoryRouter>,
      );
      await expect.element(screen.getByText('MLA1100000005')).toBeVisible();
      await frame();
      const scroller = scrollerOf();
      const widths = columnWidths(scroller);
      // Before: 360 px from <colgroup>, stretched by the table's leftover share.
      expect(widths.titulo).toBeGreaterThan(400);
      const title = [...scroller.querySelectorAll('tbody td[data-column="titulo"] span')].find((el) => el.textContent === LONG_TITLE);
      expect(title).toBeDefined();
      expect(title.scrollHeight).toBeLessThanOrEqual(title.clientHeight + 1);
      expect(title.title).toContain(LONG_TITLE);
      screen.unmount();
    });

    it(`1440x900 ${theme}: the Publicación grip widens the column and the width survives a reload`, async () => {
      const screen = await renderMarginPage({ width: 1440, height: 900, theme });
      await frame();
      const scroller = scrollerOf();
      const widthsBefore = columnWidths(scroller);
      const before = widthsBefore.titulo;
      const grip = screen.getByRole('separator', { name: 'Ajustar ancho de Publicación' });
      await expect.element(grip).toBeVisible();
      grip.element().focus();
      for (let i = 0; i < 10; i += 1) await userEvent.keyboard('{ArrowRight}');
      await frame();
      const { titulo: after, ...others } = columnWidths(scroller);
      expect(after).toBeGreaterThanOrEqual(before + 90);
      // Its neighbours keep their width: the table grows, nothing else is squeezed.
      const { titulo: _before, ...othersBefore } = widthsBefore;
      expect(others).toEqual(othersBefore);
      screen.unmount();
      await new Promise((resolve) => setTimeout(resolve, 0));
      const again = await renderMarginPage({ width: 1440, height: 900, theme });
      await frame();
      expect(Math.abs(columnWidths(scrollerOf()).titulo - after)).toBeLessThanOrEqual(1);
      again.unmount();
    });

    it(`1440x900 ${theme}: the Agrupado tree's first column has its own grip and key`, async () => {
      const screen = await renderTree({ width: 1440, height: 900, theme });
      await frame();
      const before = columnWidths(scrollerOf()).titulo;
      const grip = screen.getByRole('separator', { name: 'Ajustar ancho de Publicación' });
      grip.element().focus();
      for (let i = 0; i < 5; i += 1) await userEvent.keyboard('{ArrowRight}');
      await frame();
      const after = columnWidths(scrollerOf()).titulo;
      expect(after).toBeGreaterThanOrEqual(before + 40);
      screen.unmount();
      expect(JSON.parse(localStorage.getItem('pubml:colsizing:agrupado') ?? '{}').titulo).toBe(after);
      expect(localStorage.getItem('pubml:colsizing:lista')).toBeNull();
    });

    it(`1440x900 ${theme}: the Producto view's first column has its own grip and reads a long product name whole`, async () => {
      const screen = await renderProducts({ width: 1440, height: 900, theme });
      await frame();
      const scroller = scrollerOf();
      const before = columnWidths(scroller).titulo;
      expect(before).toBeGreaterThan(400);
      const name = [...scroller.querySelectorAll('tbody td[data-column="titulo"] [title]')].find((el) =>
        el.textContent.startsWith('Sistema Mesh Deco X20'),
      );
      expect(name).toBeDefined();
      expect(name.scrollWidth).toBeLessThanOrEqual(name.clientWidth + 1);
      expect(name.scrollHeight).toBeLessThanOrEqual(name.clientHeight + 1);
      const grip = screen.getByRole('separator', { name: 'Ajustar ancho de Producto' });
      grip.element().focus();
      for (let i = 0; i < 5; i += 1) await userEvent.keyboard('{ArrowRight}');
      await frame();
      const after = columnWidths(scroller).titulo;
      expect(after).toBeGreaterThanOrEqual(before + 40);
      if (PRODUCT_SHOTS_DIR) await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/columnas-producto-1440-${theme}.png` });
      screen.unmount();
      // Saved under the Producto view's own key (written at the latest on unmount): the list keeps its width.
      expect(JSON.parse(localStorage.getItem('pubml:colsizing:producto') ?? '{}').titulo).toBe(after);
      expect(localStorage.getItem('pubml:colsizing:lista')).toBeNull();
    });
  }
});
