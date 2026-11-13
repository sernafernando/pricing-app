/**
 * MejoresOfertasPmsBadge in the real TopBar of an admin who is also a PM: both
 * notifiers (their own sentence and the grouped one) fit beside every other badge at
 * 1440 with room for CI's fonts (DejaVu, ~8% wider), and the grouped popover opens
 * inside the viewport with every PM's name whole. Real Chromium geometry.
 *
 * Screenshots are written only when `VITE_MEJORES_OFERTAS_SHOTS_DIR` is set.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import { ThemeProvider } from '../../contexts/ThemeContext';
import { useAuthStore } from '../../store/authStore';
import TopBar from '../../components/TopBar';

const SHOTS_DIR = import.meta.env.VITE_MEJORES_OFERTAS_SHOTS_DIR;
const CI_FONT_MARGIN = 1.12;

const PMS = vi.hoisted(() => [
  { pm_id: 17, nombre: 'Carolina Lépore', count: 128 },
  { pm_id: 3, nombre: 'Ramiro Echeverría Santa María', count: 46 },
  { pm_id: 21, nombre: 'Sofía Benítez', count: 9 },
  { pm_id: 9, nombre: 'Juan Pereyra', count: 0 },
]);

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
    '/ml-publications/view/mejores-ofertas/por-pm': { pms: PMS, total: 183 },
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

describe.each(['light', 'dark'])('MejoresOfertasPmsBadge in the TopBar (%s)', (theme) => {
  it('fits beside the PM badge at 1440 and opens every PM inside the viewport', async () => {
    await page.viewport(1440, 900);
    localStorage.setItem('theme', theme);
    setTheme(theme);
    render(
      <MemoryRouter>
        <ThemeProvider>
          <TopBar />
        </ThemeProvider>
      </MemoryRouter>,
    );
    await expect.element(page.getByRole('link', { name: 'tenés 128 promos mejores para revisar' })).toBeVisible();
    const button = page.getByRole('button', { name: 'Promos mejores por PM: 183 en total' });
    await expect.element(button).toBeVisible();

    const header = button.element().closest('header');
    const [left, center, right] = header.children;
    const widthOf = (node) => node.getBoundingClientRect().width;
    const cs = getComputedStyle(header);
    const inner = header.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const centerContent = [...center.children].reduce((sum, child) => sum + widthOf(child), 0);
    expect(header.scrollWidth).toBeLessThanOrEqual(header.clientWidth);
    // A wider font stretches the bar's texts, not its icons, paddings or gaps: the free room must cover CI's wider
    // font (~8%, 12% kept) on every visible text of the bar, as the phone checks of the PM badge do.
    const texts = [...header.querySelectorAll('span, a, button, div')].filter(
      (node) => node.offsetWidth > 0 && [...node.childNodes].some((c) => c.nodeType === Node.TEXT_NODE && c.textContent.trim()),
    );
    const textWidth = texts.reduce((sum, node) => sum + widthOf(node), 0);
    const room = inner - (widthOf(left) + centerContent + widthOf(right));
    expect(room).toBeGreaterThanOrEqual(textWidth * (CI_FONT_MARGIN - 1));
    expect(button.element().getBoundingClientRect().height).toBe(34);

    await userEvent.click(button);
    const dialog = page.getByRole('dialog', { name: 'Promos mejores por PM' });
    await expect.element(dialog).toBeVisible();
    const box = dialog.element().getBoundingClientRect();
    expect(box.left).toBeGreaterThanOrEqual(0);
    expect(box.right).toBeLessThanOrEqual(window.innerWidth);
    expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
    const rows = [...dialog.element().querySelectorAll('a')];
    expect(rows.map((row) => row.getAttribute('href'))).toEqual(
      PMS.map((pm) => `/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=${pm.pm_id}`),
    );
    for (const row of rows) {
      const name = row.querySelector('span');
      expect(name.scrollWidth).toBeLessThanOrEqual(name.clientWidth); // never clipped
      expect(row.getBoundingClientRect().height).toBeLessThanOrEqual(40); // one line each, the long one too
    }

    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/mejores-ofertas-pms-topbar-1440-${theme}.png` });
  });

  it.each([481, 480, 390, 360])('at %ipx the grouped notifier hides only on small phones', async (width) => {
    await page.viewport(width, 844);
    localStorage.setItem('theme', theme);
    setTheme(theme);
    render(
      <MemoryRouter>
        <ThemeProvider>
          <TopBar />
        </ThemeProvider>
      </MemoryRouter>,
    );
    // The PM's own badge stays on every width; the grouped one is gone at <=480px.
    await expect.element(page.getByRole('link', { name: 'tenés 128 promos mejores para revisar' })).toBeVisible();
    const button = page.getByRole('button', { name: 'Promos mejores por PM: 183 en total', includeHidden: true });
    if (width > 480) {
      await expect.element(button).toBeVisible();
    } else {
      await expect.element(button).not.toBeVisible();
      const header = button.element().closest('header');
      expect(header.scrollWidth).toBeLessThanOrEqual(header.clientWidth);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/mejores-ofertas-pms-topbar-${width}-${theme}.png` });
    }
  });
});
