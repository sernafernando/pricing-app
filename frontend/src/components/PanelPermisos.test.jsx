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

const encabezadoUsuario = () => screen.getByRole('region', { name: 'Usuario seleccionado' });
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

  it('does not reload the previous user over the new one when the override finishes after the switch', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByText('Ana Pérez'));
    await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);

    // The override POST stays pending, so its reload starts only after the switch.
    let liberarOverride;
    api.post.mockReturnValueOnce(new Promise((resolve) => { liberarOverride = resolve; }));
    await user.click(concederAdmin());

    await user.click(screen.getAllByText('Beto Gómez')[0]);
    await waitFor(() => expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument());

    await act(async () => liberarOverride({ data: {} }));
    await act(async () => {});

    // Still Beto's permissions: Ana's reload must not be applied.
    expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Conceder acceso a Admin' })).not.toBeInTheDocument();
  });

  describe('user list', () => {
    const lista = () => screen.getByRole('list', { name: 'Usuarios del sistema' });
    const filaUsuario = (nombre) => within(lista()).getByRole('button', { name: new RegExp(nombre) });

    it('shows each user with a role chip and the overrides chip only for the selected one', async () => {
      const user = userEvent.setup();
      api.get.mockImplementation(((original) => (url) => {
        if (url !== '/permisos/usuario/7') return original(url);
        const data = permisosDe(7);
        Object.assign(data.permisos_detallados.administracion[0], {
          override: true, efectivo: true, origen: 'override_agregado',
        });
        return Promise.resolve({ data });
      })(api.get.getMockImplementation()));
      renderPanel();

      await screen.findByText('Ana Pérez');
      expect(within(filaUsuario('Ana Pérez')).getByText('PRICING')).toBeInTheDocument();
      expect(within(filaUsuario('Beto Gómez')).getByText('ADMIN')).toBeInTheDocument();
      expect(within(lista()).queryByText(/^\+\d/)).not.toBeInTheDocument();

      await user.click(filaUsuario('Ana Pérez'));

      expect(filaUsuario('Ana Pérez')).toHaveAttribute('aria-pressed', 'true');
      expect(await within(filaUsuario('Ana Pérez')).findByText('+1 −0')).toBeInTheDocument();
      expect(within(filaUsuario('Beto Gómez')).queryByText(/^\+\d/)).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Ana Pérez' })).toBeInTheDocument();
    });

    it('searches users ignoring case and accents', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.type(await screen.findByPlaceholderText('Buscar usuario...'), 'PEREZ');

      expect(within(lista()).getByText('Ana Pérez')).toBeInTheDocument();
      expect(within(lista()).queryByText('Beto Gómez')).not.toBeInTheDocument();
    });

    it.each([
      ['username', 'bgz'],
      ['email', 'contacto@empresa'],
    ])('searches users by %s', async (_campo, texto) => {
      const user = userEvent.setup();
      // Username and email share nothing with the name, so only they can match.
      const beto = { ...OTRO, username: 'bgz', email: 'contacto@empresa.com' };
      api.get.mockImplementation(((original) => (url) => (
        url === '/usuarios' ? Promise.resolve({ data: [USUARIO, beto] }) : original(url)
      ))(api.get.getMockImplementation()));
      renderPanel();

      await user.type(await screen.findByPlaceholderText('Buscar usuario...'), texto);

      expect(within(lista()).getByText('Beto Gómez')).toBeInTheDocument();
      expect(within(lista()).queryByText('Ana Pérez')).not.toBeInTheDocument();
    });

    it('searches users that have no email or username', async () => {
      const user = userEvent.setup();
      const sinDatos = { ...OTRO, username: null, email: undefined };
      api.get.mockImplementation(((original) => (url) => (
        url === '/usuarios' ? Promise.resolve({ data: [USUARIO, sinDatos] }) : original(url)
      ))(api.get.getMockImplementation()));
      renderPanel();

      // Matches by role, so the missing username/email are read before it.
      await user.type(await screen.findByPlaceholderText('Buscar usuario...'), 'admin');

      expect(within(lista()).getByText('Beto Gómez')).toBeInTheDocument();
      expect(within(lista()).queryByText('Ana Pérez')).not.toBeInTheDocument();
      // No "@null" / "@undefined" placeholder for the missing contact data.
      expect(filaUsuario('Beto Gómez')).not.toHaveTextContent(/null|undefined/);

      // Neither a lone "@" in the selected user's header.
      await user.click(filaUsuario('Beto Gómez'));
      const encabezado = encabezadoUsuario();
      expect(encabezado).not.toHaveTextContent('@');
    });

    it('says so when no user matches the search', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.type(await screen.findByPlaceholderText('Buscar usuario...'), 'zzz');

      expect(within(lista()).getByText('Ningún usuario coincide.')).toBeInTheDocument();
      expect(within(lista()).queryByRole('button')).not.toBeInTheDocument();
    });

    it('says there are no users, not a search mismatch, when the list is empty', async () => {
      api.get.mockImplementation(((original) => (url) => (
        url === '/usuarios' ? Promise.resolve({ data: [] }) : original(url)
      ))(api.get.getMockImplementation()));
      renderPanel();

      await screen.findByRole('list', { name: 'Usuarios del sistema' });
      expect(within(lista()).getByText('No hay usuarios.')).toBeInTheDocument();
      expect(within(lista()).queryByText('Ningún usuario coincide.')).not.toBeInTheDocument();
    });

    it('shows a +0 −0 overrides chip for a selected user without overrides', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(await screen.findByText('Beto Gómez'));

      expect(await within(filaUsuario('Beto Gómez')).findByText('+0 −0')).toBeInTheDocument();
    });

    it('marks a user without an active flag as inactive, like the header does', async () => {
      const user = userEvent.setup();
      const sinEstado = { ...OTRO, activo: undefined };
      api.get.mockImplementation(((original) => (url) => (
        url === '/usuarios' ? Promise.resolve({ data: [USUARIO, sinEstado] }) : original(url)
      ))(api.get.getMockImplementation()));
      renderPanel();

      await screen.findByText('Beto Gómez');
      expect(within(filaUsuario('Beto Gómez')).getByText('Inactivo')).toBeInTheDocument();
      expect(within(filaUsuario('Ana Pérez')).queryByText('Inactivo')).not.toBeInTheDocument();

      await user.click(filaUsuario('Beto Gómez'));
      const encabezado = encabezadoUsuario();
      expect(within(encabezado).getByText('Inactivo')).toBeInTheDocument();
    });
  });

  describe('user modal', () => {
    const ROLES = [
      { id: 1, codigo: 'VENTAS', nombre: 'Ventas' },
      { id: 2, codigo: 'PRICING', nombre: 'Pricing' },
      { id: 3, codigo: 'SUPERADMIN', nombre: 'Superadmin' },
    ];
    const formulario = (nombre) => screen.getByRole('form', { name: nombre });

    beforeEach(() => {
      api.get.mockImplementation(((original) => (url) => (
        url === '/roles' ? Promise.resolve({ data: ROLES }) : original(url)
      ))(api.get.getMockImplementation()));
      api.patch.mockResolvedValue({ data: {} });
    });

    it('creates a user from a modal with the same payload as before', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(await screen.findByRole('button', { name: '+ Nuevo Usuario' }));
      const form = formulario('Nuevo usuario');
      await waitFor(() => expect(within(form).getByLabelText('Usuario')).toHaveFocus());
      // A non-SUPERADMIN admin cannot hand out SUPERADMIN.
      expect(within(form).queryByRole('option', { name: 'Superadmin' })).not.toBeInTheDocument();
      expect(within(form).getByLabelText('Rol')).toHaveValue('1');

      await user.type(within(form).getByLabelText('Usuario'), 'carla');
      await user.type(within(form).getByLabelText('Nombre completo'), 'Carla Ruiz');
      await user.type(within(form).getByLabelText('Contraseña'), 'secreta');
      await user.selectOptions(within(form).getByLabelText('Rol'), 'Pricing');
      await user.click(within(form).getByRole('button', { name: 'Crear Usuario' }));

      expect(api.post).toHaveBeenCalledWith('/usuarios', {
        username: 'carla', email: null, nombre: 'Carla Ruiz', password: 'secreta', rol: 'PRICING', rol_id: 2,
      });
      await waitFor(() => expect(screen.queryByRole('form', { name: 'Nuevo usuario' })).not.toBeInTheDocument());
      expect(await screen.findByText('Usuario creado correctamente')).toBeInTheDocument();
    });

    it('keeps the modal open and shows the error inside it when required fields are missing', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(await screen.findByRole('button', { name: '+ Nuevo Usuario' }));
      await user.click(within(formulario('Nuevo usuario')).getByRole('button', { name: 'Crear Usuario' }));

      expect(api.post).not.toHaveBeenCalledWith('/usuarios', expect.anything());
      expect(within(formulario('Nuevo usuario')).getByText('Username, nombre y contraseña son requeridos'))
        .toBeInTheDocument();
    });

    it('shows a backend error inside the modal', async () => {
      const user = userEvent.setup();
      api.post.mockRejectedValueOnce({ response: { data: { detail: 'El usuario ya existe' } } });
      renderPanel();

      await user.click(await screen.findByRole('button', { name: '+ Nuevo Usuario' }));
      const form = formulario('Nuevo usuario');
      await user.type(within(form).getByLabelText('Usuario'), 'ana');
      await user.type(within(form).getByLabelText('Nombre completo'), 'Ana');
      await user.type(within(form).getByLabelText('Contraseña'), 'x');
      await user.click(within(form).getByRole('button', { name: 'Crear Usuario' }));

      expect(await within(formulario('Nuevo usuario')).findByText('El usuario ya existe')).toBeInTheDocument();
    });

    it('closes with Escape and with Cancelar, but not by clicking outside', async () => {
      const user = userEvent.setup();
      renderPanel();
      const nuevo = await screen.findByRole('button', { name: '+ Nuevo Usuario' });

      await user.click(nuevo);
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('form', { name: 'Nuevo usuario' })).not.toBeInTheDocument();

      await user.click(nuevo);
      await user.click(formulario('Nuevo usuario').closest('.modal-overlay-tesla'));
      expect(formulario('Nuevo usuario')).toBeInTheDocument();

      await user.click(within(formulario('Nuevo usuario')).getByRole('button', { name: 'Cancelar' }));
      expect(screen.queryByRole('form', { name: 'Nuevo usuario' })).not.toBeInTheDocument();
    });

    it('edits the selected user from a modal prefilled with their data', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(within(encabezadoUsuario()).getByRole('button', { name: 'Editar' }));
      const form = formulario('Editar usuario');
      expect(within(form).getByLabelText('Usuario')).toHaveValue('ana');
      expect(within(form).getByLabelText('Email')).toHaveValue('ana@x.com');
      expect(within(form).getByLabelText('Rol')).toHaveValue('2');
      expect(within(form).queryByLabelText('Contraseña')).not.toBeInTheDocument();

      const nombre = within(form).getByLabelText('Nombre completo');
      await user.clear(nombre);
      await user.type(nombre, 'Ana María Pérez');
      await user.click(within(form).getByRole('button', { name: 'Guardar' }));

      expect(api.patch).toHaveBeenCalledWith('/usuarios/7', {
        username: 'ana', email: 'ana@x.com', nombre: 'Ana María Pérez', rol: 'PRICING', rol_id: 2,
      });
      await waitFor(() => expect(screen.queryByRole('form', { name: 'Editar usuario' })).not.toBeInTheDocument());
    });
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
