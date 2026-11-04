/**
 * ML Ads, Display tab -- the real page, real CSS, real Chromium (ml-ads-cupones-display S8).
 *
 * Layout: the approved Stitch screen 56a8ea4c. Data: `src/test/fixtures/mlAdsDisplay.js` (real captures), over its
 * range 07/09-06/10/2026 with the first campaign's trend open, as the screen shows it. At the widths operators use,
 * in both themes:
 *  - the tab bar shows Aportes and Display, Display selected, with its active count;
 *  - KPI values and money cells never overflow their box;
 *  - the table scrolls inside its card and never pushes the page sideways;
 *  - the daily cost stacked by campaign and the open row's trend are drawn.
 *
 *   pnpm exec vitest run --project=visual mlAdsDisplay   (CI; locally only with the owner's OK)
 *   VITE_ML_ADS_SHOTS_DIR=/tmp/shots ...                  (also saves screenshots)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import MlAds from '../../pages/MlAds';
import { DISPLAY_REPORT } from '../fixtures/mlAdsDisplay';

const PREVIOUS_MISSING = [{ source: 'display', advertiser_id: 25713, day: '2026-08-08', status: null }];

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: {
    // No period before the captures was stored: the previous period answers with its days missing.
    get: vi.fn((url, config) =>
      Promise.resolve({
        data:
          url !== '/ml-ads/display'
            ? { campaigns: [] }
            : config.params.date_from < '2026-09-07'
              ? { ...DISPLAY_REPORT, coverage: { ...DISPLAY_REPORT.coverage, missing_days: PREVIOUS_MISSING } }
              : DISPLAY_REPORT,
      }),
    ),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

const SHOTS_DIR = import.meta.env.VITE_ML_ADS_SHOTS_DIR;
// The viewport (`name`), plus the whole page laid out at that width (`name-full`): the iframe only paints its
// viewport, so it grows to the page's height for the full shot and goes back afterwards.
const shot = async (name, width, height) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
  const shell = document.querySelector('[data-shell]');
  await page.viewport(width, Math.max(height, shell.scrollHeight + 16));
  await page.screenshot({ path: `${SHOTS_DIR}/${name}-full.png`, element: shell });
  await page.viewport(width, height);
};

describe('ML Ads Display tab (visual)', () => {
  for (const [width, height] of [
    [1280, 800],
    [1440, 900],
    [1920, 1080],
  ]) {
    for (const theme of ['light', 'dark']) {
      it(`keeps KPIs and money inside their boxes at ${width}px, ${theme}`, async () => {
        await page.viewport(width, height);
        setTheme(theme);
        document.body.style.background = 'var(--cf-bg-app)';
        const screen = await render(
          <div data-shell>
            <MemoryRouter initialEntries={['/ml-ads-aportes?tab=display']}>
              <Routes>
                <Route path="/ml-ads-aportes" element={<MlAds />} />
              </Routes>
            </MemoryRouter>
          </div>,
        );
        await screen.getByLabelText('Desde').fill('2026-09-07');
        await screen.getByLabelText('Hasta').fill('2026-10-06');
        await expect.element(screen.getByText('DisplayCatalogo-Consideracion')).toBeVisible();
        await expect.element(screen.getByRole('tab', { name: 'Display' })).toHaveAttribute('aria-selected', 'true');
        await expect.element(screen.getByRole('tab', { name: 'Display' })).toHaveTextContent('4 Activas');
        await expect.element(screen.getByRole('img', { name: /Costo diario por campaña/ })).toBeVisible();
        await screen.getByRole('button', { name: 'Ver tendencia diaria de DisplayCatalogo', exact: true }).click();
        await expect.element(screen.getByRole('img', { name: 'Costo diario de DisplayCatalogo', exact: true })).toBeVisible();

        for (const value of document.querySelectorAll('span[class*="kpiValue"]')) {
          expect(value.scrollWidth).toBeLessThanOrEqual(value.parentElement.clientWidth);
        }
        for (const cell of document.querySelectorAll('td[class*="num"]')) {
          expect(cell.scrollWidth).toBeLessThanOrEqual(cell.clientWidth + 1);
        }
        for (const name of document.querySelectorAll('span[class*="campaignName"]')) {
          expect(name.getBoundingClientRect().height).toBeLessThanOrEqual(42);
        }
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
        await shot(`display-${width}-${theme}`, width, height);
      });
    }
  }
});
