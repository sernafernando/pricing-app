/**
 * Publicaciones ML column order and presets (pubml-columnas-presets S1, S3) -- the real page, real CSS, real
 * Chromium and real dnd-kit: the column picker with a keyboard drag in progress and the presets menu, in both themes,
 * inside the window. With `VITE_PUBML_PRESETS_SHOTS_DIR` it takes their screenshots.
 *
 *   VITE_PUBML_PRESETS_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual publicacionesMlPresets
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import PublicacionesML from '../../pages/PublicacionesML';
import { publicacionesMlAPI } from '../../services/api';
import { mlPublicationsPresetsAPI } from '../../services/mlPublicationsPresets';
import { FACETS, ITEMS_RESPONSE, KPIS_RESPONSE } from './publicacionesMlFixtures';

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

// The user's layout and presets of the list: a shared preset applied and then changed (modificado), and their own.
vi.mock('../../services/mlPublicationsPresets', () => ({
  mlPublicationsPresetsAPI: { getLayout: vi.fn(), saveLayout: vi.fn(), list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
const PRESETS = [
  {
    id: 5,
    vista: 'publicacion',
    nombre: 'Pausadas por precio',
    compartido: true,
    editable: true,
    updated_at: '2026-11-18T10:00:00Z',
    payload: { columns: { visibility: { tienda: true }, order: ['titulo', 'tienda', 'tipo'] }, params: { estado: 'paused', orden: 'precio', dir: 'asc' } },
  },
  {
    id: 6,
    vista: 'publicacion',
    nombre: 'Reposición Full del equipo de ventas',
    compartido: true,
    editable: false,
    updated_at: '2026-11-18T10:00:00Z',
    payload: { columns: { visibility: {}, order: [] }, params: { stock: 'full_sin_stock' } },
  },
  {
    id: 9,
    vista: 'publicacion',
    nombre: 'Mis activas',
    compartido: false,
    editable: true,
    updated_at: '2026-11-18T10:00:00Z',
    payload: { columns: { visibility: {}, order: [] }, params: { estado: 'active' } },
  },
];

const SHOTS_DIR = import.meta.env.VITE_PUBML_PRESETS_SHOTS_DIR;
const WIDTH = 1600;
const HEIGHT = 1000;

const Shell = ({ children }) => (
  <div data-shell style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>
    {children}
  </div>
);

const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const inside = (el) => {
  const box = el.getBoundingClientRect();
  return box.left >= 0 && box.top >= 0 && box.right <= window.innerWidth && box.bottom <= window.innerHeight;
};

const renderPage = async (theme) => {
  await page.viewport(WIDTH, HEIGHT);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  window.scrollTo(0, 0);
  const screen = await render(
    <MemoryRouter initialEntries={['/ml-publicaciones?estado=paused&orden=precio&dir=asc&marcas=EPSON']}>
      <Shell>
        <PublicacionesML />
      </Shell>
    </MemoryRouter>,
  );
  await expect.element(screen.getByText('MLA1100000001')).toBeVisible();
  return screen;
};

beforeEach(() => {
  localStorage.clear();
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.items.mockResolvedValue({ data: { ...ITEMS_RESPONSE, facets: FACETS } });
  publicacionesMlAPI.kpis.mockReset();
  publicacionesMlAPI.kpis.mockResolvedValue({ data: KPIS_RESPONSE });
  mlPublicationsPresetsAPI.getLayout.mockResolvedValue({
    columns: { visibility: { tienda: true }, order: ['titulo', 'tienda', 'tipo'] },
    preset_activo_id: 5,
  });
  mlPublicationsPresetsAPI.saveLayout.mockImplementation((vista, body) => Promise.resolve(body));
  mlPublicationsPresetsAPI.list.mockResolvedValue(PRESETS);
});

describe('Publicaciones ML column order and presets (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`${WIDTH}x${HEIGHT} ${theme}: the column picker with its handles and a group lifted by keyboard`, async () => {
      const screen = await renderPage(theme);
      await userEvent.click(screen.getByRole('button', { name: 'Columnas' }));
      const picker = screen.getByRole('group', { name: 'Elegir columnas visibles' });
      await expect.element(picker.getByRole('button', { name: 'Mover grupo Stock' })).toBeVisible();
      await expect.element(picker.getByRole('button', { name: 'Restablecer' })).toBeVisible();
      expect(inside(picker.element())).toBe(true);
      // Space lifts the group, an arrow moves it: dnd-kit's keyboard drag, in progress for the screenshot.
      picker.getByRole('button', { name: 'Mover grupo Stock' }).element().focus();
      await userEvent.keyboard(' ');
      await frame();
      await userEvent.keyboard('{ArrowUp}');
      await frame();
      expect(picker.element().querySelector('[class*="dragging"]')).not.toBeNull();
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/picker-arrastrando-${theme}.png` });
      await userEvent.keyboard('{Escape}');
      screen.unmount();
    });

    it(`${WIDTH}x${HEIGHT} ${theme}: the presets menu, its active preset marked modificado`, async () => {
      const screen = await renderPage(theme);
      const trigger = screen.getByRole('button', { name: 'Preset: Pausadas por precio (modificado)' });
      await expect.element(trigger).toBeVisible();
      await userEvent.click(trigger);
      const menu = screen.getByRole('dialog', { name: 'Presets' });
      await expect.element(menu.getByRole('button', { name: 'Aplicar Reposición Full del equipo de ventas' })).toBeVisible();
      await expect.element(menu.getByRole('button', { name: 'Guardar cambios' })).toBeVisible();
      expect(inside(menu.element())).toBe(true);
      // The trigger keeps to one line, the name cut short rather than wrapped.
      expect(trigger.element().getBoundingClientRect().height).toBeLessThan(40);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/presets-menu-${theme}.png` });
      screen.unmount();
    });
  }

  it(`${WIDTH}x${HEIGHT} light: Guardar como nuevo asks a name and personal or shared`, async () => {
    const screen = await renderPage('light');
    await userEvent.click(screen.getByRole('button', { name: /^Preset:/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Guardar como nuevo' }));
    await expect.element(screen.getByLabelText('Nombre')).toBeVisible();
    await expect.element(screen.getByRole('radio', { name: 'Compartido' })).toBeVisible();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/presets-guardar-light.png` });
    screen.unmount();
  });
});
