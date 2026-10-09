import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import api, { marcasPmAPI } from '../services/api';
import PanelPermisos from './PanelPermisos';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  marcasPmAPI: { listarTodosLosPares: vi.fn(), obtenerConteosSubPMs: vi.fn() },
}));

const USUARIO = { id: 7, nombre: 'Ana Pérez', username: 'ana', email: 'ana@x.com', rol: 'PRICING', activo: true };

const permisosDe = () => ({
  usuario_id: 7,
  rol: 'PRICING',
  permisos_detallados: {
    administracion: [{
      codigo: 'admin.ver_panel', nombre: 'Ver panel', descripcion: '', es_critico: false,
      tiene_por_rol: false, override: null, efectivo: false, origen: 'sin_permiso',
    }],
  },
});

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url) => {
    if (url === '/usuarios') return Promise.resolve({ data: [USUARIO] });
    if (url === '/permisos/catalogo') return Promise.resolve({ data: {} });
    if (url === '/roles') return Promise.resolve({ data: [] });
    if (url === '/auth/me') return Promise.resolve({ data: { id: 1, rol: 'ADMIN' } });
    if (url === '/permisos/usuario/7') return Promise.resolve({ data: permisosDe() });
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
});
