/**
 * Admin "Marcas sin stock" — the exception list and the brand search fit the
 * viewport at desktop and phone widths, in both themes, with no horizontal
 * page scroll. Real Chromium geometry: jsdom does no layout.
 *
 * Screenshots are written only when `VITE_MARCAS_VISIBLES_SHOTS_DIR` is set (a
 * DEV aid, never a committed baseline).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import PanelMarcasVisibles from '../../components/PanelMarcasVisibles';
import api from '../../services/api';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const SHOTS_DIR = import.meta.env.VITE_MARCAS_VISIBLES_SHOTS_DIR;

const PAYLOAD = {
  excepciones: [
    { id: 1, marca: 'Kingston', creado_por: 'Carolina Lépore', created_at: '2026-11-13T12:00:00Z', con_stock: true },
    { id: 2, marca: 'Verbatim', creado_por: 'Ramiro Echeverría', created_at: '2026-11-12T15:30:00Z', con_stock: false },
    { id: 3, marca: 'Hikvision Professional Series', creado_por: null, created_at: '2026-11-01T09:00:00Z', con_stock: false },
  ],
  marcas: [
    { marca: 'Epson', con_stock: true, en_excepcion: false },
    { marca: 'Epsilon Audio', con_stock: false, en_excepcion: false },
    { marca: 'Epson Professional Imaging Solutions', con_stock: false, en_excepcion: false },
    { marca: 'Kingston', con_stock: true, en_excepcion: true },
    { marca: 'Verbatim', con_stock: false, en_excepcion: true },
  ],
};

beforeEach(() => {
  api.get.mockResolvedValue({ data: PAYLOAD });
});

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
  { width: 390, height: 844, theme: 'light' },
  { width: 390, height: 844, theme: 'dark' },
])('Marcas sin stock at $width px, $theme', ({ width, height, theme }) => {
  it('shows the list and the search without horizontal page scroll', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    // The Admin page's side gutter (16px on a phone).
    const screen = await render(
      <div style={{ padding: '0 16px' }}>
        <PanelMarcasVisibles />
      </div>,
    );

    await expect.element(screen.getByText('Verbatim')).toBeVisible();
    await userEvent.fill(screen.getByLabelText('Agregar una marca'), 'eps');
    await expect.element(screen.getByRole('button', { name: 'Agregar Epsilon Audio' })).toBeVisible();

    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    const add = screen.getByRole('button', { name: 'Agregar Epson Professional Imaging Solutions' }).element();
    expect(add.getBoundingClientRect().right).toBeLessThanOrEqual(width);

    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/marcas-sin-stock-${width}-${theme}.png` });
    }
  });
});
