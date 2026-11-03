/**
 * ML Ads, Display tab -- the real page, real CSS, real Chromium (ml-ads-cupones-display S8).
 *
 * Data: `src/test/fixtures/mlAdsDisplay.js` (real captures). At the widths operators use, in both themes:
 *  - the tab bar shows Aportes and Display, Display selected;
 *  - KPI values and money cells never overflow their box;
 *  - the 15-column table scrolls inside its card and never pushes the page sideways;
 *  - the daily cost chart is drawn.
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

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn((url) => Promise.resolve({ data: url === '/ml-ads/display' ? DISPLAY_REPORT : { campaigns: [] } })),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

const SHOTS_DIR = import.meta.env.VITE_ML_ADS_SHOTS_DIR;
const shot = async (name) => SHOTS_DIR && page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });

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
          <MemoryRouter initialEntries={['/ml-ads-aportes?tab=display']}>
            <Routes>
              <Route path="/ml-ads-aportes" element={<MlAds />} />
            </Routes>
          </MemoryRouter>,
        );
        await expect.element(screen.getByText('DisplayCatalogo-Consideracion')).toBeVisible();
        await expect.element(screen.getByRole('tab', { name: 'Display' })).toHaveAttribute('aria-selected', 'true');
        await expect.element(screen.getByRole('img', { name: /Costo diario/ })).toBeVisible();

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
        await shot(`display-${width}-${theme}`);
      });
    }
  }
});
