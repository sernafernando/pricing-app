/**
 * Métricas with canal=todo and canal=fuera (vpf-metricas-canal-fe T2) -- the real page, real CSS, real Chromium,
 * fixtures shaped like contract C3 (`metricasMlCanalFixtures.js`, invented data). The layout promises of the
 * approved mockups 1 and 2 (`handoffs/diseno-vpf/`), at 1920 px in both themes:
 * - the page never scrolls sideways; the KPI cards stay on one row and no figure of theirs wraps;
 * - Todo: the Canal column is right after Producto, the daily bars stack ML under Por fuera;
 * - Por fuera: the "no comisión ni envío" note sits right-aligned on the alerts row, the ML-only bands are gone.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when `VITE_METRICAS_SHOTS_DIR` is set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { FUERA_BOARD_RESPONSE, TODO_BOARD_RESPONSE } from './metricasMlCanalFixtures';

// The query the page opens with (the menu links to `?canal=fuera`); an in-memory one, as `searchParamsMock`.
const url = vi.hoisted(() => ({ initial: '' }));

vi.mock('react-router-dom', async () => {
  const { useState } = await import('react');
  return {
    // The board renders the PDF upload modal, which navigates to the upload history.
    useNavigate: () => () => {},
    useSearchParams: () => {
      const [params, setParams] = useState(() => new URLSearchParams(url.initial));
      return [params, (next) => setParams(new URLSearchParams(next))];
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
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const routeGet = (path, config) => {
  if (path === '/ml-metricas/board') {
    const canal = config?.params?.canal;
    return { data: canal === 'fuera' ? FUERA_BOARD_RESPONSE : TODO_BOARD_RESPONSE };
  }
  if (path === '/usuarios/pms') return { data: [] };
  return { data: {} };
};

const SHOTS_DIR = import.meta.env.VITE_METRICAS_SHOTS_DIR;

const shot = async (name, { width, height }) => {
  if (!SHOTS_DIR) return;
  const shell = document.querySelector('[data-shell]');
  await page.viewport(width, Math.max(height, shell.scrollHeight + 16));
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: shell });
  await page.viewport(width, height);
};

// The mockups are drawn without the app's chrome: the page alone, on the app background.
const Shell = ({ children }) => (
  <div data-shell style={{ padding: '24px 24px 24px 48px' }}>
    {children}
  </div>
);

const renderPage = async ({ query, width, height, theme }) => {
  url.initial = query;
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  const screen = await render(
    <Shell>
      <MetricasML />
    </Shell>,
  );
  await expect.element(screen.getByText('Router de prueba AC1200').first()).toBeVisible();
  return screen;
};

const lineHeightOf = (el) => {
  const style = getComputedStyle(el);
  return Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.3;
};
const wrapped = (elements) =>
  [...elements]
    .filter((el) => el.getClientRects().length > 1 || el.getBoundingClientRect().height > lineHeightOf(el) * 1.6)
    .map((el) => el.textContent.trim());

const SIZE = { width: 1920, height: 1080 };

describe('Métricas canal (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((path, config) => Promise.resolve(routeGet(path, config)));
  });

  for (const theme of ['light', 'dark']) {
    it(`Todo ${theme}: KPI split on one row, Canal column after Producto, stacked daily bars`, async () => {
      const screen = await renderPage({ query: 'canal=todo', ...SIZE, theme });
      await expect.element(screen.getByRole('columnheader', { name: 'Canal' })).toBeVisible();
      await shot(`canal-todo-${theme}`, SIZE);

      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(SIZE.width);
      const kpis = document.querySelector('section[aria-label="Indicadores del período"]');
      const tops = [...kpis.children].map((card) => Math.round(card.getBoundingClientRect().top));
      expect(new Set(tops).size).toBe(1);
      expect(wrapped(kpis.querySelectorAll('[data-split] strong, [data-kpi-value]'))).toEqual([]);

      const headers = [...document.querySelectorAll('thead tr:last-child th')].map((th) => th.textContent.trim());
      expect(headers.slice(0, 2)).toEqual(['Detalle / SKU / Marca', 'Canal']);
      // Mockup 1: no channel cost column, so the Rotación columns stay inside the table card at 1920.
      expect(document.querySelector('td[data-col-id="costo_canal"]')).toBeNull();
      const scroller = document.querySelector('[data-table-scroll]');
      const ageing = [...document.querySelectorAll('thead tr:last-child th')].find((th) => th.textContent.trim() === 'Ageing');
      expect(ageing.getBoundingClientRect().right).toBeLessThanOrEqual(scroller.getBoundingClientRect().right + 0.5);

      const bar = document.querySelector('ol[aria-label="Ventas por día"] li:last-child');
      const ml = bar.querySelector('[data-canal="ml"]').getBoundingClientRect();
      const fuera = bar.querySelector('[data-canal="fuera"]').getBoundingClientRect();
      expect(ml.height).toBeGreaterThan(0);
      expect(fuera.bottom).toBeLessThanOrEqual(ml.top + 0.5);
      screen.unmount();
    });

    it(`Por fuera ${theme}: ML-only bands gone, the note right-aligned on the alerts row`, async () => {
      const screen = await renderPage({ query: 'canal=fuera', ...SIZE, theme });
      await expect.element(screen.getByText('Recargo cheque fuera de la venta: $ 412.300,50')).toBeVisible();
      await shot(`canal-fuera-${theme}`, SIZE);

      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(SIZE.width);
      expect(document.querySelector('[aria-label="Filtrar por tienda oficial"]')).toBeNull();
      expect(document.querySelector('[aria-label="Por tipo de envío"]')).toBeNull();

      const note = [...document.querySelectorAll('span')].find((el) => el.textContent.startsWith('Por fuera no tiene comisión ML'));
      const band = note.closest('div[class*="filterBand"]');
      const alerts = band.querySelector('[role="group"][aria-label="Alertas"]');
      expect(Math.abs(note.getBoundingClientRect().right - band.getBoundingClientRect().right)).toBeLessThan(32);
      expect(note.getBoundingClientRect().top).toBeLessThan(alerts.getBoundingClientRect().bottom);
      expect(wrapped([note])).toEqual([]);

      const kpis = document.querySelector('section[aria-label="Indicadores del período"]');
      const tops = [...kpis.children].map((card) => Math.round(card.getBoundingClientRect().top));
      expect(new Set(tops).size).toBe(1);
      expect(wrapped(kpis.querySelectorAll('[data-kpi-value]'))).toEqual([]);
      expect(document.querySelectorAll('ol[aria-label="Ventas por día"] li')).toHaveLength(31);
      // C5: the period cost right after Total Gauss, its money on one line; the top salespeople as chips.
      const leafHeaders = [...document.querySelectorAll('thead tr:last-child th')].map((th) => th.textContent.trim());
      expect(leafHeaders[leafHeaders.indexOf('Total Gauss') + 1]).toBe('Costo (Costo D)');
      expect(wrapped(document.querySelectorAll('td[data-col-id="costo_canal"] [data-money]'))).toEqual([]);
      const vendedores = document.querySelector('[role="group"][aria-label="Vendedores"]');
      expect(vendedores.querySelectorAll('button')).toHaveLength(4);
      expect(vendedores.closest('div[class*="filterBand"]').getClientRects()).toHaveLength(1);
      screen.unmount();
    });
  }
});
