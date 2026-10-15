/**
 * The TP-Link brand is driven by an explicit permission, never by a toggle.
 *
 * `data-brand` lives next to `data-theme` on <html>: the brand picks the
 * palette, the theme still picks light or dark inside it. The permission must
 * be granted explicitly — SUPERADMIN's `tienePermiso` wildcard must NOT brand
 * an administrator's whole app.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render } from '@testing-library/react';
import { ThemeProvider, useBrandFromPermisos, useTheme, PERMISO_TPLINK_SOLO } from './ThemeContext';

const permisosStub = { permisos: [], rol: null, tienePermiso: () => true };

vi.mock('./PermisosContext', () => ({
  usePermisos: () => permisosStub,
  PermisosProvider: ({ children }) => children,
}));

const html = () => document.documentElement;

function BrandProbe() {
  const brand = useBrandFromPermisos();
  const { theme } = useTheme();
  return <span data-testid="probe">{`${brand ?? 'none'}|${theme}`}</span>;
}

const renderProbe = () =>
  render(
    <ThemeProvider>
      <BrandProbe />
    </ThemeProvider>,
  );

beforeEach(() => {
  localStorage.clear();
  permisosStub.permisos = [];
  permisosStub.rol = null;
  html().removeAttribute('data-brand');
});

afterEach(() => {
  html().removeAttribute('data-brand');
});

describe('ThemeContext — data-brand from the tplink.solo permission', () => {
  it('uses the tplink.solo permission code', () => {
    expect(PERMISO_TPLINK_SOLO).toBe('tplink.solo');
  });

  it('sets data-brand="tplink" when the user has tplink.solo', () => {
    permisosStub.permisos = ['tplink.solo', 'ml_metricas.ver'];
    const { getByTestId } = renderProbe();
    expect(html().getAttribute('data-brand')).toBe('tplink');
    expect(getByTestId('probe').textContent).toBe('tplink|light');
  });

  it('keeps data-theme independent of the brand', () => {
    localStorage.setItem('theme', 'dark');
    permisosStub.permisos = ['tplink.solo'];
    renderProbe();
    expect(html().getAttribute('data-brand')).toBe('tplink');
    expect(html().getAttribute('data-theme')).toBe('dark');
  });

  it('removes a stale data-brand when the user lacks tplink.solo', () => {
    html().setAttribute('data-brand', 'tplink');
    permisosStub.permisos = ['ml_metricas.ver'];
    renderProbe();
    expect(html().hasAttribute('data-brand')).toBe(false);
  });

  it('does not brand a SUPERADMIN through the tienePermiso wildcard', () => {
    permisosStub.rol = 'SUPERADMIN';
    permisosStub.permisos = [];
    renderProbe();
    expect(html().hasAttribute('data-brand')).toBe(false);
  });

  it('removes data-brand when the permission goes away', () => {
    permisosStub.permisos = ['tplink.solo'];
    const { rerender } = renderProbe();
    expect(html().getAttribute('data-brand')).toBe('tplink');

    permisosStub.permisos = [];
    rerender(
      <ThemeProvider>
        <BrandProbe />
      </ThemeProvider>,
    );
    expect(html().hasAttribute('data-brand')).toBe(false);
  });

  it('removes data-brand when the branded layout unmounts (logout)', () => {
    // Logout unmounts the layout (TopBar) while ThemeProvider stays mounted.
    permisosStub.permisos = ['tplink.solo'];
    const tree = (showLayout) => (
      <ThemeProvider>{showLayout && <BrandProbe />}</ThemeProvider>
    );
    const { rerender } = render(tree(true));
    expect(html().getAttribute('data-brand')).toBe('tplink');

    rerender(tree(false));
    expect(html().hasAttribute('data-brand')).toBe(false);
  });

  it('exposes no way to toggle the brand from the theme context', () => {
    let ctx;
    function Grab() {
      ctx = useTheme();
      return null;
    }
    render(
      <ThemeProvider>
        <Grab />
      </ThemeProvider>,
    );
    expect(ctx.toggleBrand).toBeUndefined();
    expect(typeof ctx.toggleTheme).toBe('function');
  });
});
