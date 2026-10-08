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
import { setTheme, tokenColor } from './visualHelpers';
import PublicacionesML from '../../pages/PublicacionesML';
import { publicacionesMlAPI } from '../../services/api';
import { DATA_STATE_OK, FACETS, ITEMS, ITEMS_RESPONSE } from './publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { items: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

// 50 rows so the scroller really has something to scroll vertically.
const MANY = Array.from({ length: 50 }, (_, i) => ({ ...ITEMS[i % ITEMS.length], item_id: `MLA${1100000100 + i}` }));
const RESPONSE = {
  ...ITEMS_RESPONSE,
  items: MANY,
  facets: FACETS,
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

const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
];
const THEMES = ['light', 'dark'];

describe('Publicaciones ML (visual)', () => {
  beforeEach(() => {
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
