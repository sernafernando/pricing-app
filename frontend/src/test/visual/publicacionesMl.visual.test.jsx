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
import {
  BRAND_NODES,
  DATA_STATE_OK,
  DETAIL_RESPONSE,
  DETAIL_RESPONSE_MARGIN,
  FACETS,
  ITEMS,
  ITEMS_RESPONSE,
  PRODUCT_NODES,
  VARIATIONS_RESPONSE,
  VARIATION_ITEM,
  groupsResponse,
  makeNode,
} from './publicacionesMlFixtures';

// The markup column, its filters and the sub-rows' cost are for `ver_ganancia` only.
let canSeeMargin = false;
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => (permiso === 'ml_metricas.ver_ganancia' ? canSeeMargin : true),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { items: vi.fn(), variations: vi.fn(), groups: vi.fn(), detail: vi.fn(), enqueue: vi.fn() },
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
      it(`${width}x${height} ${theme}: the markup column and its filters fit, and the sort says "peor variación"`, async () => {
        const screen = await renderMarginPage({ width, height, theme });
        const scroller = scrollerOf();
        const header = [...scroller.querySelectorAll('thead th')].find((th) => th.textContent.includes('Markup'));
        expect(header).toBeDefined();
        expect(header.textContent).toContain('peor variación');
        expect(wrapped([header.querySelector('button')])).toEqual([]);
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

// The detail panel open beside the table (publicaciones-ml-vista P13a.T5, S61.1/S62.1).
const SELECTED = MANY[0].item_id;
const PANEL_VIEWPORTS = [
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
];

const renderWithPanel = async ({ width, height, theme, margin = false, tab = '' }) => {
  canSeeMargin = margin;
  const base = { ...MANY[0], is_full: true, variations_count: 3 };
  publicacionesMlAPI.items.mockResolvedValue({
    data: margin ? { ...MARGIN_RESPONSE, items: [{ ...base, markup: MARGIN_ITEMS[1].markup }, ...MANY.slice(1)] } : { ...RESPONSE, items: [base, ...MANY.slice(1)] },
  });
  publicacionesMlAPI.detail.mockResolvedValue({ data: { ...(margin ? DETAIL_RESPONSE_MARGIN : DETAIL_RESPONSE), row: base } });
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
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
        for (const el of panel.querySelectorAll('*')) {
          const r = el.getBoundingClientRect();
          if (r.width === 0) continue;
          expect(r.right, el.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(box.right + 0.5);
        }
        const tabs = [...panel.querySelectorAll('[role="tab"]')];
        expect(tabs.map((tab) => tab.textContent)).toEqual(['Resumen', 'Variaciones', 'Full']);
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

  it('1366x768 dark: the Full tab badges a partial report with the info tone', async () => {
    const screen = await renderWithPanel({ width: 1366, height: 768, theme: 'dark', tab: 'full' });
    publicacionesMlAPI.detail.mockClear();
    await expect.element(screen.getByText('Últimos 30 días')).toBeVisible();
    // The fixture's report is complete: no badge, and the figures sit on one line.
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
