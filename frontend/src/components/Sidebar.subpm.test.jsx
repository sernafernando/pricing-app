/**
 * Sidebar conditional nav entry test (sub-pm-scope-marcas PR3): "Mis Sub-PMs"
 * must be visible only when the current user is titular of ≥1 (marca,
 * categoria) pair (GET /marcas-pm/mis-titularidades total > 0), regardless of
 * permiso — it is data-scoped, not permission-gated.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import Sidebar from './Sidebar';
import { marcasPmAPI } from '../services/api';

// Global setup.js mock only stubs tienePermiso/cargandoPermisos; Sidebar also
// calls tieneAlgunPermiso for multi-permiso items, which isn't relevant here
// but must exist to avoid a crash while rendering the rest of the menu.
// `permisosDenegados` lets a test simulate a non-admin: every permiso is
// granted except the ones listed (used for 'admin.gestionar_pms').
const permisosDenegados = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => !permisosDenegados.has(codigo),
    tieneAlgunPermiso: (codigos) => codigos.some((c) => !permisosDenegados.has(c)),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

beforeEach(() => {
  marcasPmAPI.misTitularidades.mockReset();
  // Default for the data-scoped (non-admin) cases below.
  permisosDenegados.clear();
  permisosDenegados.add('admin.gestionar_pms');
});

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe('Sidebar — Mis Sub-PMs conditional entry', () => {
  it('shows the entry when mis-titularidades returns ≥1 pair', async () => {
    const user = userEvent.setup();
    marcasPmAPI.misTitularidades.mockResolvedValue({ data: { pares: [{ id: 1, marca: 'Samsung', categoria: 'Celulares' }], total: 1 } });
    renderSidebar();
    await waitFor(() => expect(marcasPmAPI.misTitularidades).toHaveBeenCalled());
    // "Gestión" section is collapsed by default — expand it to reveal items.
    await user.click(screen.getByText('Gestión'));
    expect(await screen.findByText('Mis Sub-PMs')).toBeInTheDocument();
  });

  it('hides the entry when mis-titularidades returns 0 pairs', async () => {
    const user = userEvent.setup();
    marcasPmAPI.misTitularidades.mockResolvedValue({ data: { pares: [], total: 0 } });
    renderSidebar();
    await waitFor(() => expect(marcasPmAPI.misTitularidades).toHaveBeenCalled());
    await user.click(screen.getByText('Gestión'));
    expect(screen.queryByText('Mis Sub-PMs')).not.toBeInTheDocument();
  });

  it('shows the entry to an admin (admin.gestionar_pms) with zero titularidades', async () => {
    const user = userEvent.setup();
    permisosDenegados.clear();
    marcasPmAPI.misTitularidades.mockResolvedValue({ data: { pares: [], total: 0 } });
    renderSidebar();
    await waitFor(() => expect(marcasPmAPI.misTitularidades).toHaveBeenCalled());
    await user.click(screen.getByText('Gestión'));
    expect(await screen.findByText('Mis Sub-PMs')).toBeInTheDocument();
  });

  it('hides the entry when the mis-titularidades call fails', async () => {
    const user = userEvent.setup();
    marcasPmAPI.misTitularidades.mockRejectedValue(new Error('network'));
    renderSidebar();
    await waitFor(() => expect(marcasPmAPI.misTitularidades).toHaveBeenCalled());
    await user.click(screen.getByText('Gestión'));
    expect(screen.queryByText('Mis Sub-PMs')).not.toBeInTheDocument();
  });
});
