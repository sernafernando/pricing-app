import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import api, { marcasPmAPI } from '../services/api';
import PanelPermisos from './PanelPermisos';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  marcasPmAPI: { listarTodosLosPares: vi.fn(), obtenerConteosSubPMs: vi.fn() },
}));

const USUARIO = { id: 7, nombre: 'Ana Pérez', username: 'ana', email: 'ana@x.com', rol: 'PRICING', activo: true };
const OTRO = { id: 8, nombre: 'Beto Gómez', username: 'beto', email: 'beto@x.com', rol: 'ADMIN', activo: true };

// Ana lacks admin.ver_panel; Beto has it by role.
const permisosDe = (usuarioId = 7) => ({
  usuario_id: usuarioId,
  rol: usuarioId === 7 ? 'PRICING' : 'ADMIN',
  permisos_detallados: {
    administracion: [{
      codigo: 'admin.ver_panel', nombre: 'Ver panel', descripcion: '', es_critico: false,
      tiene_por_rol: usuarioId !== 7, override: null, efectivo: usuarioId !== 7,
      origen: usuarioId === 7 ? 'sin_permiso' : 'rol',
    }],
  },
});

function renderPanel() {
  render(
    <MemoryRouter>
      <PanelPermisos />
    </MemoryRouter>,
  );
}

const filaAdmin = () => screen.getByText('/admin', { selector: 'code' }).closest('li');
const concederAdmin = () => within(filaAdmin()).getByRole('button', { name: 'Conceder acceso a Admin' });

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url) => {
    if (url === '/usuarios') return Promise.resolve({ data: [USUARIO, OTRO] });
    if (url === '/permisos/catalogo') return Promise.resolve({ data: {} });
    if (url === '/roles') return Promise.resolve({ data: [] });
    if (url === '/auth/me') return Promise.resolve({ data: { id: 1, rol: 'ADMIN' } });
    if (url === '/permisos/usuario/7') return Promise.resolve({ data: permisosDe(7) });
    if (url === '/permisos/usuario/8') return Promise.resolve({ data: permisosDe(8) });
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
  api.post.mockResolvedValue({ data: {} });
  marcasPmAPI.listarTodosLosPares.mockResolvedValue({ data: [] });
  marcasPmAPI.obtenerConteosSubPMs.mockResolvedValue({ data: { conteos: [] } });
});

describe('PanelPermisos', () => {
  it('shows the selected user permissions by screen and keeps the search after an override', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <PanelPermisos />
      </MemoryRouter>,
    );

    await user.click(await screen.findByText('Ana Pérez'));
    const buscador = await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);
    await user.type(buscador, 'admin');

    const fila = screen.getByText('/admin', { selector: 'code' }).closest('li');
    await user.click(within(fila).getByRole('button', { name: 'Conceder acceso a Admin' }));

    expect(api.post).toHaveBeenCalledWith('/permisos/override', expect.objectContaining({
      usuario_id: 7, permiso_codigo: 'admin.ver_panel', concedido: true,
    }));
    await waitFor(() =>
      expect(api.get.mock.calls.filter(([url]) => url === '/permisos/usuario/7')).toHaveLength(2),
    );
    // Reloaded in place: the view was not torn down, so the search survives.
    expect(screen.getByPlaceholderText(/Buscá una pantalla o permiso/)).toHaveValue('admin');
    expect(await screen.findByText('Permiso concedido')).toBeInTheDocument();
  });

  it('does not let a late reload of the previous user overwrite the newly selected one', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByText('Ana Pérez'));
    await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);

    // The reload that follows the override stays pending until we release it.
    let liberarRecarga;
    const recargaPendiente = new Promise((resolve) => { liberarRecarga = resolve; });
    const getOriginal = api.get.getMockImplementation();
    let llamadasAna = 0;
    api.get.mockImplementation((url) => {
      if (url === '/permisos/usuario/7' && ++llamadasAna === 1) return recargaPendiente;
      return getOriginal(url);
    });

    await user.click(concederAdmin());
    await waitFor(() => expect(llamadasAna).toBe(1));

    await user.click(screen.getAllByText('Beto Gómez')[0]);
    await waitFor(() => expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument());

    await act(async () => liberarRecarga({ data: permisosDe(7) }));

    // Still Beto's permissions: Ana's late payload was dropped.
    expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Conceder acceso a Admin' })).not.toBeInTheDocument();
    // ...and Ana's success banner does not show up over Beto's permissions.
    await act(async () => {});
    expect(screen.queryByText('Permiso concedido')).not.toBeInTheDocument();
  });

  describe('late permission responses', () => {
    // Holds the FIRST GET of the given user's permissions until released;
    // later GETs answer at once with `siguiente()`.
    function retenerPrimeraCarga(usuarioId, siguiente = () => permisosDe(usuarioId)) {
      const getOriginal = api.get.getMockImplementation();
      let liberar;
      const pendiente = new Promise((resolve) => { liberar = resolve; });
      let llamadas = 0;
      api.get.mockImplementation((url) => {
        if (url !== `/permisos/usuario/${usuarioId}`) return getOriginal(url);
        llamadas += 1;
        return llamadas === 1 ? pendiente : Promise.resolve({ data: siguiente() });
      });
      return (data) => act(async () => liberar({ data }));
    }

    it('does not let the first selection overwrite a later one when it answers last', async () => {
      const user = userEvent.setup();
      const liberarAna = retenerPrimeraCarga(7);
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(screen.getByText('Beto Gómez'));
      await waitFor(() => expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument());

      await liberarAna(permisosDe(7));

      expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Conceder acceso a Admin' })).not.toBeInTheDocument();
    });

    it('does not let an older request for the same user overwrite a newer one', async () => {
      const user = userEvent.setup();
      // Ana's second load already shows the access granted by an override.
      const conOverride = () => {
        const data = permisosDe(7);
        Object.assign(data.permisos_detallados.administracion[0], {
          override: true, efectivo: true, origen: 'override_agregado',
        });
        return data;
      };
      const liberarAna = retenerPrimeraCarga(7, conOverride);
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(screen.getByText('Beto Gómez'));
      await user.click(screen.getByText('Ana Pérez'));
      await waitFor(() => expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument());

      // The stale first answer (no access) arrives last and must be dropped.
      await liberarAna(permisosDe(7));

      expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument();
    });
  });

  describe('feedback messages', () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('does not let an earlier success timer wipe a later error', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);

      await user.click(concederAdmin());
      expect(await screen.findByText('Permiso concedido')).toBeInTheDocument();

      // One second later a second override fails.
      await act(async () => vi.advanceTimersByTime(1000));
      api.post.mockRejectedValueOnce({ response: { data: { detail: 'No se pudo guardar' } } });
      await user.click(concederAdmin());
      expect(await screen.findByText('No se pudo guardar')).toBeInTheDocument();

      // Past the first success's 2 s timer: the error must still be there.
      await act(async () => vi.advanceTimersByTime(1500));
      expect(screen.getByText('No se pudo guardar')).toBeInTheDocument();
    });

    it('still clears a success message after 2 seconds', async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);
      await user.click(concederAdmin());
      expect(await screen.findByText('Permiso concedido')).toBeInTheDocument();

      await act(async () => vi.advanceTimersByTime(2100));
      expect(screen.queryByText('Permiso concedido')).not.toBeInTheDocument();
    });
  });
});
