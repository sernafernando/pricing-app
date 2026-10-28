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
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { contrastRatio, setTheme, tokenColor } from './visualHelpers';
import PublicacionesML from '../../pages/PublicacionesML';
import { equiposAPI, mlItemOverridesAPI, offsetsGananciaAPI, preciosAPI, productosPropiosAPI, promocionesAPI, publicacionesMlAPI, pxqAPI } from '../../services/api';
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
vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    // Only the prearmadas badge posts here: two ready for every product asked.
    post: vi.fn((url, body) =>
      Promise.resolve({ data: { stats: Object.fromEntries((body?.items ?? []).map(({ item_id }) => [item_id, { exact: 2, upgrade: 0 }])) } }),
    ),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  pxqAPI: { getLive: vi.fn(), getMarkup: vi.fn(), createTier: vi.fn(), updateTier: vi.fn(), deleteTier: vi.fn(), sync: vi.fn(), adoptLive: vi.fn() },
  publicacionesMlAPI: { items: vi.fn(), products: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), events: vi.fn(), history: vi.fn(), enqueue: vi.fn(), setItemStatus: vi.fn(), statusItemIds: vi.fn(), statusBulk: vi.fn(), kpis: vi.fn(), stats: vi.fn(() => Promise.resolve({ data: { stats: { total: 40, con_stock: 30, con_precio: 35, con_stock_sin_precio: 3, nuevos: 5, nuevos_sin_precio: 2, oferta_sin_rebate: 4 }, can_see_margin: false } })), productIds: vi.fn(() => Promise.resolve({ data: { item_ids: [4101, 4102], count: 2, sin_producto: 1 } })), productLinks: vi.fn(() => Promise.resolve({ data: { units: [] } })), setProductLink: vi.fn(), setProductLinkNone: vi.fn(), revertProductLinkAuto: vi.fn(), searchProducts: vi.fn() },
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
  promocionesAPI: { getPromocionesItem: vi.fn(), refreshItemPromociones: vi.fn(), confirmarSinPromosML: vi.fn(), getCompetenciaCatalogo: vi.fn(), refreshCompetenciaCatalogo: vi.fn() },
  productosAPI: {
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
              precio_pvp: 239999, markup_pvp: 31.9 },
            { item_id: 4102, precio_lista_ml: 45999, markup: -3.2, mejor_oferta_precio: 41399, mejor_oferta_markup: -0.098,
              mejor_oferta_porcentaje_rebate: 12.5, mejor_oferta_monto_rebate: 5174.88, mejor_oferta_fecha_hasta: '2026-11-30',
              mejor_oferta_pvp_seller: 47999 },
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
const MANY = Array.from({ length: 50 }, (_, i) => ({
  ...ITEMS[i % ITEMS.length],
  item_id: `MLA${1100000100 + i}`,
  erp_stock: { quantity: ERP_QUANTITIES[i % ERP_QUANTITIES.length] },
  metrics: METRICS[i % METRICS.length],
}));
const RESPONSE = {
  ...ITEMS_RESPONSE,
  items: MANY,
  facets: { ...FACETS, stock: { ...FACETS.stock, erp_sin_stock: 9 } },
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

const renderPage = async ({ width, height, theme }) => {
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  window.scrollTo(0, 0);
  const screen = await render(
    <MemoryRouter initialEntries={['/ml-publicaciones']}>
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
const overflowingCells = (root) => {
  const offenders = [];
  for (const td of root.querySelectorAll('tbody td')) {
    const box = td.getBoundingClientRect();
    for (const child of td.querySelectorAll('*')) {
      const r = child.getBoundingClientRect();
      if (r.width === 0) continue;
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
const wrapped = (elements) =>
  [...elements]
    .filter((el) => el.getClientRects().length > 1 || rect(el).height > lineHeightOf(el) * 1.6)
    .map((el) => el.textContent.trim());

// Every suite shows the strip unless it says otherwise.
beforeEach(() => {
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
        const figures = [...scroller.querySelectorAll('td[data-align="right"] span')].filter((el) =>
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

      it(`${width}x${height} ${theme}: the stat cards keep every label and figure on one line, inside their card`, async () => {
        const screen = await renderPage({ width, height, theme });
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

      it(`${width}x${height} ${theme}: our own, Full and ERP stock sit in three columns under STOCK, headers and figures on one line`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        const headers = ['stock_propio', 'stock_full', 'stock_erp'].map((key) => scroller.querySelector(`thead th[data-column="${key}"]`));
        expect(headers.map((th) => th.textContent)).toEqual(['Propio', 'Full', 'ERP']);
        const group = [...scroller.querySelectorAll('thead th[scope="colgroup"]')].find((th) => th.textContent === 'Stock');
        expect(group.colSpan).toBe(3);
        expect(wrapped(headers.map((th) => th.querySelector('button')))).toEqual([]);
        // Never the available sum: the first fixture row has 34 available, 20 Full and 14 of our own.
        const first = scroller.querySelector('tbody tr');
        expect(first.querySelector('td[data-column="stock_propio"]').textContent).toBe('14');
        expect(first.querySelector('td[data-column="stock_full"]').textContent).toBe('20');
        const notes = [...scroller.querySelectorAll('tbody td span')].filter((el) => el.textContent === 'Sin stock ERP');
        expect(notes.length).toBeGreaterThan(0);
        expect(wrapped(notes)).toEqual([]);
        expect(overflowingCells(scroller)).toEqual([]);
        await expect.element(screen.getByRole('button', { name: /Sin stock ERP/ })).toBeVisible();
        await expect.element(screen.getByRole('button', { name: /Sin stock propio/ })).toBeVisible();
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the grouped header reads like Métricas ML and stays pinned above the rows`, async () => {
        const screen = await renderPage({ width, height, theme });
        const scroller = scrollerOf();
        const groups = [...scroller.querySelectorAll('thead th[scope="colgroup"]')];
        // Productos' price columns (S11) lead, right after Precio.
        expect(groups.map((th) => th.textContent)).toEqual(['Precios de Productos', 'Ventas (unidades)', 'Resultado financiero', 'Rotación', 'Stock']);
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
        const ventas = rect(groups[1]);
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

const renderMarginPage = async ({ width, height, theme }) => {
  canSeeMargin = true;
  publicacionesMlAPI.items.mockResolvedValue({ data: MARGIN_RESPONSE });
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  window.scrollTo(0, 0);
  const screen = await render(
    <MemoryRouter initialEntries={['/ml-publicaciones']}>
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
        const ranges = [...scroller.querySelectorAll('tbody td[data-align="right"] span')].filter((el) => /%/.test(el.textContent) && !/parcial/.test(el.textContent));
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
        const figures = subRows.flatMap((row) => [...row.querySelectorAll('td[data-align="right"] span')]).filter((el) => /^[-\d.,%]+$/.test(el.textContent.trim()));
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
const CATEGORY = makeNode({ kind: 'categoria', key: 'ROUTERS', label: 'ROUTERS', count: 90, params: { marcas: 'TP-LINK', categorias: 'ROUTERS' }, negative_count: 4, markup_min: -6.5, markup_max: 38.2 });
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
      const figures = [...scroller.querySelectorAll('tbody td[data-align="right"] span')].filter((el) => /^[-\d.,%\s–—]+$/.test(el.textContent.trim()));
      expect(figures.length).toBeGreaterThan(0);
      expect(wrapped(figures)).toEqual([]);
      expect(overflowingCells(scroller)).toEqual([]);
      const negatives = [...rowWith(scroller, 'TP-LINK').querySelectorAll('td[data-align="right"] span')].find((el) => el.textContent === '4');
      expect(getComputedStyle(negatives).color).toBe(tokenColor('--tone-danger-fg'));
      const clean = [...rowWith(scroller, 'EPSON').querySelectorAll('td[data-align="right"] span')].find((el) => el.textContent === '0');
      expect(getComputedStyle(clean).color).not.toBe(tokenColor('--tone-danger-fg'));
      screen.unmount();
    });

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
        const figures = [...scroller.querySelectorAll('tbody td[data-align="right"] span')].filter((el) => el.textContent.trim());
        expect(figures.length).toBeGreaterThan(0);
        expect(wrapped(figures)).toEqual([]);
        expect(overflowingCells(scroller)).toEqual([]);
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
      it(`${width}x${height} ${theme}: the PPP and sell in lines stay inside the cost cell of a product row`, async () => {
        const rows = [{ ...PRODUCT_ROWS[0], ...COST_LINES }, ...PRODUCT_ROWS.slice(1)];
        const screen = await renderProducts({ width, height, theme, rows });
        await screen.getByRole('button', { name: 'Columnas' }).click();
        await screen.getByRole('checkbox', { name: 'Costo' }).click();
        await screen.getByRole('button', { name: 'Columnas' }).click();
        const row = rowWith(scrollerOf(), 'Router Archer AX55');
        const cell = [...row.querySelectorAll('td')].find((td) => td.textContent.includes('USD 45,50'));
        expect(cell.textContent).toContain('ppp: USD $41.20');
        expect(cell.textContent).toContain('c/ sell in: ARS $63000.00');
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
        await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
        await expect.element(screen.getByRole('complementary', { name: 'Detalle del producto' }).getByText('Cifras')).toBeVisible();
        const panel = document.querySelector('[data-split-panel]');
        await expect.element(screen.getByRole('button', { name: /Router TP-Link Archer AX55 por color/ })).toBeVisible();
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
        const figures = [...panel.querySelectorAll('dd')].filter((el) => el.textContent.trim());
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
        await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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
        await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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
        await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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
          await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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
      it(`${width}x${height} ${theme}: the product's prearmadas badge fits in the panel header`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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
          await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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
    }

    for (const { width, height } of VIEWPORTS) {
      it(`${width}x${height} ${theme}: the product's instalment settings and their edit fit under its prices`, async () => {
        preciosAPI.obtenerProducto.mockResolvedValue({
          data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, sell_in_out: SELL_IN_OUT, recalcular_cuotas_auto: false, markup_adicional_cuotas_custom: 6.5, markup_adicional_cuotas_pvp_custom: null },
        });
        offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
        try {
          const screen = await renderProducts({ width, height, theme });
          await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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

      it(`${width}x${height} ${theme}: the product's ban and its confirmation fit inside the panel`, async () => {
        const screen = await renderProducts({ width, height, theme });
        await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
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
          await screen.getByRole('table', { name: /por producto/ }).getByText('Router Archer AX55').click();
          const aside = screen.getByRole('complementary', { name: 'Detalle del producto' });
          await aside.getByRole('tab', { name: 'Precios' }).click();
          await expect.element(aside.getByText('$ 64.000,00')).toBeVisible();
          const panel = document.querySelector('[data-split-panel]');
          const box = rect(panel);
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
          expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
          const tabs = [...panel.querySelectorAll('[role="tab"]')];
          expect(tabs.map((tab) => tab.textContent)).toEqual(['Resumen', 'Precios', 'Cambios']);
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
];

// The detail panel open beside the table (publicaciones-ml-vista P13a.T5, S61.1/S62.1).
const SELECTED = MANY[0].item_id;
const PANEL_VIEWPORTS = [
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
];

const renderWithPanel = async ({ width, height, theme, margin = false, tab = '', linked = false, detailExtra = {} }) => {
  canSeeMargin = margin;
  const base = { ...MANY[0], is_full: true, variations_count: 3 };
  publicacionesMlAPI.items.mockResolvedValue({
    data: margin ? { ...MARGIN_RESPONSE, items: [{ ...base, markup: MARGIN_ITEMS[1].markup }, ...MANY.slice(1)] } : { ...RESPONSE, items: [base, ...MANY.slice(1)] },
  });
  const detail = linked ? (margin ? DETAIL_LINKED_MARGIN : DETAIL_LINKED) : margin ? DETAIL_RESPONSE_MARGIN : DETAIL_RESPONSE;
  publicacionesMlAPI.detail.mockResolvedValue({ data: { ...detail, ...detailExtra, row: base } });
  publicacionesMlAPI.events.mockResolvedValue({ data: EVENTS_RESPONSE });
  publicacionesMlAPI.history.mockImplementation((itemId, params) =>
    Promise.resolve({ data: params?.tecnicos ? HISTORY_TECNICOS_RESPONSE : HISTORY_RESPONSE }),
  );
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
  promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
  promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: PROMOTIONS } });
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
        expect(tabs.map((tab) => tab.textContent)).toEqual(['Resumen', 'Datos', 'Variaciones', 'Full', 'Promos', 'Eventos', 'Historial', 'Producto']);
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

      it(`${width}x${height} ${theme}: the money, stock and dates of Resumen stay on one line`, async () => {
        const screen = await renderWithPanel({ width, height, theme });
        const values = [...panelOf().querySelectorAll('dd')].filter((el) => /^[\d.,/: ]+(ARS|%)?$/.test(el.textContent.trim()));
        expect(values.length).toBeGreaterThan(4);
        expect(wrapped(values)).toEqual([]);
        screen.unmount();
      });
    }
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
      it(`${width}x${height} ${theme}: the Promociones tab lists the promotions inside the panel`, async () => {
        const screen = await renderWithPanel({ width, height, theme, tab: 'promociones' });
        await expect.element(screen.getByText('Oferta del día')).toBeVisible();
        const panel = panelOf();
        const box = rect(panel);
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        const rows = [...panel.querySelectorAll('[role="tabpanel"] li')];
        expect(rows).toHaveLength(2);
        for (const el of rows.flatMap((row) => [row, ...row.querySelectorAll('*')])) {
          const r = rect(el);
          if (r.width === 0) continue;
          expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(box.right + 0.5);
        }
        screen.unmount();
      });
    }
  }

  // Precios: cost card, one accented card per list, markup chips by the app scale (markupTone).
  for (const { width, height } of PANEL_VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the Precios tab shows cost with offset and with sell in, every markup as toned chips and fits the panel`, async () => {
        preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, sell_in_out: SELL_IN_OUT } });
        offsetsGananciaAPI.vigentes.mockResolvedValue({
          data: [{ id: 7, marca: 'TP-LINK', tipo_offset: 'porcentaje_costo', porcentaje: 10, descripcion: 'Rebate TP-Link con una descripción larga', grupo_id: null }],
        });
        try {
          const screen = await renderWithPanel({ width, height, theme, tab: 'precios', linked: true, margin: true });
          await expect.element(screen.getByText('$ 57.600,00')).toBeVisible();
          const panel = panelOf();
          expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);

          const facts = panel.querySelector('[aria-label="Referencias del producto"]');
          expect(getComputedStyle(facts).backgroundColor).toBe(tokenColor('--tone-neutral-bg'));

          const groups = [...panel.querySelectorAll('section[data-list]')];
          expect(groups.map((g) => getComputedStyle(g).borderLeftColor)).toEqual([
            tokenColor('--tone-info-fg'),
            tokenColor('--tone-purple-fg'),
            tokenColor('--tone-warning-fg'),
          ]);

          const row = (label) => [...panel.querySelectorAll('tbody tr')].find((tr) => (tr.querySelector('th').getAttribute('aria-label') ?? tr.querySelector('th').textContent) === label);
          const chip = (label, col) => row(label).querySelector(`[data-col="${col}"] [data-tone]`);
          expect(getComputedStyle(chip('Clásica', 'markup')).color).toBe(tokenColor('--tone-success-fg'));
          expect(getComputedStyle(chip('12 cuotas', 'markup')).color).toBe(tokenColor('--tone-danger-fg'));
          expect(getComputedStyle(chip('12 cuotas', 'markup')).backgroundColor).toBe(tokenColor('--tone-danger-bg'));
          expect(chip('Clásica', 'markup-offset').textContent).toBe('31,56%');
          expect(chip('Clásica', 'markup-sell-in-out').textContent).toBe('28,80%');
          expect(facts).toHaveTextContent('$ 60.000,00');
          // Readable on the card in both themes.
          const card = getComputedStyle(groups[0]).backgroundColor;
          for (const label of ['Clásica', '12 cuotas']) {
            expect(contrastRatio(getComputedStyle(chip(label, 'markup')).color, card)).toBeGreaterThanOrEqual(3);
          }

          // Figures on one line. Whether every list fits the panel's width depends on the typeface the host
          // resolves (the suite loads none, see pxqPanel.visual.test.jsx): the CI runner's fallback is about a
          // quarter wider than a desktop's, so that fit is checked by hand on a screenshot, not here.
          const figures = [...panel.querySelectorAll('tbody td')].filter((td) => /\d/.test(td.textContent));
          expect(figures.filter((td) => getComputedStyle(td).whiteSpace !== 'nowrap').map((td) => td.textContent)).toEqual([]);
          expect(wrapped(panel.querySelectorAll('section[data-list] [data-tone]'))).toEqual([]);
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
        const screen = await renderWithPanel({ width: 1366, height: 768, theme, tab: 'promociones' });
        const strip = panelOf().querySelector('[role="tablist"]');
        const tabs = [...strip.querySelectorAll('[role="tab"]')];
        expect(strip.scrollWidth).toBeGreaterThan(strip.clientWidth + 1);
        expect(new Set(tabs.map((tab) => Math.round(rect(tab).top))).size).toBe(1);
        const open = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true');
        expect(open.textContent).toBe('Promos');
        expect(rect(open).left).toBeGreaterThanOrEqual(rect(strip).left - 0.5);
        expect(rect(open).right).toBeLessThanOrEqual(rect(strip).right + 0.5);
        screen.unmount();
      } finally {
        squeeze.remove();
      }
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
      // With a product checked, the Pintar button joins the band and still fits it.
      await screen.getByRole('checkbox', { name: /Seleccionar el producto de/ }).first().click();
      await expect.element(screen.getByRole('button', { name: 'Pintar 1 producto' })).toBeVisible();
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
      if (PRODUCT_SHOTS_DIR) {
        window.scrollTo(0, 0);
        await page.screenshot({ path: `${PRODUCT_SHOTS_DIR}/paint-menu-1366-${theme}.png` });
      }
      screen.unmount();
    });
  }

  for (const theme of ['light', 'dark']) {
    it(`1366x768 ${theme}: a price edited in place keeps its input inside the cell`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme });
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
      const screen = await renderPage({ width: 1366, height: 768, theme });
      await expect.element(screen.getByText('Hasta 30/11').first()).toBeVisible();
      const lines = [...document.querySelectorAll('[data-offer-detail]')];
      expect(lines.map((line) => line.textContent).slice(0, 4)).toEqual(['Aporte 12,50%', 'Rebate $ 5.174,88', 'Hasta 30/11', 'PVP $ 47.999,00']);
      const cell = lines[0].closest('td');
      const cellBox = cell.getBoundingClientRect();
      for (const line of lines.slice(0, 4)) {
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
    it(`1366x768 ${theme}: the rebate and web transfer editors open inside their cell, every control in view`, async () => {
      const screen = await renderPage({ width: 1366, height: 768, theme });
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
      const screen = await renderPage({ width: 1366, height: 768, theme });
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
      const all = screen.getByRole('checkbox', { name: 'Seleccionar los productos de la página' });
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
