/**
 * Métricas ML — the real page, real CSS, real Chromium, fixtures shaped like
 * the backend's responses (ODD `metricas-ml-tablero` T4).
 *
 * Asserts the layout promises the approved design (`tablero.png`) and the
 * feature doc make, at the two widths operators use, in both themes:
 * - the table scrolls sideways INSIDE its card, never the page;
 * - the Producto column stays pinned while it does;
 * - money never wraps ("$" never alone on a line), and neither do the
 *   "vs anterior" chip or "Mín / Máx 90D";
 * - nothing pokes out of its cell.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when
 * `VITE_METRICAS_SHOTS_DIR` is set:
 *
 *   VITE_METRICAS_SHOTS_DIR=/abs/dir pnpm exec vitest run --project=visual metricasMl
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme, tokenColor } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { BOARD_RESPONSE, EPSON_PUBLICATIONS } from './metricasMlFixtures';

vi.mock('react-router-dom', () => ({
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
    return { data: { ...BOARD_RESPONSE, refreshed_at: new Date(Date.now() - 3 * 60 * 1000).toISOString() } };
  }
  if (url.startsWith('/ml-metricas/board/products/')) return { data: EPSON_PUBLICATIONS };
  if (url === '/usuarios/pms') return { data: [] };
  return { data: {} };
};

const SHOTS_DIR = import.meta.env.VITE_METRICAS_SHOTS_DIR;

const shot = async (name, { width, height }) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
  const shell = document.querySelector('[data-shell]');
  await page.viewport(width, Math.max(height, shell.scrollHeight + 16));
  await page.screenshot({ path: `${SHOTS_DIR}/${name}-full.png`, element: shell });
  await page.viewport(width, height);
};

// Fixed 56px TopBar + collapsed 48px sidebar, as the operator sees it.
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
  const screen = await render(
    <Shell>
      <MetricasML />
    </Shell>,
  );
  await expect.element(screen.getByText(/Impresora Multifunción Epson EcoTank/).first()).toBeVisible();
  return screen;
};

// A cell's content horizontally inside its own <td>; anything else overlaps
// the neighbour column.
const overflowingCells = (root) => {
  const offenders = [];
  for (const td of root.querySelectorAll('tbody td')) {
    const box = td.getBoundingClientRect();
    for (const child of td.querySelectorAll('*')) {
      const r = child.getBoundingClientRect();
      if (r.width === 0) continue;
      if (r.right > box.right + 0.5 || r.left < box.left - 0.5) {
        offenders.push(`${td.dataset.colId}: ${child.textContent.trim().slice(0, 40)}`);
        break;
      }
    }
  }
  return offenders;
};

// ONE rendered line, shown WHOLE: a single client rect no taller than ~1.6
// line-heights, and nothing cut by an ellipsis (a "$ 84.920.45…" hides the
// figure just as badly as a "$" alone on its line).
const lineHeightOf = (el) => {
  const style = getComputedStyle(el);
  return Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.3;
};
const wrapped = (elements) =>
  [...elements]
    .filter(
      (el) =>
        el.getClientRects().length > 1 ||
        el.getBoundingClientRect().height > lineHeightOf(el) * 1.6 ||
        el.scrollWidth > el.clientWidth + 1,
    )
    .map((el) => el.textContent.trim());

const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
];
const THEMES = ['light', 'dark'];

describe('Métricas ML board (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
  });

  for (const { width, height } of VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: an excluded chip is struck through in the danger tone and the filter band does not overflow`, async () => {
        const screen = await renderPage({ width, height, theme });
        const group = () => document.querySelector('[role="group"][aria-label="Filtrar por estado de publicación"]');
        const pausada = () => [...group().querySelectorAll('button')].find((b) => /Pausada/.test(b.textContent));
        // neutral -> include -> exclude
        await screen.getByRole('button', { name: /Pausada/ }).click();
        await screen.getByRole('button', { name: /Pausada/ }).click();
        await expect.element(screen.getByRole('button', { name: /^Ocultar Pausada · \d/ })).toBeVisible();
        await shot(`board-${width}-${theme}-excluded`, { width, height });

        const chip = pausada();
        expect(chip.dataset.state).toBe('exclude');
        const label = [...chip.querySelectorAll('span')].find((s) => s.textContent === 'Pausada');
        expect(getComputedStyle(label).textDecorationLine).toBe('line-through');
        expect(getComputedStyle(chip).color).toBe(tokenColor('--tone-danger-fg'));
        // One line (the chip's own scrollWidth counts its off-screen sr-only
        // separator, so measure the box), whole, inside the page.
        expect(chip.getClientRects()).toHaveLength(1);
        expect(chip.getBoundingClientRect().height).toBeLessThan(lineHeightOf(chip) * 2);
        expect(wrapped([label])).toEqual([]);
        const chipBox = chip.getBoundingClientRect();
        expect(chipBox.right).toBeLessThanOrEqual(width);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        const band = group().closest('div[class*="filterBand"]');
        expect(band.scrollWidth).toBeLessThanOrEqual(band.clientWidth + 1);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: the period toggle, its warning, the stock and ageing chips and the sort arrow fit`, async () => {
        const screen = await renderPage({ width, height, theme });
        // An ageing chip with "Solo con ventas" on: the warning shows next to
        // the toggle (ODD "Período y stock" PS3).
        await screen.getByRole('button', { name: /^Más de 60 d/ }).click();
        await expect.element(screen.getByText('Ocultando productos sin ventas en el período')).toBeVisible();
        await screen.getByRole('columnheader', { name: /^Stock/ }).getByRole('button').click();
        await expect.element(screen.getByRole('columnheader', { name: /^Stock/ })).toHaveAttribute('aria-sort', 'descending');
        await shot(`board-${width}-${theme}-periodo-stock`, { width, height });

        const toggle = document.querySelector('[role="switch"]');
        const hint = [...document.querySelectorAll('[role="status"]')].find((el) => /Ocultando/.test(el.textContent));
        const groups = ['Filtrar por stock', 'Filtrar por ageing'].map((name) =>
          document.querySelector(`[role="group"][aria-label="${name}"]`),
        );
        const chips = groups.flatMap((group) => [...group.querySelectorAll('button')]);
        expect(chips).toHaveLength(6);
        // Every control on ONE line, whole, inside the page.
        for (const el of [toggle, hint, ...chips]) {
          expect(el.getClientRects(), el.textContent).toHaveLength(1);
          expect(el.getBoundingClientRect().height, el.textContent).toBeLessThan(lineHeightOf(el) * 2);
          expect(el.getBoundingClientRect().right, el.textContent).toBeLessThanOrEqual(width);
        }
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        const band = toggle.closest('div[class*="filterBand"]');
        expect(band.scrollWidth).toBeLessThanOrEqual(band.clientWidth + 1);
        // The toggle reads as ON (filled chip) and the ageing dots carry the
        // Ageing column's tones.
        expect(toggle.getAttribute('aria-checked')).toBe('true');
        expect(getComputedStyle(toggle).backgroundColor).toBe(tokenColor('--money-headline'));
        const dotOf = (label) => chips.find((c) => c.textContent.startsWith(label)).querySelector('[data-tone]');
        expect(getComputedStyle(dotOf('Más de 60 d')).backgroundColor).toBe(tokenColor('--tone-danger-fg'));
        expect(getComputedStyle(dotOf('31 a 60 d')).backgroundColor).toBe(tokenColor('--tone-warning-fg'));
        expect(getComputedStyle(hint).color).toBe(tokenColor('--tone-warning-fg'));

        // The sorted header keeps its label and arrow on one line, inside it.
        const th = document.querySelector('thead th[aria-sort="descending"]');
        const button = th.querySelector('button');
        const arrow = th.querySelector('svg');
        expect(arrow).not.toBeNull();
        expect(button.getClientRects()).toHaveLength(1);
        expect(button.getBoundingClientRect().height).toBeLessThan(lineHeightOf(button) * 2);
        const thBox = th.getBoundingClientRect();
        expect(arrow.getBoundingClientRect().right).toBeLessThanOrEqual(thBox.right + 0.5);
        expect(button.getBoundingClientRect().right).toBeLessThanOrEqual(thBox.right + 0.5);
        screen.unmount();
      });

      it(`${width}x${height} ${theme}: scrolls inside the card, Producto pinned, nothing wraps or overflows`, async () => {
        const screen = await renderPage({ width, height, theme });
        // Open the Epson product: the publication sub-rows are part of the look.
        await screen.getByRole('button', { name: /Ver publicaciones de Impresora Multifunción Epson/ }).click();
        await expect.element(screen.getByText('MLA2060835678')).toBeVisible();
        await shot(`board-${width}-${theme}`, { width, height });

        const table = document.querySelector('table');
        const scroller = document.querySelector('[data-table-scroll]');

        // The page never scrolls sideways; the table does, inside its card.
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        expect(scroller.scrollWidth).toBeGreaterThan(scroller.clientWidth);

        expect(overflowingCells(table)).toEqual([]);

        // Money, the delta chip and Mín / Máx each on ONE line.
        expect(wrapped(table.querySelectorAll('[data-money]'))).toEqual([]);
        const kpis = document.querySelector('section[aria-label="Indicadores del período"]');
        expect(wrapped(kpis.querySelectorAll('[data-kpi-value]'))).toEqual([]);
        expect(wrapped(table.querySelectorAll('td[data-col-id="markup_delta"] > span'))).toEqual([]);
        expect(wrapped(table.querySelectorAll('td[data-col-id="markup_range"] > span'))).toEqual([]);

        // Scroll the table all the way right: Producto stays where it was,
        // and the Sell-in columns come into view.
        const firstCell = table.querySelector('tbody td[data-col-id="producto"]');
        const leftBefore = firstCell.getBoundingClientRect().left;
        scroller.scrollLeft = scroller.scrollWidth;
        await new Promise((resolve) => requestAnimationFrame(resolve));
        expect(Math.abs(firstCell.getBoundingClientRect().left - leftBefore)).toBeLessThan(1);
        const lastHeader = table.querySelector('thead tr:last-child th:last-child');
        expect(lastHeader.getBoundingClientRect().right).toBeLessThanOrEqual(scroller.getBoundingClientRect().right + 1);
        await shot(`board-${width}-${theme}-scrolled`, { width, height });

        // Colour semantics against the tokens: a loss in red, a rising
        // markup green.
        const byText = (text) => [...table.querySelectorAll('span')].filter((el) => el.textContent === text).pop();
        expect(getComputedStyle(byText('-$ 1.416.000,00')).color).toBe(tokenColor('--money-negative'));
        expect(getComputedStyle(byText('▲ +2,1 pp')).color).toBe(tokenColor('--tone-success-fg'));
        expect(getComputedStyle(byText('▼ -5,8 pp')).color).toBe(tokenColor('--tone-danger-fg'));
        screen.unmount();
      });
    }
  }
});
