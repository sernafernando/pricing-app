/**
 * Sell-out monto total reparto by criterion (S3) in real Chromium: the "Repartir según" selector and its button on one
 * line, and the per-product preview with its actions, inside a panel-width section, light and dark.
 *
 *   VITE_SELLOUT_CRITERIO_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellOutRepartoCriterio
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellOutReparto from '../../components/sellOut/SellOutReparto';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANA_MONTO_TOTAL, VISTAS_PREVIAS } from '../../components/sellOut/sellOutFixtures';

vi.mock('../../services/api', () => ({ default: { get: vi.fn() }, productosAPI: { listar: vi.fn() } }));
vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { repartir: vi.fn(), vistaPreviaReparto: vi.fn(), repartirPorCriterio: vi.fn(), detalle: vi.fn() },
}));

const SHOTS_DIR = import.meta.env.VITE_SELLOUT_CRITERIO_SHOTS_DIR;

describe('SellOutReparto by criterion (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`fits the selector and the preview in a 480px panel, ${theme}`, async () => {
      await page.viewport(1280, 1100);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      sellOutAPI.vistaPreviaReparto.mockResolvedValue({ data: VISTAS_PREVIAS.unidades });
      const screen = await render(
        <div data-testid="panel" style={{ width: 480, padding: 16, background: 'var(--cf-bg-card)' }}>
          <SellOutReparto campana={{ ...CAMPANA_MONTO_TOTAL, reparto_criterio: null }} editable porCriterio onGuardado={() => {}} />
        </div>,
      );
      await screen.getByLabelText('Repartir según').selectOptions('unidades');
      await screen.getByRole('button', { name: 'Ver reparto' }).click();
      await expect.element(screen.getByRole('table', { name: 'Vista previa del reparto' })).toBeVisible();

      const panel = document.querySelector('[data-testid="panel"]');
      const derecha = panel.getBoundingClientRect().right;
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      for (const control of panel.querySelectorAll('select, input, button, td')) {
        expect(control.getBoundingClientRect().right).toBeLessThanOrEqual(derecha);
      }
      const selector = screen.getByLabelText('Repartir según').element().getBoundingClientRect();
      const boton = screen.getByRole('button', { name: 'Ver reparto' }).element().getBoundingClientRect();
      expect(Math.abs(selector.bottom - boton.bottom)).toBeLessThan(3); // one line
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellout-reparto-criterio-${theme}.png` });
    });
  }
});
