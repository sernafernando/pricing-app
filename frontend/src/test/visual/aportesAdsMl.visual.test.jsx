/**
 * Aportes de marcas (Ads ML) -- the real page, real CSS, real Chromium (ml-ads-contribution-redesign S3-S5).
 *
 * The layout promises of the Stitch design, at the widths operators use (1280-1920), in both themes:
 *  - every contribution chip stays on ONE line;
 *  - money never wraps and the table never pushes the page sideways;
 *  - the add and delete modals open with their content.
 *
 *   pnpm exec vitest run --project=visual aportesAdsMl
 *   VITE_APORTES_SHOTS_DIR=/tmp/shots pnpm exec vitest run --project=visual aportesAdsMl   (also saves screenshots)
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import AportesAdsML from '../../pages/AportesAdsML';
import { APORTE_HISTORY } from '../../pages/aportesFixtures';
import { DISPLAY_REPORT } from '../fixtures/mlAdsDisplay';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const contribution = (id, campaign, extra) => ({
  id,
  advertiser_id: 25713,
  campaign_id: campaign,
  kind: 'percentage',
  value: 30,
  date_from: '2026-10-01',
  date_to: '2026-10-31',
  settlement: null,
  brand: 'Epson',
  note: null,
  created_by_id: 1,
  updated_by_id: 1,
  created_at: '2026-10-01T10:00:00',
  updated_at: '2026-10-01T10:00:00',
  ...extra,
});

const campaign = (id, name, cost, contributionTotal, contributions, extra) => ({
  advertiser_id: 25713,
  advertiser_name: 'GAUSS',
  campaign_id: id,
  name,
  status: 'active',
  cost,
  contribution: contributionTotal,
  contributions,
  ...extra,
});

const CAMPAIGNS = [
  campaign(351204887, 'Epson EcoTank – Octubre', 980000, 294000, [contribution(1, 351204887)]),
  campaign(
    351982104,
    'TP-Link Deco & AX Mesh',
    720000,
    350000,
    [contribution(2, 351982104, { kind: 'fixed_amount', value: 350000, settlement: 'full', advertiser_id: 714700 })],
    { advertiser_id: 714700, advertiser_name: 'TPLINK' },
  ),
  campaign(352441920, 'HP Ink Tank Smart 580', 310000, 200000, [
    contribution(3, 352441920, { kind: 'fixed_amount', value: 200000, settlement: 'refund_difference' }),
  ]),
  campaign(353110945, 'Logitech MX Master & Periféricos', 650000, 321000, [
    contribution(4, 353110945, { value: 50, date_to: '2026-10-15' }),
    contribution(5, 353110945, { kind: 'fixed_amount', value: 150000, settlement: 'full', date_from: '2026-10-16' }),
  ]),
  campaign(354029112, 'Samsung Monitores Essential 24"', 612300, 0, []),
  campaign(349102830, 'Brother Rotuladoras & Cintas P-Touch', 220000, 0, [], { status: 'paused' }),
];

const aporte = (id, brand, campaignId, campaignName, kind, value, covered, extra) => ({
  ...contribution(id, campaignId, { brand, kind, value }),
  channel: 'product_ads',
  advertiser_name: 'GAUSS',
  campaign_name: campaignName,
  covered,
  loaded_by: 'Lucía Fernández',
  loaded_at: '2026-10-02T10:00:00',
  edited_by: null,
  edited_at: null,
  ...extra,
});

// DERIVED: the seven aportes of Stitch 55853ac1 ("Por aporte"), with the period costs that give its tiles.
const APORTES_STITCH = {
  contributions: [
    aporte(1, 'Epson', 351204887, 'Epson EcoTank – Octubre', 'percentage', 30, 294000),
    aporte(2, 'TP-Link', 351982104, 'TP-Link Deco & AX Mesh', 'fixed_amount', 350000, 350000, { settlement: 'full' }),
    aporte(3, 'HP', 352441920, 'HP Ink Tank Smart 580', 'fixed_amount', 200000, 200000, {
      settlement: 'refund_difference',
      loaded_by: 'Martín Gómez',
      loaded_at: '2026-10-03T09:00:00',
    }),
    aporte(4, 'Logitech', 353110945, 'Logitech MX Master & Periféricos', 'percentage', 50, 171000, {
      date_to: '2026-10-15',
      loaded_by: 'Martín Gómez',
      loaded_at: '2026-10-01T09:00:00',
    }),
    aporte(5, 'Logitech', 353110945, 'Logitech MX Master & Periféricos', 'fixed_amount', 150000, 150000, {
      settlement: 'full',
      date_from: '2026-10-16',
      loaded_by: 'Martín Gómez',
      loaded_at: '2026-10-16T09:00:00',
      edited_by: 'Martín Gómez',
      edited_at: '2026-10-18T09:00:00',
    }),
    aporte(6, 'Kingston', 350819772, 'Kingston SSD & Memorias RAM', 'fixed_amount', 100000, 100000, {
      settlement: 'full',
      loaded_at: '2026-10-05T10:00:00',
    }),
    aporte(7, 'Xerox', null, null, 'percentage', 25, 300000, {
      channel: 'display',
      loaded_at: '2026-10-04T10:00:00',
    }),
  ],
  totals: { product_ads_cost: 4810000, display_cost: 1500000, no_campaign_cost: 84300 },
};

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn((url, config) => {
      if (url === '/marcas') return Promise.resolve({ data: { marcas: ['EPSON', 'HP', 'TP-Link', 'Xerox'] } });
      if (url === '/ml-ads/display') return Promise.resolve({ data: DISPLAY_REPORT });
      if (url.endsWith('/preview') && config.params.channel === 'display') {
        // DERIVED from Stitch 7512c518: Display spent 1,200,000 in the range and the aporte covers 300,000.
        const display = { spend: 1200000, counted: 300000, net: 900000, warnings: [], data_through: null, over_spend: false };
        return Promise.resolve({ data: display });
      }
      if (url === '/ml-ads/contributions') return Promise.resolve({ data: APORTES_STITCH });
      if (url.endsWith('/history')) return Promise.resolve({ data: APORTE_HISTORY });
      // DERIVED: the ledger closed through 10-20, so a range to 10-31 shows the missing-data line (ml-ads-aportes-robust S4).
      const preview = { spend: 742300, counted: 500000, net: 242300, warnings: [], data_through: '2026-10-20' };
      return Promise.resolve({ data: url.endsWith('/preview') ? preview : { campaigns: CAMPAIGNS } });
    }),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

const SHOTS_DIR = import.meta.env.VITE_APORTES_SHOTS_DIR;
const shot = async (name) => SHOTS_DIR && page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });

const renderPage = async ({ width, height, theme }) => {
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  const screen = await render(
    <MemoryRouter initialEntries={['/ml-ads-aportes']}>
      <AportesAdsML />
    </MemoryRouter>,
  );
  await expect.element(screen.getByText('Epson EcoTank – Octubre')).toBeVisible();
  return screen;
};

describe('Aportes de marcas (Ads ML) (visual)', () => {
  // A failed assertion must not leave high contrast on for the next test.
  afterEach(() => document.documentElement.classList.remove('high-contrast'));

  for (const [width, height] of [
    [1280, 800],
    [1440, 900],
    [1920, 1080],
  ]) {
    for (const theme of ['light', 'dark']) {
      it(`keeps chips on one line and money unwrapped at ${width}px, ${theme}`, async () => {
        await renderPage({ width, height, theme });
        const chips = [...document.querySelectorAll('li[class*="chip"]')];
        expect(chips.length).toBe(5);
        for (const chip of chips) expect(chip.getBoundingClientRect().height).toBeLessThanOrEqual(30);
        for (const name of document.querySelectorAll('span[class*="campaignName"]')) {
          expect(name.getBoundingClientRect().height).toBeLessThanOrEqual(42);
        }
        const states = [...document.querySelectorAll('td > span[class*="state"]')];
        expect(states.length).toBe(6);
        for (const state of states) expect(state.getBoundingClientRect().height).toBeLessThanOrEqual(24);
        // The add button has its own column, level with the row's first line.
        for (const add of document.querySelectorAll('button[aria-label^="Agregar aporte a"]')) {
          const first = add.closest('tr').querySelector('li, span[class*="none"]').getBoundingClientRect();
          expect(add.getBoundingClientRect().top).toBeLessThan(first.bottom);
          expect(add.getBoundingClientRect().left).toBeGreaterThanOrEqual(first.right);
        }
        // Every aporte row puts amount, settlement and range on the same verticals.
        const edges = (selector, side) =>
          new Set(chips.map((chip) => Math.round(chip.querySelector(selector).getBoundingClientRect()[side])));
        expect(edges('span[class*="chipValue"]', 'right').size).toBe(1);
        expect(edges('span[class*="kind"]', 'left').size).toBe(1);
        expect(edges('span[class*="chipRange"]', 'left').size).toBe(1);
        for (const cell of document.querySelectorAll('td[class*="num"]')) {
          expect(cell.scrollWidth).toBeLessThanOrEqual(cell.clientWidth + 1);
        }
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        await shot(`page-${width}-${theme}`);
      });
    }
  }

  for (const [theme, highContrast] of [
    ['light', false],
    ['dark', false],
    ['light', true],
  ]) {
    const mode = `${theme}${highContrast ? '-hc' : ''}`;
    it(`lays out the add modal: brand first, $ inside the amount, one figure per line (${mode})`, async () => {
      // Tall enough for the whole form, so the shot shows every field without scrolling the modal.
      const screen = await renderPage({ width: 1440, height: 1400, theme });
      document.documentElement.classList.toggle('high-contrast', highContrast);
      await userEvent.click(screen.getByRole('button', { name: 'Agregar aporte', exact: true }));
      await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Marca' }), 'EPSON');
      await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Campaña' }), '25713-351204887');
      await userEvent.click(screen.getByRole('button', { name: 'Monto fijo' }));
      await userEvent.fill(screen.getByLabelText('Monto', { exact: true }), '500000');
      await userEvent.click(screen.getByLabelText('Devuelve la diferencia'));
      await userEvent.fill(screen.getByLabelText('Desde', { exact: true }).nth(1), '2026-10-01');
      await userEvent.fill(screen.getByLabelText('Hasta', { exact: true }).nth(1), '2026-10-31');
      await userEvent.click(screen.getByLabelText('El monto incluye IVA'));
      await expect.element(screen.getByLabelText('Lo que cubre el aporte')).toBeVisible();
      await expect.element(screen.getByText(/Hay datos de Ads hasta el 20\/10\/2026/)).toBeVisible();

      const amount = screen.getByLabelText('Monto', { exact: true }).element();
      expect(amount.value).toBe('500.000');
      const box = amount.parentElement.getBoundingClientRect();
      const dollar = amount.parentElement.firstElementChild.getBoundingClientRect();
      expect(dollar.left).toBeGreaterThanOrEqual(box.left);
      expect(dollar.right).toBeLessThanOrEqual(amount.getBoundingClientRect().left);
      for (const figure of document.querySelectorAll('dl[aria-label="Lo que cubre el aporte"] dd')) {
        expect(getComputedStyle(figure).fontVariantNumeric).toContain('tabular-nums');
        expect(figure.getBoundingClientRect().height).toBeLessThanOrEqual(24);
      }
      const form = document.getElementById('aporte-ads-form');
      expect(form.querySelector('label').textContent).toMatch(/^Marca/);

      const modal = form.closest('.modal-tesla');
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/modal-agregar-1440-${mode}.png`, element: modal });
      document.documentElement.classList.remove('high-contrast');
    });
  }

  for (const [theme, highContrast] of [
    ['light', false],
    ['dark', false],
    ['light', true],
  ]) {
    const mode = `${theme}${highContrast ? '-hc' : ''}`;
    it(`lays out the "Por aporte" view: badges and money never wrapped, no sideways scroll (${mode})`, async () => {
      const screen = await renderPage({ width: 1440, height: 1500, theme });
      document.documentElement.classList.toggle('high-contrast', highContrast);
      await userEvent.click(screen.getByRole('button', { name: 'Por aporte' }));
      await expect.element(screen.getByText('Total (7 aportes)')).toBeVisible();

      const table = document.querySelector('table[aria-label="Aportes del período"]');
      const pills = [...table.querySelectorAll('tbody span[class*="nowrap"], tbody span[class*="pill"]')];
      expect(pills.length).toBeGreaterThan(0);
      for (const pill of pills) {
        const box = pill.getBoundingClientRect();
        const cell = pill.closest('td').getBoundingClientRect();
        expect(box.height, `"${pill.textContent}" ${box.width}px in a ${cell.width}px cell`).toBeLessThanOrEqual(26);
      }
      for (const cell of table.querySelectorAll('td[class*="num"]')) {
        expect(cell.scrollWidth).toBeLessThanOrEqual(cell.clientWidth + 1);
        // One line of figures: every text box of the cell sits on the same line. (The cell's own height is the
        // row's, which a two-line campaign name sets.)
        const range = document.createRange();
        range.selectNodeContents(cell);
        const lines = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top)));
        expect(lines.size, `"${cell.textContent}" wraps`).toBeLessThanOrEqual(1);
      }
      for (const row of table.querySelectorAll('tbody tr')) {
        const cells = [...row.children];
        // Every cell stays a table cell, so the row's borders line up across the table.
        for (const cell of cells) expect(getComputedStyle(cell).display).toBe('table-cell');
        const [name, id] = cells[2].querySelectorAll('span[class*="campaign"]');
        expect(id.getBoundingClientRect().top).toBeGreaterThanOrEqual(name.getBoundingClientRect().bottom - 1);
      }
      const displayBar = document.querySelector('section[aria-label="Por marca"] [data-channel="display"]');
      const productBar = document.querySelector('section[aria-label="Por marca"] [data-channel="product_ads"]');
      expect(getComputedStyle(displayBar).backgroundColor).not.toBe(getComputedStyle(productBar).backgroundColor);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1440);
      await shot(`por-aporte-1440-${mode}`);
      document.documentElement.classList.remove('high-contrast');
    });
  }

  for (const [theme, highContrast] of [
    ['light', false],
    ['dark', false],
    ['light', true],
  ]) {
    const mode = `${theme}${highContrast ? '-hc' : ''}`;
    it(`lays out the history modal: one card per event, struck old values, one line each (${mode})`, async () => {
      const screen = await renderPage({ width: 1440, height: 1500, theme });
      document.documentElement.classList.toggle('high-contrast', highContrast);
      await userEvent.click(screen.getByRole('button', { name: 'Por aporte' }));
      await expect.element(screen.getByText('Total (7 aportes)')).toBeVisible();
      await userEvent.click(screen.getByRole('button', { name: 'Historial del aporte de Logitech' }).nth(1));
      await expect.element(screen.getByText('Martín Gómez · 18/10/2026 10:05')).toBeVisible();

      const list = document.querySelector('ul[aria-label="Eventos del aporte"]');
      expect(list.children.length).toBe(2);
      for (const line of list.querySelectorAll('li li')) expect(line.getBoundingClientRect().height).toBeLessThanOrEqual(24);
      const struck = list.querySelector('del');
      expect(getComputedStyle(struck).textDecorationLine).toContain('line-through');
      const modal = list.closest('.modal-tesla');
      expect(modal.scrollWidth).toBeLessThanOrEqual(modal.clientWidth + 1);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/modal-historial-1440-${mode}.png`, element: modal });
      document.documentElement.classList.remove('high-contrast');
    });
  }

  for (const [theme, highContrast] of [
    ['light', false],
    ['dark', false],
    ['light', true],
  ]) {
    const mode = `${theme}${highContrast ? '-hc' : ''}`;
    it(`lays out the add modal on Display: channel after the brand, whole account, one-sentence summary (${mode})`, async () => {
      const screen = await renderPage({ width: 1440, height: 1500, theme });
      document.documentElement.classList.toggle('high-contrast', highContrast);
      await userEvent.click(screen.getByRole('button', { name: 'Agregar aporte', exact: true }));
      await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Marca' }), 'Xerox');
      const channel = screen.getByRole('group', { name: 'Canal' });
      await userEvent.click(channel.getByRole('button', { name: 'Display' }));
      const campaign = screen.getByRole('combobox', { name: 'Campaña de Display' });
      await expect.element(campaign.getByRole('option', { name: 'Toda la cuenta Display · GAUSS' })).toBeInTheDocument();
      await userEvent.selectOptions(campaign, '25713-all');
      await userEvent.click(screen.getByRole('button', { name: 'Monto fijo' }));
      await userEvent.fill(screen.getByLabelText('Monto', { exact: true }), '300000');
      await userEvent.click(screen.getByLabelText('Se recibe todo'));
      await userEvent.fill(screen.getByLabelText('Desde', { exact: true }).nth(1), '2026-10-01');
      await userEvent.fill(screen.getByLabelText('Hasta', { exact: true }).nth(1), '2026-10-31');
      const summary = screen.getByText(/^En el rango, Display gastó/);
      await expect.element(summary).toBeVisible();
      await expect
        .element(summary)
        .toHaveTextContent('En el rango, Display gastó $ 1.200.000,00; este aporte cubre $ 300.000,00.');

      const top = (el) => el.getBoundingClientRect().top;
      const [brand, group, select] = [
        screen.getByRole('combobox', { name: 'Marca' }).element(),
        channel.element(),
        campaign.element(),
      ];
      expect(top(brand)).toBeLessThan(top(group));
      expect(top(group)).toBeLessThan(top(select));
      const [productAds, display] = group.querySelectorAll('button');
      expect(display.getBoundingClientRect().top).toBe(productAds.getBoundingClientRect().top);
      await expect.element(screen.getByText(/^Toda la cuenta: el aporte cubre/)).toBeVisible();
      for (const figure of summary.element().querySelectorAll('strong, span')) {
        expect(figure.getBoundingClientRect().height).toBeLessThanOrEqual(24);
      }
      const modal = group.closest('.modal-tesla');
      expect(modal.scrollWidth).toBeLessThanOrEqual(modal.clientWidth + 1);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/modal-agregar-display-1440-${mode}.png`, element: modal });
      document.documentElement.classList.remove('high-contrast');
    });
  }

  it('opens the delete modal with its summary', async () => {
    const screen = await renderPage({ width: 1440, height: 900, theme: 'light' });
    await userEvent.click(screen.getByRole('button', { name: 'Borrar aporte $ 200.000,00' }));
    await expect.element(screen.getByText('¿Borrar este aporte?')).toBeVisible();
    await shot('modal-borrar-1440-light');
  });
});
