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
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import AportesAdsML from '../../pages/AportesAdsML';

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

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn((url) => {
      if (url === '/marcas') return Promise.resolve({ data: { marcas: ['EPSON', 'HP', 'TP-Link'] } });
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
        for (const pill of document.querySelectorAll('span[class*="keep"]')) {
          expect(pill.getBoundingClientRect().height).toBeLessThanOrEqual(24);
        }
        for (const add of document.querySelectorAll('button[aria-label^="Agregar aporte a"]')) {
          const first = add.parentElement.firstElementChild.getBoundingClientRect();
          expect(add.getBoundingClientRect().top).toBeLessThan(first.bottom);
        }
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

  it('opens the delete modal with its summary', async () => {
    const screen = await renderPage({ width: 1440, height: 900, theme: 'light' });
    await userEvent.click(screen.getByRole('button', { name: 'Borrar aporte $ 200.000,00' }));
    await expect.element(screen.getByText('¿Borrar este aporte?')).toBeVisible();
    await shot('modal-borrar-1440-light');
  });
});
