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
// What the other top bar badges show: every one of them by default (the widest bar), changed per test.
const others = vi.hoisted(() => ({ truck: 34, birthdays: 1, tickets: 12 }));
const OTHERS_ALL = { truck: 34, birthdays: 1, tickets: 12 };

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
    '/ml-metricas/board': { kpis: { gross: { value: 187654321.5 } } },
    '/notificaciones/agrupadas?solo_no_leidas=false': [],
    '/notificaciones/stats': { total: 3, no_leidas: 3 },
  };
  return {
    ...original,
    default: {
      ...original.default,
      get: vi.fn(async (url) => ({
        data: url === '/free-shipping-alerts/count' ? { count: others.truck } : (answers[url] ?? {}),
      })),
    },
    ticketsAPI: {
      ...original.ticketsAPI,
      badgeCount: vi.fn(async () => ({
        data: { pendientes: others.tickets, sin_asignar: 4, asignados_a_mi: 8, sync_vikunja_habilitado: false },
      })),
    },
    rrhhAPI: {
      ...original.rrhhAPI,
      cumpleanosHoy: vi.fn(async () => ({
        data: { empleados: others.birthdays ? [{ empleado_id: 1, nombre: 'Ana', apellido: 'Paz' }] : [] },
      })),
    },
  };
});

beforeEach(() => {
  Object.assign(others, OTHERS_ALL);
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
    expect(Math.abs(box.height - truck.element().getBoundingClientRect().height)).toBeLessThanOrEqual(1);

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

  const renderBar = () =>
    render(
      <MemoryRouter>
        <ThemeProvider>
          <TopBar />
        </ThemeProvider>
      </MemoryRouter>,
    );

  const phoneBar = async (width) => {
    await page.viewport(width, 844);
    localStorage.setItem('theme', theme);
    setTheme(theme);
    renderBar();
    const badge = page.getByRole('link', { name: 'tenés 128 promos mejores para revisar' });
    await expect.element(badge).toBeVisible();
    await expect.element(page.getByText('C', { exact: true })).toBeVisible(); // the avatar's initial
    return badge.element();
  };

  // At 390 nothing may overflow, and what can still give way (the logo down to its 28px floor, plus the free
  // room) must cover CI's wider font (~8%, 12% kept) on every text of the bar.
  const LOGO_FLOOR = 28;
  const checkPhoneBar = (el) => {
    const header = el.closest('header');
    expect(header.scrollWidth).toBeLessThanOrEqual(header.clientWidth);
    const bar = header.getBoundingClientRect();
    const avatar = header.querySelector('[data-user-menu]').getBoundingClientRect();
    expect(avatar.left).toBeGreaterThanOrEqual(bar.left);
    expect(avatar.right).toBeLessThanOrEqual(bar.right);
    const [left, , right] = header.children;
    const img = left.querySelector('img').getBoundingClientRect();
    const burger = left.querySelector('button').getBoundingClientRect();
    const rightBox = right.getBoundingClientRect();
    // Real edges, not box widths: the left block may be narrower than what it holds.
    expect(burger.right).toBeLessThanOrEqual(img.left);
    expect(img.right).toBeLessThanOrEqual(rightBox.left);
    expect(rightBox.right).toBeLessThanOrEqual(bar.right - parseFloat(getComputedStyle(header).paddingRight));
    const logo = img.width;
    expect(logo).toBeGreaterThanOrEqual(LOGO_FLOOR);
    const texts = [...right.querySelectorAll('span')].filter((span) => span.offsetWidth > 0 && span.textContent.trim());
    const textWidth = texts.reduce((sum, span) => sum + span.getBoundingClientRect().width, 0);
    const room = rightBox.left - img.right + (logo - LOGO_FLOOR);
    expect(room).toBeGreaterThanOrEqual(textWidth * (CI_FONT_MARGIN - 1));
    return logo;
  };

  // 390 and 360: the common phone widths.
  it.each([390, 360])('at phone width (%i) a PM sees icon and number and the avatar stays on the bar', async (width) => {
    Object.assign(others, { truck: 0, birthdays: 0 }); // a PM's usual bar: tickets, this badge, the bell, the avatar
    const el = await phoneBar(width);
    const [label, count] = el.querySelectorAll('span');
    expect(getComputedStyle(label).display).toBe('none');
    expect(count.textContent).toBe('128');
    // ~50px: the badge's own chrome (border, padding, 16px icon, gap) stays at 29px whatever the font; the number
    // is what CI's wider font stretches.
    expect(el.getBoundingClientRect().width - count.getBoundingClientRect().width).toBeLessThanOrEqual(30);
    const logo = checkPhoneBar(el);
    if (width === 390) expect(logo).toBe(104); // the logo only gives way when the bar needs it
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/mejores-ofertas-topbar-${width}-pm-${theme}.png` });
  });

  it.each([390, 360])('at phone width (%i) every badge at once still fits: the logo gives way', async (width) => {
    const el = await phoneBar(width); // birthday, tickets, truck, this badge, the bell, the avatar
    expect(el.closest('header').querySelectorAll('[data-user-menu], [data-ticket-badge]').length).toBe(2);
    checkPhoneBar(el);
    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/mejores-ofertas-topbar-${width}-all-badges-${theme}.png` });
    }
  });
});
