/**
 * Ventas ML for a `tplink.solo` user (metricas-ml-tplink-mode P7) -- the real
 * page in real Chromium, with the backend's TP response shapes. Same harness
 * as `ventasMl.visual.test.jsx`; screenshots only with `VITE_VENTAS_SHOTS_DIR`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import VentasML from '../../pages/VentasML';
import api from '../../services/api';
import {
  SALES_RESPONSE,
  KPI_RESPONSE,
  ORDER_DETAIL_RESPONSE,
  PACK_DETAIL_RESPONSE,
  EPSON_ORDER_ID,
} from './ventasMlFixtures';

// The Ventas ML fixtures reshaped the way the backend answers a TP-only user
// (`ml_ventas_ops.py` `_tp_model`): every Gauss key gone, TP figures in their
// place, an unknown Total TP null and flagged. Total TP is the Gauss total
// x 1.1 and Markup TP the Gauss markup + 5 points -- any plausible number
// serves a layout test.
const GAUSS_KEYS = new Set(['total_gauss', 'total_gauss_provisional', 'total_gauss_provisional_falta', 'markup']);
const toTp = (value) => {
  if (Array.isArray(value)) return value.map(toTp);
  if (!value || typeof value !== 'object') return value;
  const out = {};
  for (const [key, inner] of Object.entries(value)) {
    if (!GAUSS_KEYS.has(key) && key !== 'costo_mercaderia') out[key] = toTp(inner);
  }
  if ('total_gauss' in value) {
    const known = value.total_gauss !== null && value.total_gauss !== undefined;
    out.total_tp = known ? value.total_gauss * 1.1 : null;
    out.markup_tp = known && value.markup !== null && value.markup !== undefined ? value.markup + 5 : null;
    out.tp_incompleto = !known;
    out.total_tp_provisional = Boolean(value.total_gauss_provisional);
    out.total_tp_provisional_falta = value.total_gauss_provisional_falta ?? null;
  }
  return out;
};

const SALES_TP = toTp(SALES_RESPONSE);
const PACK_TP = toTp(PACK_DETAIL_RESPONSE);
const { cadena_total_gauss: cadena, total_gauss: _omit, ...detailRest } = ORDER_DETAIL_RESPONSE;
const ORDER_TP = {
  ...detailRest,
  total_tp: cadena.total_gauss * 1.1,
  cadena_total_tp: {
    total_tp: cadena.total_gauss * 1.1,
    costo_tp: 227448.0,
    markup_tp: 26.6,
    tp_incompleto: false,
    lineas: cadena.lineas.map((l) => (l.code === 'costo_mercaderia' ? { code: 'costo_tp', monto: 227448.0 } : l)),
    provisional: cadena.provisional,
    provisional_falta: cadena.provisional_falta,
  },
};
const KPI_TP = {
  ...Object.fromEntries(
    Object.entries(KPI_RESPONSE).filter(([k]) => !/gauss|markup/.test(k)),
  ),
  total_tp_sum: 15532990.11,
  tp_incompleto_count: 7,
  markup_tp_weighted_pct: 31.3,
};

const router = vi.hoisted(() => ({ params: '' }));

// Same isolation the other page-level visual tests use: a live
// react-router-dom pulls a second React graph into browser mode. The page only
// needs search params and a Link, so both are reproduced with real state.
vi.mock('react-router-dom', async () => {
  const { useState } = await import('react');
  return {
    useSearchParams: () => {
      const [params, setParams] = useState(() => new URLSearchParams(router.params));
      const update = (next) => {
        const value = typeof next === 'function' ? next(params) : next;
        const resolved = new URLSearchParams(value);
        router.params = resolved.toString();
        setParams(resolved);
      };
      return [params, update];
    },
    Link: ({ to, children, ...rest }) => (
      <a href={to} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosAPI: {
    marcas: vi.fn(() => Promise.resolve({ data: { marcas: [] } })),
    subcategorias: vi.fn(() => Promise.resolve({ data: { categorias: [] } })),
    obtenerMarcasPorPMs: vi.fn(() => Promise.resolve({ data: { marcas: [] } })),
    obtenerSubcategoriasPorPMs: vi.fn(() => Promise.resolve({ data: { subcategorias: [] } })),
  },
  authAPI: { login: vi.fn(), me: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: ['ml_ops.ver', 'tplink.solo'], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const routeGet = (url) => {
  if (url === '/ml-ventas-ops/sales') return { data: SALES_TP };
  if (url === '/ml-ventas-ops/sales/kpis') return { data: KPI_TP };
  if (url === '/ml-ventas-ops/sales/sync-status') {
    return { data: { last_synced_at: new Date(Date.now() - 3 * 60 * 1000).toISOString() } };
  }
  if (url.startsWith('/ml-ventas-ops/orders/')) return { data: ORDER_TP };
  if (url.startsWith('/ml-ventas-ops/packs/')) return { data: PACK_TP };
  if (url === '/usuarios/pms') return { data: [] };
  return { data: {} };
};

const SHOTS_DIR = import.meta.env.VITE_VENTAS_SHOTS_DIR;

const Shell = ({ children }) => (
  <div
    data-shell
    style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}
  >
    {children}
  </div>
);

const renderPage = async ({ width, height, params = '' }) => {
  router.params = params;
  await page.viewport(width, height);
  setTheme('light');
  document.body.style.background = 'var(--cf-bg-app)';
  const screen = await render(
    <Shell>
      <VentasML />
    </Shell>,
  );
  await expect.element(screen.getByText(/Impresora Multifunción Epson/).first()).toBeVisible();
  return screen;
};

const overflowingCells = (root) => {
  const offenders = [];
  for (const td of root.querySelectorAll('tbody td')) {
    const box = td.getBoundingClientRect();
    for (const child of td.querySelectorAll('*')) {
      const r = child.getBoundingClientRect();
      if (r.width === 0) continue;
      if (r.right > box.right + 0.5 || r.left < box.left - 0.5) {
        offenders.push(`${td.dataset.colId || td.cellIndex}: ${child.textContent.trim().slice(0, 40)}`);
        break;
      }
    }
  }
  return offenders;
};

describe('Ventas ML in TP mode (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
  });

  for (const { width, height } of [
    { width: 1920, height: 1080 },
    { width: 1366, height: 768 },
  ]) {
    it(`list ${width}x${height}: Total TP fits its column, no Gauss anywhere`, async () => {
      const screen = await renderPage({ width, height });
      await expect.element(screen.getByText('TP incompleto')).toBeVisible();
      const table = document.querySelector('table');
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tp-list-${width}-light.png` });
      expect(overflowingCells(table)).toEqual([]);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      expect(table.querySelectorAll('tbody td[data-col-id="total_tp"]').length).toBeGreaterThan(0);
      // An unknown Total TP reads "incompleto", in the muted sub-line colour.
      const incompleto = [...table.querySelectorAll('td[data-col-id="total_tp"] span')].find(
        (el) => el.textContent === 'incompleto',
      );
      expect(incompleto).toBeTruthy();
      expect(document.body.textContent).not.toMatch(/gauss/i);
      expect(api.get.mock.calls.some(([url]) => url.startsWith('/ml-ventas-ops/divergences'))).toBe(false);
      screen.unmount();
    });
  }

  it('panel 1366x768: the chain ends in Total TP', async () => {
    const screen = await renderPage({ width: 1366, height: 768, params: `orden=${EPSON_ORDER_ID}` });
    await expect.element(screen.getByRole('region', { name: 'Total TP' })).toBeVisible();
    const aside = document.querySelector('aside');
    expect(aside.textContent).toContain('Costo TP');
    expect(document.body.textContent).not.toMatch(/gauss/i);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tp-panel-1366-light.png` });
    expect(overflowingCells(document.querySelector('table'))).toEqual([]);
    screen.unmount();
  });
});
