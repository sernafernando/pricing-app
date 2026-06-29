/**
 * Test helper — wraps the component under test with the minimal providers
 * required by Productos.jsx:
 *   1. MemoryRouter — so useSearchParams works in jsdom
 *   2. Permissive PermisosContext stub — all tienePermiso() calls return true
 *
 * useAuthStore reads from zustand (in-memory) — no wrapper needed; we set a
 * fake token in localStorage so the auth guard passes without a real JWT.
 */

import { createContext, useContext } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';

// ---------------------------------------------------------------------------
// Stub PermisosContext: grants every permission, no API calls made
// ---------------------------------------------------------------------------
const PermisosContext = createContext();

// eslint-disable-next-line react-refresh/only-export-components
export const usePermisos = () => useContext(PermisosContext);

function PermisosProviderStub({ children }) {
  return (
    <PermisosContext.Provider
      value={{
        permisos: [],
        tienePermiso: () => true,
        cargandoPermisos: false,
      }}
    >
      {children}
    </PermisosContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// renderWithRouter — call this instead of RTL's render() in all CS-* tests
// ---------------------------------------------------------------------------
export function renderWithRouter(ui, { initialEntries = ['/'] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <PermisosProviderStub>
        {ui}
      </PermisosProviderStub>
    </MemoryRouter>
  );
}
