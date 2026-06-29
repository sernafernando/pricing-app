/**
 * Test helper — wraps the component under test with the minimal providers
 * required by Productos.jsx:
 *   1. MemoryRouter — so useSearchParams works in jsdom
 *
 * NOTE: PermisosContext and authStore are both mocked globally in setup.js.
 *   - usePermisos() → vi.mock('../contexts/PermisosContext') → tienePermiso always true
 *   - useAuthStore() → vi.mock('../store/authStore') → token: 'test-token', user stub
 * No additional provider wrappers are needed here.
 */

import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';

/**
 * Render a component inside a MemoryRouter so useSearchParams works in jsdom.
 *
 * @param {React.ReactElement} ui - Component to render
 * @param {{ initialEntries?: string[] }} opts
 */
export function renderWithRouter(ui, { initialEntries = ['/'] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      {ui}
    </MemoryRouter>
  );
}
