/**
 * Publicaciones ML on a phone (mobile-metricas-pubml T2, S2, S5, S7) -- the real page, real CSS, real Chromium, at
 * 390x844 in both themes: the cards, the filters sheet and the publication panel full screen.
 *  - nothing is wider than the screen: the page never scrolls sideways;
 *  - every button of the header, the chips and the list is at least 44px tall;
 *  - the panel covers the whole screen, with "Publicaciones" to go back.
 *
 *   VITE_PUBLICACIONES_PHONE_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual publicacionesMlPhone   (also saves screenshots)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme, tokenColor } from './visualHelpers';
import PublicacionesML from '../../pages/PublicacionesML';
import { promocionesAPI, publicacionesMlAPI } from '../../services/api';
import { FACETS, ITEMS, ITEMS_RESPONSE, KPIS_RESPONSE_MARGIN, MARKUP_BREAKDOWN, makeDetail } from './publicacionesMlFixtures';


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

const SHOTS_DIR = import.meta.env.VITE_PUBLICACIONES_PHONE_SHOTS_DIR;
const shot = async (name, element) => SHOTS_DIR && page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, ...(element && { element }) });

// The list's rows with Métricas' figures, their ERP stock and markup, as a user with every permission sees them.
const FIGURES = [
  { units_30d: 14, ageing_days: 12, erp: 791, markup: 12.7 },
  { units_30d: 61, ageing_days: 41, erp: 0, markup: -2.1 },
  { units_30d: 0, ageing_days: null, erp: 0, markup: 21.3 },
  { units_30d: 3, ageing_days: 135, erp: 12500, markup: null },
];
const PHONE_ITEMS = ITEMS.map((item, index) => {
  const { units_30d, ageing_days, erp, markup } = FIGURES[index];
  return {
    ...item,
    title: item.title ?? 'Publicación sin título en Mercado Libre',
    status: item.status ?? 'active',
    metrics: { units_7d: 1, units_30d, ageing_days },
    erp_stock: { quantity: erp },
    markup: markup == null ? null : { min: markup, max: markup, any_negative: markup < 0, partial: 0 },
  };
});

// The design's publication (PubDetalle): a USD cost with its sell in, the stock total, the 30-day sales, and a
// publication that can be paused and resynced. The cost comes in its own currency as the backend sends it (#2216).
const DETAIL_ROW = { ...PHONE_ITEMS[0], stock_total: 791, sales_30d: { units: 14, gross: 709755 } };
const PHONE_DETAIL = makeDetail({
  row: DETAIL_ROW,
  markup_breakdown: { ...MARKUP_BREAKDOWN, moneda_costo: 'USD', costo: 17.04, tipo_cambio: 1050 },
  sell_in_out: {
    sell_in: {
      compra_item_id: 7,
      descuento_unit: 640.5,
      costo: 17251.5,
      unidades_restantes: 140,
      moneda_costo: 'USD',
      costo_moneda: 16.43,
      descuento_unit_moneda: 0.61,
    },
    sell_out: null,
    markups_sell_in: {},
    markups_sell_in_out: {},
  },
  can_resync: true,
  can_change_status: true,
});

// The app's main area on a phone: the fixed TopBar above, 16px around, no sidebar.
const Shell = ({ children }) => (
  <div data-shell style={{ padding: 'calc(var(--cf-topbar-height) + 16px) 16px 16px' }}>
    {children}
  </div>
);

const renderPhone = async ({ theme, entry = '/ml-publicaciones' }) => {
  await page.viewport(390, 844);
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
  await expect.element(screen.getByText('Router TP-Link Archer AX55', { exact: false }).first()).toBeVisible();
  return screen;
};

const noSidewaysScroll = () => expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390);

const shortTargets = (root) =>
  [...root.querySelectorAll('button, select, input')]
    .filter((el) => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height < 44)
    .map((el) => el.getAttribute('aria-label') || el.textContent.trim().slice(0, 30) || el.tagName);

beforeEach(() => {
  canSeeMargin = true;
  canSeeKpis = true;
  publicacionesMlAPI.items.mockResolvedValue({ data: { ...ITEMS_RESPONSE, items: PHONE_ITEMS, can_see_margin: true, facets: FACETS } });
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE_MARGIN });
  publicacionesMlAPI.detail.mockResolvedValue({ data: PHONE_DETAIL });
  promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
  promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
});

describe.each(['light', 'dark'])('Publicaciones ML at 390x844 (%s)', (theme) => {
  it('shows the cards, fits the screen and keeps every touch target at 44px', async () => {
    await renderPhone({ theme });
    expect(document.querySelector('table')).toBeNull();
    noSidewaysScroll();
    const header = document.querySelector('header');
    const list = document.querySelector('section[aria-label="Publicaciones"]');
    expect(shortTargets(header)).toEqual([]);
    expect(shortTargets(list)).toEqual([]);
    for (const card of list.querySelectorAll('button[class*="card"]')) {
      expect(card.getBoundingClientRect().right).toBeLessThanOrEqual(390 - 16 + 0.5);
    }
    await shot(`pubml-phone-lista-${theme}`);
  });

  it('opens the filters as a bottom sheet over the page', async () => {
    const screen = await renderPhone({ theme });
    await userEvent.click(screen.getByRole('button', { name: /^Filtros/ }));
    const sheet = screen.getByRole('dialog', { name: 'Filtros' });
    await expect.element(sheet).toBeVisible();
    const box = sheet.element().getBoundingClientRect();
    expect(box.bottom).toBeCloseTo(844, 0);
    expect(box.width).toBeCloseTo(390, 0);
    noSidewaysScroll();
    // "Limpiar" beside the close button, and the team button with its word (no orphan icon).
    await expect.element(sheet.getByRole('button', { name: 'Limpiar' })).toBeVisible();
    await expect.element(sheet.getByRole('button', { name: 'Equipos' })).toHaveTextContent('Equipos');
    await shot(`pubml-phone-filtros-${theme}`);
  });

  it('opens a publication full screen', async () => {
    const screen = await renderPhone({ theme, entry: '/ml-publicaciones?sel=MLA1100000001&tab=resumen' });
    const panel = screen.getByRole('complementary', { name: 'Detalle de la publicación' });
    await expect.element(panel.getByRole('button', { name: 'Publicaciones' })).toBeVisible();
    const box = panel.element().getBoundingClientRect();
    expect([box.left, box.top, box.width, box.height]).toEqual([0, 0, 390, 844]);
    noSidewaysScroll();
    // The desktop header's four cards, the cost in its own currency.
    const figures = panel.element().querySelectorAll('[aria-label="Cifras de la publicación"] dt');
    expect([...figures].map((dt) => dt.textContent.trim())).toEqual(['Precio', 'Costo', 'Stock', 'Ventas 30 días']);
    expect(panel.element().querySelector('[aria-label="Cifras de la publicación"]').textContent).toContain('USD 17,04');
    // The top bar's icons: Mercado Libre and "⋯" with the seller panel's links.
    await expect.element(panel.getByRole('link', { name: 'Ver en Mercado Libre' })).toBeVisible();
    await expect.element(panel.getByRole('button', { name: /^Más acciones/ })).toBeVisible();
    // Pausar and Resincronizar side by side, at the bottom of the screen.
    const pause = panel.getByRole('button', { name: 'Pausar' }).element().getBoundingClientRect();
    const resync = panel.getByRole('button', { name: 'Resincronizar' }).element().getBoundingClientRect();
    expect(pause.top).toBeCloseTo(resync.top, 0);
    expect(pause.right).toBeLessThanOrEqual(resync.left);
    const footer = panel.element().querySelector('footer').getBoundingClientRect();
    expect(footer.bottom).toBeCloseTo(844, 0);
    expect(Math.min(pause.height, resync.height)).toBeGreaterThanOrEqual(44);
    // Both in the quiet outline: no fill, a thin grey border, the secondary ink.
    for (const name of ['Pausar', 'Resincronizar']) {
      const style = getComputedStyle(panel.getByRole('button', { name }).element());
      expect(style.backgroundColor, name).toBe('rgba(0, 0, 0, 0)');
      expect(style.borderTopColor, name).toBe(tokenColor('--cf-border-default'));
      expect(style.color, name).toBe(tokenColor('--cf-text-secondary'));
    }
    await shot(`pubml-phone-detalle-${theme}`, panel.element());
  });

  it('Ver competencia comes open on a catalog listing and stacks under the promos, with no sideways scroll', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: { ...PHONE_DETAIL, row: { ...DETAIL_ROW, catalog_listing: true } } });
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: {
        fetch_status: 'ok',
        fecha_consulta: '2026-11-13T12:00:00Z',
        our_price: 98500,
        competitor_count: 2,
        same_bucket: [
          { item_id: 'MLA1999000001', seller_nickname: 'DISTRIBUIDORA DE REDES DEL LITORAL SRL', price: 96999, markup: 10.42 },
          { item_id: 'MLA1999000002', seller_nickname: 'OTRO VENDEDOR', price: 99990, markup: 14.1 },
        ],
        undercutting: [],
      },
    });
    try {
      const screen = await renderPhone({ theme, entry: '/ml-publicaciones?sel=MLA1100000001&tab=promos' });
      const panel = screen.getByRole('complementary', { name: 'Detalle de la publicación' });
      await expect.element(panel.getByRole('button', { name: 'Ocultar competencia' })).toBeVisible();
      await expect.element(panel.getByText('DISTRIBUIDORA DE REDES DEL LITORAL SRL')).toBeVisible();
      const el = panel.element();
      expect(el.scrollWidth).toBeLessThanOrEqual(el.clientWidth + 1);
      noSidewaysScroll();
      const title = [...el.querySelectorAll('h3')].find((h) => h.textContent === 'Competencia del catálogo');
      const ranking = title.parentElement;
      expect(ranking.getBoundingClientRect().top).toBeGreaterThanOrEqual(ranking.previousElementSibling.getBoundingClientRect().bottom);
      ranking.scrollIntoView();
      await shot(`pubml-phone-competencia-${theme}`, el);
    } finally {
      promocionesAPI.getCompetenciaCatalogo.mockReset();
    }
  });

  it('keeps the footer at the bottom of the screen while the panel scrolls', async () => {
    const screen = await renderPhone({ theme, entry: '/ml-publicaciones?sel=MLA1100000001&tab=resumen' });
    const panel = screen.getByRole('complementary', { name: 'Detalle de la publicación' });
    await expect.element(panel.getByRole('button', { name: 'Resincronizar' })).toBeVisible();
    const scroller = panel.element();
    scroller.scrollTop = scroller.scrollHeight;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    expect(scroller.querySelector('footer').getBoundingClientRect().bottom).toBeCloseTo(844, 0);
    scroller.scrollTop = 0;
  });
});
