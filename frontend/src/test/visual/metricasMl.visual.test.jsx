/**
 * Métricas ML — the real page, real CSS, real Chromium, fixtures shaped like
 * the backend's responses (ODD `metricas-ml-tablero` T4).
 *
 * Asserts the layout promises the approved design (`tablero.png`) and the
 * feature doc make, at the two widths operators use, in both themes:
 * - the table scrolls on BOTH axes INSIDE its card (TableShell model), never the page sideways;
 * - the header stays pinned at the top of that scroller while rows move;
 * - the Producto column stays pinned while it scrolls sideways;
 * - money never wraps ("$" never alone on a line), and neither do the
 *   "vs anterior" chip or "Mín / Máx 90D";
 * - nothing pokes out of its cell.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when
 * `VITE_METRICAS_SHOTS_DIR` is set:
 *
 *   VITE_METRICAS_SHOTS_DIR=/abs/dir pnpm exec vitest run --project=visual metricasMl
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme, tokenColor } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import {
  BOARD_RESPONSE,
  BOARD_ROWS,
  EPSON_GROUP_PRODUCTS,
  EPSON_PUBLICATIONS,
  epsonNodesFor,
  GROUP_BOARD_RESPONSE,
} from './metricasMlFixtures';
import { ADS_KPIS } from '../../components/metricasMl/adsFixtures';

vi.mock('react-router-dom', async () => ({
  // The page keeps its filters in the URL (U1): an in-memory query, empty at the start.
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

        // By its name: "Costos TP" is a switch of the toolbar too.
        const toggle = [...document.querySelectorAll('[role="switch"]')].find((el) => /Solo con ventas/.test(el.textContent));
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
        // Sell in / sell out without "Costos TP": seven cards on one row, the sell card among them.
        expect(kpis.textContent).not.toContain('Total TP');
        expect(kpis.textContent).toContain('Sell in / Sell out');
        const tops = [...kpis.children].map((card) => card.getBoundingClientRect().top);
        expect(tops).toHaveLength(7);
        expect(new Set(tops).size).toBe(1);
        expect(wrapped(table.querySelectorAll('td[data-col-id="markup_delta"] > span'))).toEqual([]);
        expect(wrapped(table.querySelectorAll('td[data-col-id="markup_range"] > span'))).toEqual([]);

        // Bounded scroller on both axes (Publicaciones ML / TableShell model).
        expect(getComputedStyle(scroller).overflowY).toBe('auto');
        expect(getComputedStyle(scroller).overflowX).toBe('auto');

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

describe('Métricas ML sticky headers (visual)', () => {
  // Enough rows for the card scroller to move vertically (TableShell / Publicaciones model).
  const tallBoard = {
    ...BOARD_RESPONSE,
    total: 40,
    rows: Array.from({ length: 40 }, (_, i) => ({
      ...BOARD_ROWS[0],
      key: String(1000 + i),
      product_item_id: 1000 + i,
      title: `Producto sticky ${i}`,
      sku: `STK-${i}`,
    })),
  };

  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === '/ml-metricas/board') return Promise.resolve({ data: tallBoard });
      return Promise.resolve(routeGet(url));
    });
  });

  it('1366x768 light: header and Producto stay pinned while the card scrolls both axes', async () => {
    await page.viewport(1366, 768);
    setTheme('light');
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <Shell>
        <MetricasML />
      </Shell>,
    );
    await expect.element(screen.getByText('Producto sticky 0').first()).toBeVisible();
    const scroller = document.querySelector('[data-table-scroll]');
    expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight);

    scroller.scrollIntoView({ block: 'start' });
    scroller.scrollTop = 280;
    scroller.scrollLeft = 160;
    await new Promise((resolve) => requestAnimationFrame(resolve));

    const box = scroller.getBoundingClientRect();
    const groupCell = scroller.querySelector('thead tr:first-child th');
    const leafCell = scroller.querySelector('thead tr:last-child th');
    expect(Math.abs(groupCell.getBoundingClientRect().top - box.top)).toBeLessThanOrEqual(2);
    expect(Math.abs(leafCell.getBoundingClientRect().top - groupCell.getBoundingClientRect().bottom)).toBeLessThanOrEqual(1);

    const pinned = [...scroller.querySelectorAll('tbody td[data-col-id="producto"]')].find(
      (td) =>
        td.getBoundingClientRect().top >= leafCell.getBoundingClientRect().bottom - 0.5 &&
        td.getBoundingClientRect().bottom <= box.bottom,
    );
    expect(pinned).toBeTruthy();
    expect(Math.abs(pinned.getBoundingClientRect().left - box.left)).toBeLessThanOrEqual(2);

    const probeY = Math.min(leafCell.getBoundingClientRect().bottom + 3, box.bottom - 2);
    const probe = document.elementFromPoint(box.left + Math.min(box.width / 2, 200), probeY);
    expect(probe).toBeTruthy();
    expect(scroller.querySelector('thead').contains(probe)).toBe(false);
    expect(probe.closest('tbody')).not.toBeNull();
    screen.unmount();
  });
});

describe('Métricas ML "Agrupado" view (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board' && config?.params?.group_by === 'group') {
        return Promise.resolve({ data: { ...GROUP_BOARD_RESPONSE, dimension: config.params.dimension } });
      }
      if (url === '/ml-metricas/board/group-nodes') return Promise.resolve({ data: epsonNodesFor(config.params.path) });
      return Promise.resolve(routeGet(url));
    });
  });

  for (const { width, height } of VIEWPORTS) {
    for (const theme of THEMES) {
      it(`${width}x${height} ${theme}: the view and dimension controls fit, a group opens into its products, nothing wraps or overflows`, async () => {
        const screen = await renderPage({ width, height, theme });
        await screen.getByRole('button', { name: 'Agrupado' }).click();
        await expect.element(screen.getByText('Sin marca')).toBeVisible();
        // The whole branch open: marca > categoría > subcategoría > producto.
        await screen.getByRole('button', { name: /Ver .* de Epson/ }).click();
        await expect.element(screen.getByText('Impresoras')).toBeVisible();
        await screen.getByRole('button', { name: /Ver .* de Impresoras/ }).click();
        await expect.element(screen.getByText('Laser')).toBeVisible();
        await screen.getByRole('button', { name: /Ver .* de Laser/ }).click();
        await expect.element(screen.getByText(EPSON_GROUP_PRODUCTS.rows[0].sku)).toBeVisible();
        await shot(`board-grouped-${width}-${theme}`, { width, height });

        // The two segmented controls sit in the first band, each button on ONE line.
        const views = document.querySelector('[role="group"][aria-label="Agrupar por"]');
        const dimensions = document.querySelector('[role="group"][aria-label="Dimensión"]');
        const buttons = [...views.querySelectorAll('button'), ...dimensions.querySelectorAll('button')];
        expect(buttons).toHaveLength(8);
        for (const button of buttons) {
          expect(button.getClientRects(), button.textContent).toHaveLength(1);
          expect(button.getBoundingClientRect().height, button.textContent).toBeLessThan(lineHeightOf(button) * 2);
          expect(button.getBoundingClientRect().right, button.textContent).toBeLessThanOrEqual(width);
        }
        const band = views.closest('div[class*="filterBand"]');
        expect(band.scrollWidth).toBeLessThanOrEqual(band.clientWidth + 1);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);

        // The table: scrolls inside its card, first column pinned, no cell overflow,
        // money and the group's counts on one line.
        const table = document.querySelector('table');
        const scroller = document.querySelector('[data-table-scroll]');
        expect(scroller.scrollWidth).toBeGreaterThan(scroller.clientWidth);
        expect(overflowingCells(table)).toEqual([]);
        expect(wrapped(table.querySelectorAll('[data-money]'))).toEqual([]);
        const counts = [...table.querySelectorAll('tbody td[data-col-id="producto"] span')].filter((el) =>
          /productos? ·/.test(el.textContent),
        );
        expect(counts.length).toBeGreaterThan(0);
        expect(wrapped(counts)).toEqual([]);

        // The levels: each row one step deeper than its parent, the level tags on one line,
        // and nothing of the pinned column spilling past its cell at ANY depth.
        const depthOf = (text) => [...table.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(text));
        const firstColumnLeft = (tr) =>
          tr.querySelector('td[data-col-id="producto"] button, td[data-col-id="producto"] > div > div').getBoundingClientRect().left;
        const lefts = ['Epson', 'Impresoras', 'Laser'].map((text) => firstColumnLeft(depthOf(text)));
        expect(lefts[1]).toBeGreaterThan(lefts[0] + 10);
        expect(lefts[2]).toBeGreaterThan(lefts[1] + 10);
        expect([...table.querySelectorAll('tbody tr')].map((tr) => tr.dataset.depth)).toEqual(
          expect.arrayContaining(['0', '1', '2', '3']),
        );
        const tags = [...table.querySelectorAll('tbody td[data-col-id="producto"] span')].filter((el) =>
          ['Marca', 'Categoría', 'Subcategoría'].includes(el.textContent),
        );
        expect(tags.length).toBeGreaterThanOrEqual(3);
        expect(wrapped(tags)).toEqual([]);
        for (const cell of table.querySelectorAll('tbody td[data-col-id="producto"]')) {
          expect(cell.scrollWidth, cell.textContent).toBeLessThanOrEqual(cell.clientWidth + 1);
        }

        const firstCell = table.querySelector('tbody td[data-col-id="producto"]');
        const leftBefore = firstCell.getBoundingClientRect().left;
        scroller.scrollLeft = scroller.scrollWidth;
        await new Promise((resolve) => requestAnimationFrame(resolve));
        expect(Math.abs(firstCell.getBoundingClientRect().left - leftBefore)).toBeLessThan(1);
        screen.unmount();
      });
    }
  }
});

describe('Métricas ML hideable KPI cards (visual)', () => {
  beforeEach(() => {
    localStorage.removeItem('metricas-ml.kpis-ocultos');
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
  });
  // The browser's storage outlives the file: leave every card visible for the suites that run next.
  afterEach(() => localStorage.removeItem('metricas-ml.kpis-ocultos'));

  for (const theme of THEMES) {
    it(`1920x1080 ${theme}: hidden cards leave the row with no gap, and with every card hidden the picker stays`, async () => {
      const screen = await renderPage({ width: 1920, height: 1080, theme });
      const strip = () => document.querySelector('section[aria-label="Indicadores del período"]');
      const picker = screen.getByRole('button', { name: 'Indicadores' });
      await picker.click();
      const group = screen.getByRole('group', { name: 'Elegir indicadores visibles' });
      await group.getByRole('checkbox', { name: 'Total Gauss' }).click();
      await group.getByRole('checkbox', { name: 'Ageing promedio' }).click();
      const cards = [...strip().children];
      expect(cards).toHaveLength(5);
      expect(new Set(cards.map((card) => card.getBoundingClientRect().top)).size).toBe(1);
      expect(Math.abs(cards.at(-1).getBoundingClientRect().right - strip().getBoundingClientRect().right)).toBeLessThan(1);
      await shot(`kpis-hidden-two-${theme}`, { width: 1920, height: 1080 });

      for (const checkbox of document.querySelectorAll('[aria-label="Elegir indicadores visibles"] input:checked')) checkbox.click();
      await expect.poll(() => strip()).toBeNull();
      await expect.element(screen.getByRole('button', { name: 'Indicadores' })).toBeVisible();
      await shot(`kpis-hidden-all-${theme}`, { width: 1920, height: 1080 });
      screen.unmount();
    });

    it(`1920x1080 ${theme}: hiding Publicidad (ML Ads) takes the ads block off the page`, async () => {
      api.get.mockImplementation((url) =>
        Promise.resolve(url === '/ml-metricas/board' ? { data: { ...BOARD_RESPONSE, kpis: { ...BOARD_RESPONSE.kpis, ads: ADS_KPIS } } } : routeGet(url)),
      );
      const screen = await renderPage({ width: 1920, height: 1080, theme });
      const block = () => document.querySelector('section[aria-label="Publicidad (ML Ads)"]');
      await expect.poll(() => block()).not.toBeNull();
      await screen.getByRole('button', { name: 'Indicadores' }).click();
      await screen.getByRole('group', { name: 'Elegir indicadores visibles' }).getByRole('checkbox', { name: 'Publicidad (ML Ads)' }).click();
      await expect.poll(() => block()).toBeNull();
      // Only the block goes: the cards stay.
      expect(document.querySelector('section[aria-label="Indicadores del período"]')).not.toBeNull();
      screen.unmount();
    });
  }
});

describe('Métricas ML "Filas finas" (visual, vistas-tipo-publicacion S5)', () => {
  const KEY = 'metricas-ml.filas-finas';
  beforeEach(() => {
    localStorage.removeItem(KEY);
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
  });
  // The browser's storage outlives the file: leave the normal density for the suites that run next.
  afterEach(() => localStorage.removeItem(KEY));

  for (const theme of THEMES) {
    it(`1920x1080 ${theme}: thin rows, every cell on one line, nothing wraps or overflows`, async () => {
      const screen = await renderPage({ width: 1920, height: 1080, theme });
      await screen.getByRole('button', { name: /Ver publicaciones de Impresora Multifunción Epson/ }).click();
      await expect.element(screen.getByText('MLA2060835678')).toBeVisible();
      const table = document.querySelector('table');
      const rowHeights = () => [...table.querySelectorAll('tbody tr')].map((tr) => tr.getBoundingClientRect().height);
      const normal = Math.max(...rowHeights());

      await screen.getByRole('button', { name: 'Filas finas' }).click();
      await expect.element(screen.getByRole('button', { name: 'Filas finas', pressed: true })).toBeVisible();
      expect(table.dataset.density).toBe('dense');
      // Every row, products and publications, one thin line.
      const dense = rowHeights();
      expect(Math.max(...dense)).toBeLessThan(normal * 0.6);
      expect(Math.max(...dense)).toBeLessThanOrEqual(32);
      await shot(`board-dense-1920-${theme}`, { width: 1920, height: 1080 });

      // Nothing pokes out of its cell: the meta beside a title is cut inside its own box (with its tooltip), so
      // the cell's scroll width, not every clipped child, is what must fit.
      const spilling = [...table.querySelectorAll('tbody td')].filter((td) => td.scrollWidth > td.clientWidth + 1);
      expect(spilling.map((td) => `${td.dataset.colId}: ${td.textContent.trim().slice(0, 40)}`)).toEqual([]);
      expect(wrapped(table.querySelectorAll('[data-money]'))).toEqual([]);
      expect(wrapped(table.querySelectorAll('td[data-col-id="last_sale"] > div'))).toEqual([]);
      const titles = table.querySelectorAll('td[data-col-id="producto"] span[title], td[data-col-id="producto"] div[title]');
      expect(titles.length).toBeGreaterThan(0);
      for (const el of titles) expect(el.getClientRects().length, el.textContent).toBe(1);
      // Anything cut in the Producto cell (title, meta, publication title) carries its whole text in a tooltip.
      const cut = [...table.querySelectorAll('td[data-col-id="producto"] *')].filter((el) => el.scrollWidth > el.clientWidth + 1);
      expect(cut.length).toBeGreaterThan(0);
      for (const el of cut) expect(el.getAttribute('title'), el.textContent).toBeTruthy();
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1920);
      screen.unmount();
    });
  }

  // Under 1600px the Producto column is narrower: no line beside another (a long title, the meta with SKU, marca and
  // count, a publication's MLA line and its title, an Agrupado product's SKU line) is squeezed to nothing, nothing
  // spills out of its cell, and whatever is cut carries its whole text in a tooltip.
  const expectProductCellsReadable = (table) => {
    // One thin line per row: a line that wrapped instead of being cut would show here.
    for (const tr of table.querySelectorAll('tbody tr')) {
      expect(tr.getBoundingClientRect().height, tr.textContent.trim().slice(0, 40)).toBeLessThanOrEqual(32);
    }
    const cells = [...table.querySelectorAll('tbody td[data-col-id="producto"]')];
    expect(cells.filter((td) => td.scrollWidth > td.clientWidth + 1).map((td) => td.textContent.trim().slice(0, 40))).toEqual([]);
    const tipped = [...table.querySelectorAll('td[data-col-id="producto"] div[title]')];
    expect(tipped.length).toBeGreaterThan(0);
    for (const el of tipped) expect(el.getBoundingClientRect().width, el.title).toBeGreaterThanOrEqual(40);
    const cut = [...table.querySelectorAll('td[data-col-id="producto"] *')].filter((el) => el.scrollWidth > el.clientWidth + 1);
    for (const el of cut) expect(el.getAttribute('title'), el.textContent).toBeTruthy();
  };

  it('1366x768 light: dense, every line of the Producto cell keeps a visible width, publications and the tree too', async () => {
    localStorage.setItem(KEY, 'true');
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board' && config?.params?.group_by === 'group') {
        return Promise.resolve({ data: { ...GROUP_BOARD_RESPONSE, dimension: config.params.dimension } });
      }
      if (url === '/ml-metricas/board/group-nodes') return Promise.resolve({ data: epsonNodesFor(config.params.path) });
      // The longest MLA line there is: 12 cuotas, "Mejor", and a catálogo Full publication.
      if (url.startsWith('/ml-metricas/board/products/')) {
        const [first, ...rest] = EPSON_PUBLICATIONS.rows;
        return Promise.resolve({
          data: { ...EPSON_PUBLICATIONS, rows: [{ ...first, listing_kind: 'cuotas_12', is_catalog: true }, ...rest] },
        });
      }
      return Promise.resolve(routeGet(url));
    });
    const screen = await renderPage({ width: 1366, height: 768, theme: 'light' });
    const table = () => document.querySelector('table');
    expect(table().dataset.density).toBe('dense');
    await screen.getByRole('button', { name: /Ver publicaciones de Impresora Multifunción Epson/ }).click();
    await expect.element(screen.getByText('MLA2060835678')).toBeVisible();
    expectProductCellsReadable(table());
    await shot('board-dense-1366-light', { width: 1366, height: 768 });

    await screen.getByRole('button', { name: 'Agrupado' }).click();
    await screen.getByRole('button', { name: /Ver .* de Epson/ }).click();
    await screen.getByRole('button', { name: /Ver .* de Impresoras/ }).click();
    await screen.getByRole('button', { name: /Ver .* de Laser/ }).click();
    await expect.element(screen.getByText(EPSON_GROUP_PRODUCTS.rows[0].sku)).toBeVisible();
    expectProductCellsReadable(table());
    await shot('board-dense-grouped-1366-light', { width: 1366, height: 768 });
    screen.unmount();
  });
});
