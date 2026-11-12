/**
 * Métricas ML on a phone (handoffs `mobile-metricas-pubml-tarea` T1, design `Main.dc.html` and
 * `MetricasFiltros.dc.html`): the real page in real Chromium at 390x844, where `useIsPhone` matches by itself.
 *
 * Asserts what the spec promises a phone (S5): no horizontal page scroll at 390px, and every tap target at least
 * 44px tall (a 36px period chip taps 44px through its `::after`); the cards, the expanded card and the filter sheet
 * all fit the width.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when `VITE_METRICAS_SHOTS_DIR` is set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { BOARD_RESPONSE, EPSON_PUBLICATIONS } from './metricasMlFixtures';

vi.mock('react-router-dom', async () => ({
  useSearchParams: (await import('./searchParamsMock')).useSearchParams,
  Link: ({ to, children, ...rest }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

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

const routeGet = (url) => {
  if (url === '/ml-metricas/board') {
    return { data: { ...BOARD_RESPONSE, refreshed_at: new Date(Date.now() - 4 * 60 * 1000).toISOString() } };
  }
  if (url.startsWith('/ml-metricas/board/products/')) return { data: EPSON_PUBLICATIONS };
  if (url === '/usuarios/pms') return { data: [] };
  return { data: {} };
};

const WIDTH = 390;
const HEIGHT = 844;
const SHOTS_DIR = import.meta.env.VITE_METRICAS_SHOTS_DIR;
const EPSON = 'Impresora Multifunción Epson EcoTank L3250 Color Negro';

const shot = async (name) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
  const shell = document.querySelector('[data-shell]');
  await page.viewport(WIDTH, Math.max(HEIGHT, shell.scrollHeight + 16));
  await page.screenshot({ path: `${SHOTS_DIR}/${name}-full.png`, element: shell });
  await page.viewport(WIDTH, HEIGHT);
};

// The app shell on a phone: the fixed 56px TopBar, no sidebar, the content padded 16px (AppLayout's .mainContent).
const Shell = ({ children }) => (
  <div data-shell style={{ paddingTop: 'var(--cf-topbar-height)' }}>
    <div style={{ padding: 16 }}>{children}</div>
  </div>
);

const renderPhone = async (theme) => {
  await page.viewport(WIDTH, HEIGHT);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  document.body.style.margin = '0';
  const screen = await render(
    <Shell>
      <MetricasML />
    </Shell>,
  );
  await expect.element(screen.getByText(EPSON)).toBeVisible();
  return screen;
};

/** Tap targets under `root` shorter than 44px; a 36px chip counts its `::after` hit area. */
const smallTargets = (root) =>
  [...root.querySelectorAll('button, select, input, [role="switch"]')]
    .filter((el) => el.getClientRects().length > 0 && getComputedStyle(el).opacity !== '0')
    .filter((el) => {
      const { height } = el.getBoundingClientRect();
      const after = getComputedStyle(el, '::after');
      const extra = after.content !== 'none' && after.position === 'absolute' ? -Number.parseFloat(after.top) * 2 : 0;
      return height + extra < 44 - 0.5;
    })
    .map((el) => `${el.tagName.toLowerCase()} "${(el.getAttribute('aria-label') || el.textContent).trim().slice(0, 30)}"`);

const noPageScroll = () => {
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(WIDTH);
  expect(document.body.scrollWidth).toBeLessThanOrEqual(WIDTH);
};

describe('Métricas ML on a phone (visual, 390x844)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
  });

  for (const theme of ['light', 'dark']) {
    it(`${theme}: cards instead of the table, no page scroll sideways, 44px tap targets`, async () => {
      const screen = await renderPhone(theme);
      await shot(`metricas-phone-${theme}`);

      expect(document.querySelector('table')).toBeNull();
      noPageScroll();
      expect(smallTargets(document.querySelector('[data-shell]'))).toEqual([]);
      // Every card and KPI inside the screen.
      for (const el of document.querySelectorAll('article, [data-kpi-value]')) {
        expect(el.getBoundingClientRect().right).toBeLessThanOrEqual(WIDTH + 0.5);
      }
      // The period chips scroll inside their own row, never the page.
      const periods = document.querySelector('[role="group"][aria-label="Período"]');
      expect(getComputedStyle(periods).overflowX).toBe('auto');
      screen.unmount();
    });

    it(`${theme}: an expanded card with its publications fits the width`, async () => {
      const screen = await renderPhone(theme);
      await screen.getByRole('button', { name: new RegExp(`^${EPSON}`) }).click();
      await screen.getByRole('button', { name: 'Ver sus 3 publicaciones' }).click();
      await expect.element(screen.getByText(/MLA2060835678/)).toBeVisible();
      await shot(`metricas-phone-${theme}-expandida`);

      noPageScroll();
      const card = document.querySelector(`article[aria-label="${EPSON}"]`);
      expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth + 1);
      expect(smallTargets(card)).toEqual([]);
      screen.unmount();
    });

    it(`${theme}: the filters bottom sheet fits, scrolls inside, and keeps "Ver N productos" in view`, async () => {
      const screen = await renderPhone(theme);
      await screen.getByRole('button', { name: /^Filtros/ }).click();
      const sheet = screen.getByRole('dialog', { name: 'Filtros' });
      await expect.element(sheet).toBeVisible();
      await shot(`metricas-phone-${theme}-filtros`);

      const dialog = document.querySelector('[role="dialog"]');
      const box = dialog.getBoundingClientRect();
      expect(box.left).toBeGreaterThanOrEqual(0);
      expect(box.right).toBeLessThanOrEqual(WIDTH);
      expect(box.bottom).toBeLessThanOrEqual(HEIGHT + 0.5);
      expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1);
      const apply = [...dialog.querySelectorAll('button')].find((b) => /^Ver \d/.test(b.textContent));
      expect(apply.getBoundingClientRect().bottom).toBeLessThanOrEqual(HEIGHT);
      expect(smallTargets(dialog)).toEqual([]);
      noPageScroll();
      screen.unmount();
    });
  }
});
