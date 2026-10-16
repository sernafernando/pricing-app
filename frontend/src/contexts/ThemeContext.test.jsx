/**
 * The TP-Link brand is driven by an explicit permission, never by a toggle.
 *
 * `data-brand` lives next to `data-theme` on <html>: the brand picks the
 * palette, the theme still picks light or dark inside it. The brand comes from
 * the `permisos` list the backend sends. tplink.tema / tplink.solo are opt-in
 * codes: the backend leaves them out of a SUPERADMIN's list unless they were
 * granted explicitly, so an administrator is branded only when granted. The
 * stub's always-true `tienePermiso` proves the brand never reads that function.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render } from '@testing-library/react';
import {
  ThemeProvider,
  useBrandFromPermisos,
  useTheme,
  applyStoredBrand,
  PERMISO_TPLINK_SOLO,
  PERMISO_TPLINK_TEMA,
  BRAND_STORAGE_KEY,
} from './ThemeContext';

const permisosStub = { permisos: [], rol: null, initialized: true, tienePermiso: () => true };

vi.mock('./PermisosContext', () => ({
  usePermisos: () => permisosStub,
  PermisosProvider: ({ children }) => children,
}));

// authStore's real logout is exercised below; it needs these api exports.
vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  authAPI: { login: vi.fn(), me: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
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
  permisosStub.initialized = true;
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

  it('does not brand a SUPERADMIN that was not granted the theme', () => {
    // What /permisos/mis-permisos returns for a SUPERADMIN without the grant:
    // every code except the opt-in ones.
    permisosStub.rol = 'SUPERADMIN';
    permisosStub.permisos = ['productos.ver', 'ml_metricas.ver', 'admin.gestionar_permisos'];
    renderProbe();
    expect(html().hasAttribute('data-brand')).toBe(false);
  });

  it('brands a SUPERADMIN once tplink.tema was granted explicitly', () => {
    permisosStub.rol = 'SUPERADMIN';
    permisosStub.permisos = ['productos.ver', 'admin.gestionar_permisos', 'tplink.tema'];
    renderProbe();
    expect(html().getAttribute('data-brand')).toBe('tplink');
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

describe('ThemeContext — stored brand avoids the base-theme flash on reload', () => {
  it('stores the brand under a dedicated key', () => {
    expect(BRAND_STORAGE_KEY).toBe('brand');
  });

  it('applyStoredBrand() sets data-brand synchronously, before React renders', () => {
    localStorage.setItem(BRAND_STORAGE_KEY, 'tplink');
    applyStoredBrand();
    expect(html().getAttribute('data-brand')).toBe('tplink');
  });

  it('applyStoredBrand() ignores unknown stored values', () => {
    localStorage.setItem(BRAND_STORAGE_KEY, 'acme');
    applyStoredBrand();
    expect(html().hasAttribute('data-brand')).toBe(false);
  });

  it('applyStoredBrand() survives a throwing localStorage', () => {
    const spy = vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    try {
      expect(() => applyStoredBrand()).not.toThrow();
      expect(html().hasAttribute('data-brand')).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });

  it('keeps the stored brand while permisos are still loading', () => {
    localStorage.setItem(BRAND_STORAGE_KEY, 'tplink');
    permisosStub.initialized = false;
    permisosStub.permisos = [];
    renderProbe();
    expect(html().getAttribute('data-brand')).toBe('tplink');
    expect(localStorage.getItem(BRAND_STORAGE_KEY)).toBe('tplink');
  });

  it('clears the stored brand when loaded permisos lack tplink.solo', () => {
    localStorage.setItem(BRAND_STORAGE_KEY, 'tplink');
    html().setAttribute('data-brand', 'tplink');
    permisosStub.permisos = ['ml_metricas.ver'];
    renderProbe();
    expect(html().hasAttribute('data-brand')).toBe(false);
    expect(localStorage.getItem(BRAND_STORAGE_KEY)).toBeNull();
  });

  it('stores the brand once loaded permisos include tplink.solo', () => {
    permisosStub.permisos = ['tplink.solo'];
    renderProbe();
    expect(localStorage.getItem(BRAND_STORAGE_KEY)).toBe('tplink');
  });

  it('logout clears the stored brand and data-brand', async () => {
    const { useAuthStore } = await vi.importActual('../store/authStore');
    localStorage.setItem(BRAND_STORAGE_KEY, 'tplink');
    html().setAttribute('data-brand', 'tplink');
    await useAuthStore.getState().logout();
    expect(localStorage.getItem(BRAND_STORAGE_KEY)).toBeNull();
    expect(html().hasAttribute('data-brand')).toBe(false);
  });
});

describe('ThemeContext — tplink.tema turns on only the theme', () => {
  it('uses the tplink.tema permission code', () => {
    expect(PERMISO_TPLINK_TEMA).toBe('tplink.tema');
  });

  it('tplink.tema alone turns the brand on', () => {
    permisosStub.permisos = ['tplink.tema'];
    renderProbe();
    expect(html().getAttribute('data-brand')).toBe('tplink');
    expect(localStorage.getItem(BRAND_STORAGE_KEY)).toBe('tplink');
  });

  it('tplink.solo still turns the brand on without tplink.tema', () => {
    permisosStub.permisos = ['tplink.solo'];
    renderProbe();
    expect(html().getAttribute('data-brand')).toBe('tplink');
  });

  it('neither permission leaves the brand off', () => {
    html().setAttribute('data-brand', 'tplink');
    localStorage.setItem(BRAND_STORAGE_KEY, 'tplink');
    permisosStub.permisos = ['ml_metricas.ver', 'dashboard_tplink.ver'];
    renderProbe();
    expect(html().hasAttribute('data-brand')).toBe(false);
    expect(localStorage.getItem(BRAND_STORAGE_KEY)).toBeNull();
  });
});
