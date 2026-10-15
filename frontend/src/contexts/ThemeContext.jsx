import { createContext, useContext, useState, useEffect } from 'react';
import { usePermisos } from './PermisosContext';

const ThemeContext = createContext();

/** Users holding this permission see the whole app in TP-Link colors. */
export const PERMISO_TPLINK_SOLO = 'tplink.solo';
const BRAND_TPLINK = 'tplink';

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
  // useBrandFromPermisos), so it is neither persisted nor exposed as a toggle.
  const [brand, setBrand] = useState(null);

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
 * instead. Unmounting it (logout) clears the brand.
 *
 * It checks the explicit permission list, NOT `tienePermiso`: that one returns
 * true for every code when the role is SUPERADMIN, which would brand an
 * administrator's whole app.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const useBrandFromPermisos = () => {
  const { setBrand } = useTheme();
  const { permisos } = usePermisos();
  const brand = Array.isArray(permisos) && permisos.includes(PERMISO_TPLINK_SOLO)
    ? BRAND_TPLINK
    : null;

  useEffect(() => {
    setBrand(brand);
    return () => setBrand(null);
  }, [brand, setBrand]);

  return brand;
};
