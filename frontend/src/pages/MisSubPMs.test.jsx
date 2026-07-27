/**
 * Tests for MisSubPMs.jsx (sub-pm-scope-marcas PR3) — the sub-PM delegation
 * surface, in both titular and admin mode.
 *
 * Scope:
 *   - Renders titular pairs from GET /marcas-pm/mis-titularidades.
 *   - Admin mode (admin.gestionar_pms): all pairs from GET /marcas-pm,
 *     including pairs with no titular; admin-specific copy.
 *   - Selecting a pair loads its sub-PMs (GET /marcas-pm/sub-pms).
 *   - Grant flow: pick a user, submit, POST /marcas-pm/sub-pms, list refreshes.
 *   - Revoke flow: DELETE /marcas-pm/sub-pms/{id}, list refreshes.
 *   - Error states surface backend `detail` verbatim (403/400/404-style).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MisSubPMs from './MisSubPMs';
import { marcasPmAPI } from '../services/api';

// The global setup mock grants every permiso; this page branches on
// `admin.gestionar_pms`, so tests need to control it explicitly.
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

// Shape of GET /marcas-pm (admin): all pairs, titular optional.
const TODOS_LOS_PARES = [
  { id: 1, marca: 'Samsung', categoria: 'Celulares', usuario_id: 7, usuario_nombre: 'Otro PM' },
  { id: 99, marca: 'Huerfana', categoria: 'Sin Titular', usuario_id: null, usuario_nombre: null },
];

const PARES = {
  pares: [
    { id: 1, marca: 'Samsung', categoria: 'Celulares' },
    { id: 2, marca: 'LG', categoria: 'Televisores' },
  ],
  total: 2,
};

const SUB_PMS = [
  { id: 10, marca: 'Samsung', categoria: 'Celulares', usuario_id: 5, usuario_nombre: 'Ana', creado_por: 1, created_at: null },
];

const USUARIOS = [
  { id: 1, nombre: 'Titular', email: 'titular@x.com', rol: 'ventas' },
  { id: 5, nombre: 'Ana', email: 'ana@x.com', rol: 'ventas' },
  { id: 6, nombre: 'Beto', email: 'beto@x.com', rol: 'ventas' },
];

beforeEach(() => {
  marcasPmAPI.misTitularidades.mockReset().mockResolvedValue({ data: PARES });
  marcasPmAPI.listarSubPMs.mockReset().mockResolvedValue({ data: SUB_PMS });
  marcasPmAPI.crearSubPM.mockReset().mockResolvedValue({ data: {} });
  marcasPmAPI.eliminarSubPM.mockReset().mockResolvedValue({ data: {} });
  marcasPmAPI.listarUsuariosPM.mockReset().mockResolvedValue({ data: USUARIOS });
  marcasPmAPI.listarTodosLosPares.mockReset().mockResolvedValue({ data: TODOS_LOS_PARES });
  // Default: non-admin titular. Admin tests clear this.
  permisosDenegados.clear();
  permisosDenegados.add('admin.gestionar_pms');
});

describe('MisSubPMs', () => {
  it('renders the titular pairs from mis-titularidades', async () => {
    render(<MisSubPMs />);
    await waitFor(() => expect(marcasPmAPI.misTitularidades).toHaveBeenCalled());
    expect(await screen.findByText('Samsung / Celulares')).toBeInTheDocument();
    expect(screen.getByText('LG / Televisores')).toBeInTheDocument();
  });

  it('shows an empty state when the user is titular of no pair', async () => {
    marcasPmAPI.misTitularidades.mockResolvedValue({ data: { pares: [], total: 0 } });
    render(<MisSubPMs />);
    expect(await screen.findByText(/no sos titular/i)).toBeInTheDocument();
  });

  it('does NOT fetch the user list when the user is titular of no pair', async () => {
    marcasPmAPI.misTitularidades.mockResolvedValue({ data: { pares: [], total: 0 } });
    render(<MisSubPMs />);
    await screen.findByText(/no sos titular/i);
    await waitFor(() => expect(marcasPmAPI.misTitularidades).toHaveBeenCalled());
    expect(marcasPmAPI.listarUsuariosPM).not.toHaveBeenCalled();
  });

  it('loads sub-PMs for the selected pair', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await user.click(await screen.findByText('Samsung / Celulares'));
    await waitFor(() => expect(marcasPmAPI.listarSubPMs).toHaveBeenCalledWith('Samsung', 'Celulares'));
    expect(await screen.findByText('Ana')).toBeInTheDocument();
  });

  it('grants a sub-PM and refreshes the list', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await user.click(await screen.findByText('Samsung / Celulares'));
    await screen.findByText('Ana');

    // The titular (current logged-in user, id 1) is never offered as a sub-PM.
    expect(screen.queryByRole('option', { name: 'Titular' })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/usuario a delegar/i), '6');
    await user.click(screen.getByRole('button', { name: /otorgar/i }));

    await waitFor(() =>
      expect(marcasPmAPI.crearSubPM).toHaveBeenCalledWith({
        marca: 'Samsung',
        categoria: 'Celulares',
        usuario_id: 6,
      }),
    );
    expect(marcasPmAPI.listarSubPMs).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('Sub-PM otorgado')).toBeInTheDocument();
  });

  it('asks for confirmation before revoking, and cancel does not call the API', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await user.click(await screen.findByText('Samsung / Celulares'));
    await screen.findByText('Ana');

    await user.click(screen.getByRole('button', { name: /revocar sub-pm de ana/i }));
    expect(await screen.findByText(/¿revocar el sub-pm de ana/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /cancelar revocación/i }));
    expect(marcasPmAPI.eliminarSubPM).not.toHaveBeenCalled();
    expect(screen.queryByText(/¿revocar el sub-pm de ana/i)).not.toBeInTheDocument();
  });

  it('revokes a sub-PM after confirmation and refreshes the list', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await user.click(await screen.findByText('Samsung / Celulares'));
    await screen.findByText('Ana');

    await user.click(screen.getByRole('button', { name: /revocar sub-pm de ana/i }));
    await user.click(screen.getByRole('button', { name: /confirmar revocación del sub-pm de ana/i }));

    await waitFor(() => expect(marcasPmAPI.eliminarSubPM).toHaveBeenCalledWith(10));
    expect(marcasPmAPI.listarSubPMs).toHaveBeenCalledTimes(2);
  });

  it('surfaces backend error detail verbatim on grant failure', async () => {
    const user = userEvent.setup();
    marcasPmAPI.crearSubPM.mockRejectedValue({
      response: { data: { detail: 'El titular ya tiene acceso total; no puede auto-otorgarse como sub-PM' } },
    });
    render(<MisSubPMs />);
    await user.click(await screen.findByText('Samsung / Celulares'));
    await screen.findByText('Ana');

    await user.selectOptions(screen.getByLabelText(/usuario a delegar/i), '6');
    await user.click(screen.getByRole('button', { name: /otorgar/i }));

    expect(await screen.findByText(/no puede auto-otorgarse como sub-pm/i)).toBeInTheDocument();
  });

  it('does NOT list all pairs for a non-admin titular', async () => {
    render(<MisSubPMs />);
    await screen.findByText('Samsung / Celulares');
    expect(marcasPmAPI.listarTodosLosPares).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Mis Sub-PMs' })).toBeInTheDocument();
  });

  it('surfaces backend error detail verbatim on revoke failure', async () => {
    const user = userEvent.setup();
    marcasPmAPI.eliminarSubPM.mockRejectedValue({
      response: { data: { detail: 'No tienes permisos sobre este par marca-categoría' } },
    });
    render(<MisSubPMs />);
    await user.click(await screen.findByText('Samsung / Celulares'));
    await screen.findByText('Ana');

    await user.click(screen.getByRole('button', { name: /revocar sub-pm de ana/i }));
    await user.click(screen.getByRole('button', { name: /confirmar revocación del sub-pm de ana/i }));

    expect(await screen.findByText(/no tienes permisos sobre este par/i)).toBeInTheDocument();
  });
});

describe('MisSubPMs — admin mode (admin.gestionar_pms)', () => {
  beforeEach(() => {
    permisosDenegados.clear();
  });

  it('lists every pair from GET /marcas-pm, including pairs with no titular', async () => {
    render(<MisSubPMs />);
    await waitFor(() => expect(marcasPmAPI.listarTodosLosPares).toHaveBeenCalled());
    expect(marcasPmAPI.misTitularidades).not.toHaveBeenCalled();
    expect(await screen.findByText('Samsung / Celulares')).toBeInTheDocument();
    expect(screen.getByText('Huerfana / Sin Titular')).toBeInTheDocument();
  });

  it('manages sub-PMs of a pair the admin is not titular of', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await user.click(await screen.findByText('Huerfana / Sin Titular'));
    await waitFor(() => expect(marcasPmAPI.listarSubPMs).toHaveBeenCalledWith('Huerfana', 'Sin Titular'));

    await user.selectOptions(screen.getByLabelText(/usuario a delegar/i), '6');
    await user.click(screen.getByRole('button', { name: /otorgar/i }));

    await waitFor(() =>
      expect(marcasPmAPI.crearSubPM).toHaveBeenCalledWith({
        marca: 'Huerfana',
        categoria: 'Sin Titular',
        usuario_id: 6,
      }),
    );
  });

  it('uses admin copy instead of the titular-oriented copy', async () => {
    render(<MisSubPMs />);
    expect(await screen.findByRole('heading', { name: 'Sub-PMs' })).toBeInTheDocument();
    expect(screen.queryByText('Mis Sub-PMs')).not.toBeInTheDocument();
    expect(screen.getByText(/incluso las que no tienen titular/i)).toBeInTheDocument();
  });

  it('shows the admin empty state when there are no pairs at all', async () => {
    marcasPmAPI.listarTodosLosPares.mockResolvedValue({ data: [] });
    render(<MisSubPMs />);
    expect(await screen.findByText(/no hay marcas\/categorías cargadas/i)).toBeInTheDocument();
  });

  it('surfaces the error and does NOT fall back when GET /marcas-pm fails with 500', async () => {
    marcasPmAPI.listarTodosLosPares.mockRejectedValue({
      response: { status: 500, data: { detail: 'Error interno del servidor' } },
    });
    render(<MisSubPMs />);
    expect(await screen.findByText('Error interno del servidor')).toBeInTheDocument();
    expect(marcasPmAPI.misTitularidades).not.toHaveBeenCalled();
    expect(screen.queryByText('Samsung / Celulares')).not.toBeInTheDocument();
  });

  it('surfaces the error and does NOT fall back on a network failure (no response)', async () => {
    marcasPmAPI.listarTodosLosPares.mockRejectedValue(new Error('Network Error'));
    render(<MisSubPMs />);
    expect(await screen.findByText('Error al cargar las marcas/categorías')).toBeInTheDocument();
    expect(marcasPmAPI.misTitularidades).not.toHaveBeenCalled();
  });

  it('falls back to the titular scope when GET /marcas-pm is rejected (403)', async () => {
    marcasPmAPI.listarTodosLosPares.mockRejectedValue({ response: { status: 403, data: { detail: 'No tienes permisos' } } });
    render(<MisSubPMs />);
    expect(await screen.findByText('Samsung / Celulares')).toBeInTheDocument();
    expect(marcasPmAPI.misTitularidades).toHaveBeenCalled();
    expect(screen.getByText('LG / Televisores')).toBeInTheDocument();
  });
});
