/**
 * TopBar logo swap: TP-only users see the TP-Link logo, everyone else keeps the
 * app logo. The TopBar is also where the brand is synced from the permission,
 * because it is the first component inside both ThemeProvider and
 * PermisosProvider on every authenticated page.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import { ThemeProvider } from '../contexts/ThemeContext';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import TopBar, { TPLINK_LOGO_SRC } from './TopBar';

const permisosStub = { permisos: [], rol: null, tienePermiso: () => true };

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => permisosStub,
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../hooks/useWeather', () => ({ useWeather: () => ({ weather: null }) }));
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./FreeShippingBadge', () => ({ default: () => null }));
vi.mock('./TicketBadge', () => ({ default: () => null }));
vi.mock('./BirthdayBadge', () => ({ default: () => null }));
vi.mock('./ThemeToggleSimple', () => ({ default: () => null }));

const renderTopBar = () =>
  renderWithRouter(
    <ThemeProvider>
      <TopBar />
    </ThemeProvider>,
  );

beforeEach(() => {
  permisosStub.permisos = [];
  document.documentElement.removeAttribute('data-brand');
});

afterEach(() => {
  document.documentElement.removeAttribute('data-brand');
});

describe('TopBar — brand logo', () => {
  it('shows the TP-Link logo for tplink.solo users and brands the document', () => {
    permisosStub.permisos = ['tplink.solo'];
    renderTopBar();
    const logo = screen.getByRole('img', { name: 'TP-Link' });
    expect(logo.getAttribute('src')).toBe('/brand/tplink-logo-white.png');
    expect(document.documentElement.getAttribute('data-brand')).toBe('tplink');
  });

  it('keeps the app logo for everyone else', () => {
    permisosStub.permisos = ['ml_metricas.ver'];
    renderTopBar();
    expect(screen.queryByRole('img', { name: 'TP-Link' })).toBeNull();
    const logo = screen.getByRole('img', { name: 'Logo' });
    expect(logo.getAttribute('src')).not.toContain('tplink');
    expect(document.documentElement.hasAttribute('data-brand')).toBe(false);
  });

  it('points the TP-Link logo at an asset that exists in public/', () => {
    const publicDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../public');
    expect(TPLINK_LOGO_SRC).toMatch(/^\//);
    expect(fs.existsSync(path.join(publicDir, TPLINK_LOGO_SRC))).toBe(true);
  });
});
