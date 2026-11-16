/**
 * Cargas de PDF — the history page in real Chromium with the app's CSS (ODD `vpf-metricas-canal-fe` T3, mockup 4).
 * At 1920 px the history table and the detail card sit side by side, the table fits its card without a sideways
 * scroll, and no cell wraps.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when `VITE_CARGAS_SHOTS_DIR` is set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import CargasPdf from '../../pages/CargasPdf';
import api from '../../services/api';
import { ALCANCES, HISTORIAL } from '../../components/ventasFueraPdf/fixtures';

vi.mock('react-router-dom', () => ({
  useNavigate: () => () => {},
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
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_CARGAS_SHOTS_DIR;

// Fixed 56px TopBar + collapsed sidebar, as the operator sees it.
const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe('Cargas de PDF (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) =>
      Promise.resolve({ data: url === '/ventas-fuera-pdf/alcances' ? ALCANCES : HISTORIAL }),
    );
  });

  for (const theme of ['light', 'dark']) {
    it(`1920 ${theme}: table and detail side by side, nothing wraps or scrolls sideways`, async () => {
      await page.viewport(1920, 1080);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const screen = await render(
        <Shell>
          <CargasPdf />
        </Shell>,
      );
      await expect.element(screen.getByRole('heading', { name: 'Carga del 16/11 12:10' })).toBeVisible();
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/cargas-pdf-${theme}.png` });

      const tabla = document.querySelector('table');
      const card = tabla.closest('section');
      const detalle = document.querySelector('aside[aria-label="Detalle de la carga"]');
      expect(detalle.getBoundingClientRect().left).toBeGreaterThanOrEqual(card.getBoundingClientRect().right);
      expect(Math.abs(detalle.getBoundingClientRect().top - card.getBoundingClientRect().top)).toBeLessThan(2);
      expect(tabla.parentElement.scrollWidth).toBeLessThanOrEqual(tabla.parentElement.clientWidth + 1);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1920);
      const altos = [...tabla.querySelectorAll('tbody tr')].map((tr) => tr.getBoundingClientRect().height);
      expect(Math.max(...altos)).toBeLessThan(50);
      screen.unmount();
    });
  }
});
