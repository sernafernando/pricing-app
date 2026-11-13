/**
 * MejoresOfertasBadge in the real TopBar: the owner's sentence fits whole beside
 * every other top bar badge (birthdays, tickets, the free-shipping truck) and the
 * Facturado ML card, in both themes, with room to spare for CI's fonts (DejaVu,
 * about 8% wider than Inter). Real Chromium geometry: jsdom does no layout.
 *
 * Screenshots are written only when `VITE_MEJORES_OFERTAS_SHOTS_DIR` is set (a DEV
 * aid, never a committed baseline).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import { ThemeProvider } from '../../contexts/ThemeContext';
import { useAuthStore } from '../../store/authStore';
import TopBar from '../../components/TopBar';

const SHOTS_DIR = import.meta.env.VITE_MEJORES_OFERTAS_SHOTS_DIR;
// CI renders with DejaVu (~8% wider than the app's fonts): every check keeps more than that spare.
const CI_FONT_MARGIN = 1.12;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], rol: null, tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../../contexts/SSEContext', () => ({ useSSE: () => ({ isDegraded: () => false }) }));
vi.mock('../../hooks/useSSEChannel', () => ({ useSSEChannel: () => {} }));
vi.mock('../../hooks/useWeather', () => ({ useWeather: () => ({ weather: null }) }));

vi.mock('../../services/api', async (importOriginal) => {
  const original = await importOriginal();
  const answers = {
    '/ml-publications/view/mejores-ofertas/count': { pm_id: 17, count: 128 },
    '/free-shipping-alerts/count': { count: 34 },
    '/ml-metricas/board': { kpis: { gross: { value: 187654321.5 } } },
    '/notificaciones/agrupadas?solo_no_leidas=false': [],
    '/notificaciones/stats': { total: 3, no_leidas: 3 },
  };
  return {
    ...original,
    default: { ...original.default, get: vi.fn(async (url) => ({ data: answers[url] ?? {} })) },
    ticketsAPI: {
      ...original.ticketsAPI,
      badgeCount: vi.fn(async () => ({
        data: { pendientes: 12, sin_asignar: 4, asignados_a_mi: 8, sync_vikunja_habilitado: false },
      })),
    },
    rrhhAPI: {
      ...original.rrhhAPI,
      cumpleanosHoy: vi.fn(async () => ({ data: { empleados: [{ empleado_id: 1, nombre: 'Ana', apellido: 'Paz' }] } })),
    },
  };
});

beforeEach(() => {
  useAuthStore.setState({ user: { id: 17, nombre: 'Carolina Lépore', username: 'clepore', rol: 'ADMIN' } });
});

describe.each(['light', 'dark'])('MejoresOfertasBadge in the TopBar (%s)', (theme) => {
  it('shows the whole sentence at 1440 with room for CI fonts', async () => {
    await page.viewport(1440, 900);
    localStorage.setItem('theme', theme); // the provider applies the stored theme on mount
    setTheme(theme);
    render(
      <MemoryRouter>
        <ThemeProvider>
          <TopBar />
        </ThemeProvider>
      </MemoryRouter>,
    );
    const badge = page.getByRole('link', { name: 'tenés 128 promos mejores para revisar' });
    await expect.element(badge).toBeVisible();
    await expect.element(badge).toHaveAttribute('href', '/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=17');
    const truck = page.getByTitle(/^34 publicaci/); // the free-shipping truck beside it
    await expect.element(truck).toBeVisible();

    const el = badge.element();
    const label = el.querySelector('span');
    expect(label.textContent).toBe('tenés 128 promos mejores para revisar');
    expect(getComputedStyle(label).display).not.toBe('none');
    expect(label.scrollWidth).toBeLessThanOrEqual(label.clientWidth); // never clipped

    // The top bar's content, the sentence included, fits its width with the CI font margin to spare.
    const header = el.closest('header');
    const cs = getComputedStyle(header);
    const inner = header.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    // The center block stretches: its content is what takes room, not its box.
    const [left, center, right] = header.children;
    const widthOf = (node) => node.getBoundingClientRect().width;
    const centerContent = [...center.children].reduce((sum, child) => sum + widthOf(child), 0);
    const used = widthOf(left) + centerContent + widthOf(right);
    expect(used * CI_FONT_MARGIN).toBeLessThanOrEqual(inner);

    // The badge sits inside the top bar, on one line, at the truck's height.
    const box = el.getBoundingClientRect();
    const bar = header.getBoundingClientRect();
    expect(box.right).toBeLessThanOrEqual(bar.right);
    expect(box.height).toBe(truck.element().getBoundingClientRect().height);

    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/mejores-ofertas-topbar-1440-${theme}.png` });
    }
  });

  it('keeps only the count where the sentence does not fit', async () => {
    await page.viewport(900, 700);
    localStorage.setItem('theme', theme);
    setTheme(theme);
    render(
      <MemoryRouter>
        <ThemeProvider>
          <TopBar />
        </ThemeProvider>
      </MemoryRouter>,
    );
    const badge = page.getByRole('link', { name: 'tenés 128 promos mejores para revisar' });
    await expect.element(badge).toBeVisible();
    const [label, count] = badge.element().querySelectorAll('span');
    expect(getComputedStyle(label).display).toBe('none');
    expect(count.textContent).toBe('128');
    expect(getComputedStyle(count).display).not.toBe('none');
  });
});
