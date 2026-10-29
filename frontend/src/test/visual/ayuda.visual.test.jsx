/**
 * Ayuda — the index sits beside the sections without overlapping them, the
 * sections (tables included) never overflow sideways, and on a phone the
 * page never scrolls horizontally. Uses the REAL help files, so the content
 * on this branch is what gets measured. Real Chromium geometry: jsdom does
 * no layout.
 *
 * Screenshots are written only when `VITE_AYUDA_SHOTS_DIR` is set (a DEV
 * aid, never a committed baseline).
 */

import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import Ayuda from '../../pages/Ayuda';

const SHOTS_DIR = import.meta.env.VITE_AYUDA_SHOTS_DIR;

describe.each([
  { width: 1920, height: 1080, theme: 'light' },
  { width: 1366, height: 768, theme: 'dark' },
])('Ayuda at $width px, $theme', ({ width, height, theme }) => {
  it('lays out the index beside the sections, with nothing overflowing', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(<Ayuda />);

    await expect.element(screen.getByRole('heading', { level: 1, name: 'Ayuda' })).toBeVisible();
    const indice = screen.getByRole('navigation', { name: 'Índice de la ayuda' }).element().getBoundingClientRect();
    const primera = document.querySelector('article').getBoundingClientRect();
    expect(indice.right).toBeLessThanOrEqual(primera.left);

    for (const seccion of document.querySelectorAll('article')) {
      expect(seccion.scrollWidth).toBeLessThanOrEqual(seccion.clientWidth);
    }
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);

    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/ayuda-${theme}-${width}.png` });
      document.querySelector('article table')?.scrollIntoView({ block: 'center' });
      await page.screenshot({ path: `${SHOTS_DIR}/ayuda-tabla-${theme}-${width}.png` });
    }
  });
});

describe('Ayuda on a phone', () => {
  it('stacks the index above the sections and never scrolls sideways', async () => {
    await page.viewport(390, 844);
    setTheme('light');
    const screen = await render(<Ayuda />);

    await screen.getByRole('searchbox', { name: 'Buscar en la ayuda' }).fill('tickets');
    await expect.element(screen.getByText(/secci(ón|ones)$/)).toBeVisible();

    const indice = screen.getByRole('navigation', { name: 'Índice de la ayuda' }).element().getBoundingClientRect();
    const primera = document.querySelector('article').getBoundingClientRect();
    expect(indice.bottom).toBeLessThanOrEqual(primera.top);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390);

    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/ayuda-buscar-light-390.png` });
  });
});
