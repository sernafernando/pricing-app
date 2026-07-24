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
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: () => true,
    tieneAlgunPermiso: () => true,
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

beforeEach(() => {
  marcasPmAPI.misTitularidades.mockReset();
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

  it('hides the entry when the mis-titularidades call fails', async () => {
    const user = userEvent.setup();
    marcasPmAPI.misTitularidades.mockRejectedValue(new Error('network'));
    renderSidebar();
    await waitFor(() => expect(marcasPmAPI.misTitularidades).toHaveBeenCalled());
    await user.click(screen.getByText('Gestión'));
    expect(screen.queryByText('Mis Sub-PMs')).not.toBeInTheDocument();
  });
});
