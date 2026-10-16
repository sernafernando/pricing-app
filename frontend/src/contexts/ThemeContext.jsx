import { createContext, useContext, useState, useEffect, useRef } from 'react';
import { usePermisos } from './PermisosContext';

const ThemeContext = createContext();

/** TP-only users (data lock, later) also see the whole app in TP-Link colors. */
export const PERMISO_TPLINK_SOLO = 'tplink.solo';
/** Turns on only the TP-Link theme, with no data restriction. */
export const PERMISO_TPLINK_TEMA = 'tplink.tema';
const PERMISOS_BRAND_TPLINK = [PERMISO_TPLINK_TEMA, PERMISO_TPLINK_SOLO];
const BRAND_TPLINK = 'tplink';
const KNOWN_BRANDS = new Set([BRAND_TPLINK]);

/**
 * The last resolved brand, remembered per viewer so a reload paints the brand
 * before permissions load (no base-theme flash). A convenience only: once the
 * permissions arrive they decide, and logout clears it (see authStore.js,
 * which repeats this key to avoid an import cycle).
 */
export const BRAND_STORAGE_KEY = 'brand';

const readStoredBrand = () => {
  try {
    const stored = localStorage.getItem(BRAND_STORAGE_KEY);
    return KNOWN_BRANDS.has(stored) ? stored : null;
  } catch {
    return null;
  }
};

const writeStoredBrand = (brand) => {
  try {
    if (brand) {
      localStorage.setItem(BRAND_STORAGE_KEY, brand);
    } else {
      localStorage.removeItem(BRAND_STORAGE_KEY);
    }
  } catch {
    // Storage blocked (private window, previews): the permission still applies.
  }
};

/** Call before the first render (main.jsx) so a stored brand paints immediately. */
// eslint-disable-next-line react-refresh/only-export-components
export const applyStoredBrand = () => {
  const brand = readStoredBrand();
  if (brand) {
    document.documentElement.setAttribute('data-brand', brand);
  }
};

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
};

export const ThemeProvider = ({ children }) => {
  const [theme, setTheme] = useState(() => {
    // Cargar tema guardado o usar 'light' por defecto
    return localStorage.getItem('theme') || 'light';
  });

  const [highContrast, setHighContrast] = useState(() => {
    // Cargar preferencia de alto contraste
    return localStorage.getItem('highContrast') === 'true';
  });

  useEffect(() => {
    // Aplicar la clase al documento
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  // The brand is NOT user-toggleable: it is derived from a permission (see
  // useBrandFromPermisos), so it is never exposed as a toggle. It starts from
  // the stored brand so the provider does not undo applyStoredBrand().
  const [brand, setBrand] = useState(readStoredBrand);

  useEffect(() => {
    const root = document.documentElement;
    if (brand) {
      root.setAttribute('data-brand', brand);
    } else {
      root.removeAttribute('data-brand');
    }
  }, [brand]);

  useEffect(() => {
    // Aplicar/remover clase high-contrast
    if (highContrast) {
      document.documentElement.classList.add('high-contrast');
      console.log('✅ High contrast activado - clase agregada a <html>');
    } else {
      document.documentElement.classList.remove('high-contrast');
      console.log('❌ High contrast desactivado - clase removida de <html>');
    }
    localStorage.setItem('highContrast', highContrast);
  }, [highContrast]);

  const toggleTheme = () => {
    setTheme(prevTheme => prevTheme === 'light' ? 'dark' : 'light');
  };

  const toggleHighContrast = () => {
    setHighContrast(prev => !prev);
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, highContrast, toggleHighContrast, brand, setBrand }}>
      {children}
    </ThemeContext.Provider>
  );
};

/**
 * Syncs `data-brand` from the permissions and returns the active brand.
 *
 * ThemeProvider sits OUTSIDE PermisosProvider in App.jsx, so the provider
 * cannot read permissions itself; the authenticated layout calls this hook
 * instead.
 *
 * While permissions are still loading the stored brand stays in place; once
 * they load they are the source of truth for both `data-brand` and the stored
 * value. Unmounting the hook after that (logout) clears the brand.
 *
 * It checks the explicit permission list, NOT `tienePermiso`: that one returns
 * true for every code when the role is SUPERADMIN, which would brand an
 * administrator's whole app.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const useBrandFromPermisos = () => {
  const { brand: currentBrand, setBrand } = useTheme();
  const { permisos, initialized } = usePermisos();
  // `initialized` is false only while the first load is pending (or failed).
  const loaded = initialized !== false;
  const resolved = Array.isArray(permisos)
    && PERMISOS_BRAND_TPLINK.some((codigo) => permisos.includes(codigo))
    ? BRAND_TPLINK
    : null;
  const appliedRef = useRef(false);

  useEffect(() => {
    if (!loaded) return;
    setBrand(resolved);
    writeStoredBrand(resolved);
    appliedRef.current = true;
  }, [loaded, resolved, setBrand]);

  useEffect(() => () => {
    if (appliedRef.current) setBrand(null);
  }, [setBrand]);

  return loaded ? resolved : currentBrand;
};
