/**
 * The "API docs" sidebar entry follows the same permission as the `/api-docs` route guard in App.jsx
 * (`admin.ver_api_docs`; the route side is pinned by `registry/screenCatalog.test.js`). The backend
 * endpoint enforces it too; this keeps the entry out of the menu of everyone else.
 */
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Sidebar from './Sidebar';

let permisosDelUsuario = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: Array.from(permisosDelUsuario),
    tienePermiso: (codigo) => permisosDelUsuario.has(codigo),
    tieneAlgunPermiso: (codigos) => codigos.some((c) => permisosDelUsuario.has(c)),
    cargandoPermisos: false,
    loading: false,
    initialized: true,
  }),
  PermisosProvider: ({ children }) => children,
}));

// "Gestión" starts collapsed.
const renderSidebar = () => {
  render(<MemoryRouter><Sidebar /></MemoryRouter>);
  fireEvent.click(screen.getByText('Gestión'));
};

describe('API docs sidebar entry', () => {
  it('shows the entry to a user with admin.ver_api_docs', () => {
    permisosDelUsuario = new Set(['admin.ver_api_docs']);
    renderSidebar();
    expect(screen.getByText('API docs')).toBeInTheDocument();
  });

  it('hides the entry from an admin panel user without admin.ver_api_docs', () => {
    permisosDelUsuario = new Set(['admin.ver_panel']);
    renderSidebar();
    expect(screen.getByText('Admin')).toBeInTheDocument();
    expect(screen.queryByText('API docs')).not.toBeInTheDocument();
  });
});
