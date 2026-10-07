/**
 * Ventas ML — the real page, real CSS, real Chromium, realistic data.
 *
 * Why this file exists: the screen shipped a long checklist of features and
 * still looked broken, because nobody LOOKED at it. jsdom has no layout, so a
 * title clipped by a `max-width`, a badge pushing an amount out of its column
 * or white-on-white money all pass every unit test. This suite renders the
 * whole `VentasML` page (and its detail panel) against fixtures shaped exactly
 * like the backend's responses, at the two widths operators actually use, in
 * both themes, and asserts the geometry promises the design makes.
 *
 * Screenshots are a DEV aid, not a baseline (see `setup.visual.js` on why no
 * pixel baselines are committed). They are only written when
 * `VITE_VENTAS_SHOTS_DIR` is set:
 *
 *   VITE_VENTAS_SHOTS_DIR=/abs/scratch/dir pnpm exec vitest run --project=visual ventasMl
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme, tokenColor } from './visualHelpers';
import VentasML from '../../pages/VentasML';
import api from '../../services/api';
import {
  SALES_RESPONSE,
  KPI_RESPONSE,
  ORDER_DETAIL_RESPONSE,
  PACK_DETAIL_RESPONSE,
  EPSON_ORDER_ID,
} from './ventasMlFixtures';

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
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const routeGet = (url) => {
  if (url === '/ml-ventas-ops/sales') return { data: SALES_RESPONSE };
  if (url === '/ml-ventas-ops/sales/kpis') return { data: KPI_RESPONSE };
  if (url === '/ml-ventas-ops/sales/sync-status') {
    return { data: { last_synced_at: new Date(Date.now() - 3 * 60 * 1000).toISOString() } };
  }
  if (url === '/ml-ventas-ops/divergences') return { data: { total: 0, items: [] } };
  if (url.startsWith('/ml-ventas-ops/orders/')) return { data: ORDER_DETAIL_RESPONSE };
  if (url.startsWith('/ml-ventas-ops/packs/')) return { data: PACK_DETAIL_RESPONSE };
  if (url === '/usuarios/pms') return { data: [] };
  return { data: {} };
};

const SHOTS_DIR = import.meta.env.VITE_VENTAS_SHOTS_DIR;

// The viewport as the operator sees it (`name`), plus the whole page laid
// out at that width (`name-full`), so nothing below the fold goes unseen.
const shot = async (name, { width, height } = {}) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
  const shell = document.querySelector('[data-shell]');
  if (!shell || !width) return;
  // The iframe only paints its viewport, so grow it to the page's height for
  // the full shot and put it back afterwards.
  await page.viewport(width, Math.max(height, shell.scrollHeight + 16));
  await page.screenshot({ path: `${SHOTS_DIR}/${name}-full.png`, element: shell });
  await page.viewport(width, height);
};

// The app shell around the page: a fixed 56px TopBar and the collapsed 48px
// sidebar. Without them the page would lay out wider than it ever does for a
// real operator, and the 1366 case would be a lie.
const Shell = ({ children }) => (
  <div
    data-shell
    style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}
  >
    {children}
  </div>
);

const renderPage = async ({ width, height, theme, params = '' }) => {
  router.params = params;
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  const screen = await render(
    <Shell>
      <VentasML />
    </Shell>,
  );
  await expect.element(screen.getByText(/Impresora Multifunción Epson/).first()).toBeVisible();
  return screen;
};

const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
];
const THEMES = ['light', 'dark'];

// Every cell inside the table, horizontally contained in its own column.
// Anything that pokes out of its <td> is overlapping the next column -- the
// exact "Provisorio badge overflows" / "title runs under Orden" bug.
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

describe('Ventas ML screen (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
    api.post.mockReset();
  });

  for (const { width, height } of VIEWPORTS) {
    for (const theme of THEMES) {
      it(`list ${width}x${height} ${theme}: no cell overflows its column`, async () => {
        const screen = await renderPage({ width, height, theme });
        const table = document.querySelector('table');
        await shot(`list-${width}-${theme}`, { width, height });
        expect(overflowingCells(table)).toEqual([]);
        // The page itself never scrolls sideways at either width.
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);

        // Total Gauss: "Provisorio" lives on the line UNDER the amount, and the
        // amount keeps the same right edge whether or not the badge is there.
        const gaussCells = [...table.querySelectorAll('tbody td[data-col-id="total_gauss"]')];
        const amountRights = new Set();
        let provisionalSeen = 0;
        for (const td of gaussCells) {
          const amount = td.querySelector('[data-money]');
          if (!amount) continue;
          const a = amount.getBoundingClientRect();
          amountRights.add(Math.round(a.right));
          for (const pill of td.querySelectorAll('[data-provisional]')) {
            provisionalSeen += 1;
            expect(pill.getBoundingClientRect().top).toBeGreaterThanOrEqual(a.bottom - 0.5);
          }
        }
        expect(provisionalSeen).toBeGreaterThan(0);
        expect(amountRights.size).toBe(1);

        // Colour semantics, read from the painted page against the tokens:
        // a negative Total Gauss is red, its negative markup a red chip, a
        // healthy markup green, Neto the headline blue.
        // The innermost span with exactly this text (a wrapper holding only
        // that span has the same textContent and must not be measured).
        const byText = (text) =>
          [...table.querySelectorAll('span')].filter((el) => el.textContent === text).pop();
        expect(getComputedStyle(byText('-$ 32.450,80')).color).toBe(tokenColor('--money-negative'));
        expect(getComputedStyle(byText('-8,4%')).color).toBe(tokenColor('--tone-danger-fg'));
        expect(getComputedStyle(byText('+21,6%')).color).toBe(tokenColor('--tone-success-fg'));
        expect(getComputedStyle(byText('+4,2%')).color).toBe(tokenColor('--tone-warning-fg'));
        expect(getComputedStyle(byText('$ 502.165,91')).color).toBe(tokenColor('--money-headline'));

        // The product title is never cut to one line: at Full HD every
        // fixture title fits whole; at 1366 it may clamp, but at two lines.
        for (const title of table.querySelectorAll('tbody td[data-col-id="producto"] [data-product-title]')) {
          const lineHeight = Number.parseFloat(getComputedStyle(title).lineHeight);
          expect(title.clientHeight).toBeGreaterThanOrEqual(Math.min(title.scrollHeight, lineHeight * 2) - 1);
          if (width >= 1920) expect(title.scrollHeight).toBeLessThanOrEqual(title.clientHeight + 1);
        }
        screen.unmount();
      });

      it(`panel ${width}x${height} ${theme}: detail panel open beside the list`, async () => {
        const screen = await renderPage({ width, height, theme, params: `orden=${EPSON_ORDER_ID}` });
        await expect.element(screen.getByText('De dónde sale el neto')).toBeVisible();
        const aside = document.querySelector('aside');
        const inPanel = (text) =>
          [...aside.querySelectorAll('span')].filter((el) => el.textContent === text).pop();
        // (−) charges in red with "-$", Neto in the headline blue.
        expect(getComputedStyle(inPanel('-$ 74.676,08')).color).toBe(tokenColor('--money-negative'));
        expect(getComputedStyle(inPanel('$ 502.165,91')).color).toBe(tokenColor('--money-headline'));
        // The ML shipping id is on screen, copyable.
        expect(inPanel('44012876543')).toBeTruthy();
        expect(aside.querySelector('button[aria-label="Copiar ID de envío"]')).toBeTruthy();
        await shot(`panel-${width}-${theme}`, { width, height });
        const panel = document.querySelector('aside');
        if (SHOTS_DIR) {
          // The whole panel, not just the part above the fold: grow the
          // viewport until the panel's content fits, shoot, restore.
          await page.viewport(width, Math.max(height, panel.scrollHeight + 200));
          await page.screenshot({ path: `${SHOTS_DIR}/panel-full-${width}-${theme}.png`, element: panel });
          await page.viewport(width, height);
        }
        expect(overflowingCells(document.querySelector('table'))).toEqual([]);
        screen.unmount();
      });
    }
  }

  it('pack expanded: sub-rows render each product, nothing overflows at 1366', async () => {
    const screen = await renderPage({ width: 1366, height: 768, theme: 'light' });
    await screen.getByRole('button', { name: /Pack 2000014907031737/ }).click();
    await expect.element(screen.getByText(/Mouse Inalámbrico Logitech/).first()).toBeVisible();
    await shot('list-pack-1366-light', { width: 1366, height: 768 });
    expect(overflowingCells(document.querySelector('table'))).toEqual([]);
    screen.unmount();
  });

  // Below 1280px `.tableCard` becomes a horizontal scroll container, so the
  // sticky `<th>` pins to the CARD. A TopBar-sized `top` offset there pushed
  // the header down over the first row (a single row was left hidden).
  for (const width of [1000, 1279]) {
    it(`narrow ${width}: the header never covers the first row`, async () => {
      const screen = await renderPage({ width, height: 700, theme: 'light' });
      const table = document.querySelector('table');
      const header = table.querySelector('thead th').getBoundingClientRect();
      const firstRow = table.querySelector('tbody tr').getBoundingClientRect();
      expect(firstRow.top).toBeGreaterThanOrEqual(header.bottom - 0.5);
      screen.unmount();
    });
  }
});
