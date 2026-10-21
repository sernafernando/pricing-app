import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import api, { marcasPmAPI } from '../services/api';
import PanelPermisos from './PanelPermisos';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
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

const ROLES = [
  { id: 1, codigo: 'SUPERADMIN', nombre: 'Superadmin' },
  { id: 2, codigo: 'ADMIN', nombre: 'Administrador' },
  { id: 3, codigo: 'PRICING', nombre: 'Pricing' },
  { id: 4, codigo: 'COMPRAS', nombre: 'Compras' },
  { id: 5, codigo: 'VENTAS', nombre: 'Ventas' },
];

// GET/PUT /usuarios/{id}/roles-adicionales response.
const rolesAdicionalesDe = (usuarioId, adicionales) => ({
  usuario_id: usuarioId,
  rol_principal: ROLES.find((r) => r.codigo === (usuarioId === 7 ? 'PRICING' : 'ADMIN')),
  roles_adicionales: adicionales,
});

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
    if (url === '/usuarios/7/roles-adicionales') {
      return Promise.resolve({ data: rolesAdicionalesDe(7, [ROLES[3]]) });
    }
    if (url === '/usuarios/8/roles-adicionales') return Promise.resolve({ data: rolesAdicionalesDe(8, []) });
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

  describe('view switch', () => {
    const vistas = () => screen.getByRole('group', { name: 'Ver permisos' });

    it('starts on Por pantalla and switches to the per-permission view', async () => {
      const user = userEvent.setup();
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));

      expect(await screen.findByText('/admin', { selector: 'code' })).toBeInTheDocument();
      expect(within(vistas()).getByRole('button', { name: 'Por pantalla' })).toHaveAttribute('aria-pressed', 'true');

      await user.click(within(vistas()).getByRole('button', { name: 'Por permiso' }));

      const grupo = screen.getByRole('region', { name: 'Administración del sistema' });
      expect(within(grupo).getByText('0 de 1 concedidos')).toBeInTheDocument();
      expect(screen.queryByText('/admin', { selector: 'code' })).not.toBeInTheDocument();
    });

    it('keeps the chosen view when another user is selected', async () => {
      const user = userEvent.setup();
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(await screen.findByRole('button', { name: 'Por permiso' }));

      await user.click(screen.getByText('Beto Gómez'));

      const grupo = await screen.findByRole('region', { name: 'Administración del sistema' });
      expect(await within(grupo).findByText('1 de 1 concedidos')).toBeInTheDocument();
      expect(within(vistas()).getByRole('button', { name: 'Por permiso' })).toHaveAttribute('aria-pressed', 'true');
    });

    it('grants from the per-permission view and reloads the user', async () => {
      const user = userEvent.setup();
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(await screen.findByRole('button', { name: 'Por permiso' }));

      await user.click(screen.getByRole('button', { name: 'Conceder admin.ver_panel' }));

      expect(api.post).toHaveBeenCalledWith('/permisos/override', expect.objectContaining({
        usuario_id: 7, permiso_codigo: 'admin.ver_panel', concedido: true,
      }));
      await waitFor(() =>
        expect(api.get.mock.calls.filter(([url]) => url === '/permisos/usuario/7')).toHaveLength(2),
      );
      expect(await screen.findByText('Permiso concedido')).toBeInTheDocument();
    });

    it('keeps actions locked after switching views while an override is in flight', async () => {
      const user = userEvent.setup();
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));
      await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);

      let liberarOverride;
      api.post.mockReturnValueOnce(new Promise((resolve) => { liberarOverride = resolve; }));
      await user.click(concederAdmin());
      await user.click(within(vistas()).getByRole('button', { name: 'Por permiso' }));

      // One action at a time, whichever view started it.
      expect(screen.getByRole('button', { name: 'Conceder admin.ver_panel' })).toBeDisabled();

      await act(async () => liberarOverride({ data: {} }));
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Conceder admin.ver_panel' })).toBeEnabled(),
      );
    });

    it('locks only the user whose override is in flight', async () => {
      const user = userEvent.setup();
      const acciones = () => screen.getAllByRole('button', { name: /^(Conceder|Quitar|Resetear) / });
      const concederVerPanel = () => screen.getByRole('button', { name: 'Conceder admin.ver_panel' });
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(await screen.findByRole('button', { name: 'Por permiso' }));

      let liberarOverride;
      api.post.mockReturnValueOnce(new Promise((resolve) => { liberarOverride = resolve; }));
      await user.click(concederVerPanel());

      // Another user is not blocked by Ana's pending change.
      await user.click(screen.getAllByText('Beto Gómez')[0]);
      await waitFor(() => expect(screen.getByRole('region', { name: 'Usuario seleccionado' })).toHaveTextContent('Beto Gómez'));
      await waitFor(() => expect(acciones().length).toBeGreaterThan(0));
      for (const boton of acciones()) expect(boton).toBeEnabled();

      // Back on Ana, her change is still pending.
      await user.click(screen.getAllByText('Ana Pérez')[0]);
      await waitFor(() => expect(concederVerPanel()).toBeDisabled());

      await act(async () => liberarOverride({ data: {} }));
      await waitFor(() => {
        for (const boton of acciones()) expect(boton).toBeEnabled();
      });
    });
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

  // Phone layout: the list and the detail are two panes and CSS shows only the
  // one named by `data-vista-movil` (desktop ignores it and shows both).
  describe('phone list/detail switch', () => {
    const layout = () => document.querySelector('[data-vista-movil]');
    const volver = () => screen.queryByRole('button', { name: 'Volver a la lista de usuarios' });
    const filaUsuario = (nombre) =>
      within(screen.getByRole('list', { name: 'Usuarios del sistema' })).getByRole('button', {
        name: new RegExp(nombre),
      });

    it('shows the list and no back button while no user is selected', async () => {
      renderPanel();
      await screen.findByText('Ana Pérez');

      expect(layout()).toHaveAttribute('data-vista-movil', 'lista');
      expect(volver()).not.toBeInTheDocument();
    });

    it('shows the detail with a back button once a user is selected', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));

      expect(layout()).toHaveAttribute('data-vista-movil', 'detalle');
      expect(volver()).toBeInTheDocument();
    });

    it('goes back to the list keeping the user selected, and shows the detail again on the next pick', async () => {
      const user = userEvent.setup();
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));

      await user.click(volver());

      expect(layout()).toHaveAttribute('data-vista-movil', 'lista');
      expect(filaUsuario('Ana Pérez')).toHaveAttribute('aria-pressed', 'true');

      await user.click(filaUsuario('Beto Gómez'));

      expect(layout()).toHaveAttribute('data-vista-movil', 'detalle');
      expect(await screen.findByRole('heading', { name: 'Beto Gómez' })).toBeInTheDocument();
    });

    // Selecting never refuses (no guard in seleccionarUsuario, list rows never
    // disabled): the only "no new selection" case is tapping the same user.
    it('tapping the already selected user after going back shows its detail again', async () => {
      const user = userEvent.setup();
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(volver());

      await user.click(filaUsuario('Ana Pérez'));

      expect(layout()).toHaveAttribute('data-vista-movil', 'detalle');
      expect(volver()).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Ana Pérez' })).toBeInTheDocument();
    });

    it('does not jump to the detail when a save reselects the user after going back', async () => {
      const user = userEvent.setup();
      api.patch.mockResolvedValue({ data: {} });
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(screen.getByRole('button', { name: 'Editar' }));
      await user.click(await screen.findByRole('button', { name: /Guardar/ }));
      await waitFor(() => expect(api.patch).toHaveBeenCalled());

      // Back to the list before the delayed reselect after the save lands.
      await user.click(volver());
      await waitFor(
        () => expect(api.get.mock.calls.filter(([url]) => url === '/permisos/usuario/7').length).toBeGreaterThanOrEqual(2),
        { timeout: 2000 },
      );

      expect(layout()).toHaveAttribute('data-vista-movil', 'lista');
    });

    // No path clears the selection (deactivating keeps the user selected), so
    // the layout only goes back to the list through the back button.
    it('keeps the detail and its back button when the selected user is deactivated', async () => {
      const user = userEvent.setup();
      api.patch.mockResolvedValue({ data: {} });
      renderPanel();
      await user.click(await screen.findByText('Ana Pérez'));

      await user.click(screen.getByRole('button', { name: 'Desactivar' }));

      expect(await screen.findByRole('button', { name: 'Activar' })).toBeInTheDocument();
      expect(layout()).toHaveAttribute('data-vista-movil', 'detalle');
      expect(volver()).toBeInTheDocument();
    });

    describe('scrolling the detail into view', () => {
      // jsdom computes no layout: the phone layout (list hidden by CSS) and the
      // scroll position are stubbed; the exact originals are put back afterwards.
      let originalScrollIntoView;
      let scrollIntoView;
      // Plain DOM checks: role queries call getComputedStyle themselves.
      const columnaLista = (el) =>
        el.matches?.('[data-vista-movil] > *') && el.querySelector('h3')?.textContent === 'Usuarios del sistema';
      const columnaDetalle = () => layout().lastElementChild;

      beforeEach(() => {
        originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
        scrollIntoView = vi.fn();
        Element.prototype.scrollIntoView = scrollIntoView;
        vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
          top: -300, bottom: 200, left: 0, right: 390, width: 390, height: 500, x: 0, y: -300,
        });
      });

      afterEach(() => {
        vi.restoreAllMocks();
        if (originalScrollIntoView) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScrollIntoView);
        else delete Element.prototype.scrollIntoView;
      });

      it('scrolls the detail into view once on a phone when its top is above the viewport', async () => {
        const original = window.getComputedStyle.bind(window);
        vi.spyOn(window, 'getComputedStyle').mockImplementation((el, ...rest) =>
          columnaLista(el) ? { display: 'none' } : original(el, ...rest),
        );
        const user = userEvent.setup();
        renderPanel();

        await user.click(await screen.findByText('Ana Pérez'));
        await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);

        expect(scrollIntoView).toHaveBeenCalledTimes(1);
        expect(scrollIntoView.mock.contexts[0]).toBe(columnaDetalle());
      });

      it('does not scroll on desktop, where the list stays visible', async () => {
        const user = userEvent.setup();
        renderPanel();

        await user.click(await screen.findByText('Ana Pérez'));
        await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);

        expect(scrollIntoView).not.toHaveBeenCalled();
      });
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

    it('cannot be closed while saving, so a late response never lands in a reopened modal', async () => {
      const user = userEvent.setup();
      let rechazarAlta;
      api.post.mockReturnValueOnce(new Promise((_, reject) => { rechazarAlta = reject; }));
      renderPanel();

      await user.click(await screen.findByRole('button', { name: '+ Nuevo Usuario' }));
      const form = formulario('Nuevo usuario');
      await user.type(within(form).getByLabelText('Usuario'), 'ana');
      await user.type(within(form).getByLabelText('Nombre completo'), 'Ana');
      await user.type(within(form).getByLabelText('Contraseña'), 'x');
      await user.click(within(form).getByRole('button', { name: 'Crear Usuario' }));

      expect(within(formulario('Nuevo usuario')).getByRole('button', { name: 'Cancelar' })).toBeDisabled();
      await user.keyboard('{Escape}');
      expect(formulario('Nuevo usuario')).toBeInTheDocument();

      rechazarAlta({ response: { data: { detail: 'El usuario ya existe' } } });
      expect(await within(formulario('Nuevo usuario')).findByText('El usuario ya existe')).toBeInTheDocument();
      expect(within(formulario('Nuevo usuario')).getByRole('button', { name: 'Cancelar' })).toBeEnabled();
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

    it('keeps the edit modal open and shows a backend error inside it', async () => {
      const user = userEvent.setup();
      api.patch.mockRejectedValueOnce({ response: { data: { detail: 'El email ya está en uso' } } });
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await user.click(within(encabezadoUsuario()).getByRole('button', { name: 'Editar' }));
      await user.click(within(formulario('Editar usuario')).getByRole('button', { name: 'Guardar' }));

      expect(await within(formulario('Editar usuario')).findByText('El email ya está en uso')).toBeInTheDocument();
    });

    it('does not let the previous create success timer wipe an error in a reopened modal', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
        renderPanel();
        const nuevo = await screen.findByRole('button', { name: '+ Nuevo Usuario' });

        await user.click(nuevo);
        const form = formulario('Nuevo usuario');
        await user.type(within(form).getByLabelText('Usuario'), 'carla');
        await user.type(within(form).getByLabelText('Nombre completo'), 'Carla');
        await user.type(within(form).getByLabelText('Contraseña'), 'x');
        await user.click(within(form).getByRole('button', { name: 'Crear Usuario' }));
        expect(await screen.findByText('Usuario creado correctamente')).toBeInTheDocument();

        // One second later the admin opens a new dialog and hits a validation error.
        await act(async () => vi.advanceTimersByTime(1000));
        await user.click(nuevo);
        await user.click(within(formulario('Nuevo usuario')).getByRole('button', { name: 'Crear Usuario' }));
        const error = 'Username, nombre y contraseña son requeridos';
        expect(within(formulario('Nuevo usuario')).getByText(error)).toBeInTheDocument();

        // Past the first success's 3 s timer: the error must still be there.
        await act(async () => vi.advanceTimersByTime(2500));
        expect(within(formulario('Nuevo usuario')).getByText(error)).toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
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

  describe('roles adicionales', () => {
    const seccion = () => screen.getByRole('region', { name: 'Roles adicionales' });
    const conRoles = () => {
      const getOriginal = api.get.getMockImplementation();
      api.get.mockImplementation((url) => (url === '/roles' ? Promise.resolve({ data: ROLES }) : getOriginal(url)));
    };

    it('shows the selected user additional roles', async () => {
      const user = userEvent.setup();
      conRoles();
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      expect(await within(seccion()).findByText('Compras')).toBeInTheDocument();

      await user.click(screen.getAllByText('Beto Gómez')[0]);
      expect(await within(seccion()).findByText('Ninguno')).toBeInTheDocument();
      expect(within(seccion()).queryByText('Compras')).not.toBeInTheDocument();
    });

    it('edits them leaving out SUPERADMIN and the primary role, saves the set and reloads permissions', async () => {
      const user = userEvent.setup();
      conRoles();
      api.put.mockResolvedValue({ data: rolesAdicionalesDe(7, [ROLES[3], ROLES[4]]) });
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await within(seccion()).findByText('Compras');
      await user.click(within(seccion()).getByRole('button', { name: 'Editar roles adicionales' }));

      const opciones = within(seccion()).getAllByRole('checkbox');
      expect(opciones.map((opcion) => opcion.closest('label').textContent)).toEqual([
        expect.stringMatching(/Administrador/),
        expect.stringMatching(/Compras/),
        expect.stringMatching(/Ventas/),
      ]);
      expect(within(seccion()).getByRole('checkbox', { name: /Compras/ })).toBeChecked();
      expect(within(seccion()).getByRole('checkbox', { name: /Ventas/ })).not.toBeChecked();

      await user.click(within(seccion()).getByRole('checkbox', { name: /Ventas/ }));
      await user.click(within(seccion()).getByRole('button', { name: 'Guardar' }));

      expect(api.put).toHaveBeenCalledWith('/usuarios/7/roles-adicionales', { rol_ids: [4, 5] });
      expect(await screen.findByText('Roles adicionales actualizados')).toBeInTheDocument();
      await waitFor(() =>
        expect(api.get.mock.calls.filter(([url]) => url === '/permisos/usuario/7')).toHaveLength(2),
      );
      expect(within(seccion()).queryByRole('checkbox')).not.toBeInTheDocument();
      expect(within(seccion()).getByText('Ventas')).toBeInTheDocument();
    });

    it('disables the editor while saving', async () => {
      const user = userEvent.setup();
      conRoles();
      let resolver;
      api.put.mockReturnValue(new Promise((resolve) => { resolver = resolve; }));
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await within(seccion()).findByText('Compras');
      await user.click(within(seccion()).getByRole('button', { name: 'Editar roles adicionales' }));
      await user.click(within(seccion()).getByRole('button', { name: 'Guardar' }));

      expect(within(seccion()).getByRole('button', { name: 'Guardando...' })).toBeDisabled();
      expect(within(seccion()).getByRole('button', { name: 'Cancelar' })).toBeDisabled();
      within(seccion()).getAllByRole('checkbox').forEach((opcion) => expect(opcion).toBeDisabled());

      await act(async () => resolver({ data: rolesAdicionalesDe(7, [ROLES[3]]) }));
      expect(within(seccion()).queryByRole('checkbox')).not.toBeInTheDocument();
    });

    it('shows the backend error (400/409) and keeps the selection to retry', async () => {
      const user = userEvent.setup();
      conRoles();
      api.put.mockRejectedValueOnce({
        response: { status: 409, data: { detail: 'Otro administrador cambió los roles al mismo tiempo' } },
      });
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await within(seccion()).findByText('Compras');
      await user.click(within(seccion()).getByRole('button', { name: 'Editar roles adicionales' }));
      await user.click(within(seccion()).getByRole('checkbox', { name: /Ventas/ }));
      await user.click(within(seccion()).getByRole('button', { name: 'Guardar' }));

      expect(await within(seccion()).findByRole('alert')).toHaveTextContent(
        'Otro administrador cambió los roles al mismo tiempo',
      );
      expect(within(seccion()).getByRole('checkbox', { name: /Ventas/ })).toBeChecked();
      expect(within(seccion()).getByRole('button', { name: 'Guardar' })).toBeEnabled();
      // Permissions were not reloaded: nothing changed.
      expect(api.get.mock.calls.filter(([url]) => url === '/permisos/usuario/7')).toHaveLength(1);
    });

    it('drops a save that finishes after switching to another user', async () => {
      const user = userEvent.setup();
      conRoles();
      let resolver;
      api.put.mockReturnValue(new Promise((resolve) => { resolver = resolve; }));
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await within(seccion()).findByText('Compras');
      await user.click(within(seccion()).getByRole('button', { name: 'Editar roles adicionales' }));
      await user.click(within(seccion()).getByRole('button', { name: 'Guardar' }));

      await user.click(screen.getAllByText('Beto Gómez')[0]);
      expect(await within(seccion()).findByText('Ninguno')).toBeInTheDocument();
      await waitFor(() => expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument());

      await act(async () => resolver({ data: rolesAdicionalesDe(7, [ROLES[3], ROLES[4]]) }));

      expect(screen.queryByText('Roles adicionales actualizados')).not.toBeInTheDocument();
      expect(api.get.mock.calls.filter(([url]) => url === '/permisos/usuario/7')).toHaveLength(1);
      expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument();
      expect(within(seccion()).getByText('Ninguno')).toBeInTheDocument();
    });

    // Save succeeds; the permissions reload after it stays pending until released.
    const guardarConRecargaPendiente = async (user) => {
      conRoles();
      api.put.mockResolvedValue({ data: rolesAdicionalesDe(7, [ROLES[3]]) });
      let rechazarRecarga;
      const getOriginal = api.get.getMockImplementation();
      let llamadasAna = 0;
      api.get.mockImplementation((url) => {
        if (url === '/permisos/usuario/7' && ++llamadasAna === 2) {
          return new Promise((_, reject) => { rechazarRecarga = reject; });
        }
        return getOriginal(url);
      });
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await within(seccion()).findByText('Compras');
      await user.click(within(seccion()).getByRole('button', { name: 'Editar roles adicionales' }));
      await user.click(within(seccion()).getByRole('button', { name: 'Guardar' }));
      await waitFor(() => expect(llamadasAna).toBe(2));
      return () => rechazarRecarga(new Error('red caída'));
    };

    it('does not show a failed reload of the previous user over the newly selected one', async () => {
      const user = userEvent.setup();
      const fallarRecarga = await guardarConRecargaPendiente(user);

      await user.click(screen.getAllByText('Beto Gómez')[0]);
      await waitFor(() => expect(within(filaAdmin()).getByText('Accede')).toBeInTheDocument());
      await act(async () => fallarRecarga());

      expect(screen.queryByText('Error al recargar permisos del usuario')).not.toBeInTheDocument();
    });

    it('shows a failed reload while the same user is still selected', async () => {
      const user = userEvent.setup();
      const fallarRecarga = await guardarConRecargaPendiente(user);

      await act(async () => fallarRecarga());

      expect(await screen.findByText('Error al recargar permisos del usuario')).toBeInTheDocument();
    });

    it('is hidden for a SUPERADMIN user (already has every permission)', async () => {
      const user = userEvent.setup();
      const ROOT = { id: 9, nombre: 'Root Admin', username: 'root', email: 'root@x.com', rol: 'SUPERADMIN', activo: true };
      const getOriginal = api.get.getMockImplementation();
      api.get.mockImplementation((url) => {
        if (url === '/auth/me') return Promise.resolve({ data: { id: 1, rol: 'SUPERADMIN' } });
        if (url === '/usuarios') return Promise.resolve({ data: [USUARIO, ROOT] });
        if (url === '/permisos/usuario/9') return Promise.resolve({ data: { ...permisosDe(8), usuario_id: 9, rol: 'SUPERADMIN' } });
        if (url === '/usuarios/9/roles-adicionales') return Promise.resolve({ data: rolesAdicionalesDe(9, []) });
        return getOriginal(url);
      });
      renderPanel();

      await user.click(await screen.findByText('Root Admin'));
      await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);
      expect(screen.queryByRole('region', { name: 'Roles adicionales' })).not.toBeInTheDocument();
      expect(api.get).not.toHaveBeenCalledWith('/usuarios/9/roles-adicionales');

      // The same SUPERADMIN viewer does get it for a non-SUPERADMIN user.
      await user.click(screen.getAllByText('Ana Pérez')[0]);
      expect(await screen.findByRole('region', { name: 'Roles adicionales' })).toBeInTheDocument();
    });

    it('is not offered to a viewer whose primary role is not ADMIN or SUPERADMIN', async () => {
      const user = userEvent.setup();
      const getOriginal = api.get.getMockImplementation();
      api.get.mockImplementation((url) =>
        url === '/auth/me' ? Promise.resolve({ data: { id: 1, rol: 'GERENTE' } }) : getOriginal(url),
      );
      renderPanel();

      await user.click(await screen.findByText('Ana Pérez'));
      await screen.findByPlaceholderText(/Buscá una pantalla o permiso/);
      expect(screen.queryByRole('region', { name: 'Roles adicionales' })).not.toBeInTheDocument();
      expect(api.get).not.toHaveBeenCalledWith('/usuarios/7/roles-adicionales');
    });
  });
});
