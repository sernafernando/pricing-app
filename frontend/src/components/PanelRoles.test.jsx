import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../services/api';
import PanelRoles from './PanelRoles';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

// Shapes mirror backend/app/api/endpoints/roles.py (RolResponse, GET /roles/{id}/permisos)
// and PermisosService.obtener_catalogo_permisos (GET /permisos/catalogo).
const ROLES = [
  { id: 1, codigo: 'SUPERADMIN', nombre: 'Super Admin', descripcion: null, es_sistema: true, orden: 0, activo: true, usuarios_count: 1 },
  { id: 2, codigo: 'ADMIN', nombre: 'Administrador', descripcion: null, es_sistema: true, orden: 1, activo: true, usuarios_count: 2 },
  { id: 3, codigo: 'VENTAS', nombre: 'Ventas', descripcion: null, es_sistema: false, orden: 2, activo: true, usuarios_count: 5 },
];

const permiso = (codigo, nombre, extra = {}) => ({ codigo, nombre, descripcion: null, es_critico: false, ...extra });

const CATALOGO = {
  productos: [
    permiso('productos.ver', 'Ver productos'),
    permiso('productos.editar_precios', 'Editar precios', { es_critico: true }),
  ],
  administracion: [permiso('admin.ver_panel', 'Ver panel de administración')],
};

const permisosDeRol = (rolId, codigos) => ({
  rol_id: rolId,
  rol_codigo: ROLES.find((r) => r.id === rolId).codigo,
  permisos: codigos.map((c) => ({ ...permiso(c, c), categoria: c.split('.')[0] })),
});

const errorConDetalle = (detail) => Object.assign(new Error('Request failed'), { response: { data: { detail } } });

const diferido = () => {
  let resolver;
  const promesa = new Promise((resolve) => {
    resolver = resolve;
  });
  return { promesa, resolver };
};

const cargasDeRoles = () => api.get.mock.calls.filter(([url]) => url === '/roles').length;

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  api.get.mockImplementation((url) => {
    if (url === '/roles') return Promise.resolve({ data: ROLES });
    if (url === '/permisos/catalogo') return Promise.resolve({ data: CATALOGO });
    if (url === '/roles/2/permisos') return Promise.resolve({ data: permisosDeRol(2, ['productos.ver', 'admin.ver_panel']) });
    if (url === '/roles/3/permisos') return Promise.resolve({ data: permisosDeRol(3, ['productos.ver']) });
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
  api.put.mockResolvedValue({ data: { success: true } });
  api.post.mockResolvedValue({ data: {} });
  api.patch.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// 'Ventas' is both a role card and a matrix column, so wait for the loaded panel instead.
async function renderPanel() {
  render(<PanelRoles />);
  await screen.findByRole('button', { name: '+ Nuevo Rol' });
}

// A role card is a button named by its content: '<nombre> [SISTEMA] <codigo> · N usuarios'.
const tarjeta = (nombre) => screen.getByRole('button', { name: new RegExp(`^${nombre} `) });
const drawer = (nombre) => screen.getByRole('dialog', { name: nombre });
const queryDrawer = () => screen.queryByRole('dialog');

/** Opens the role drawer from its card: role management lives there, not on the cards. */
async function abrirRol(user, nombre) {
  await user.click(tarjeta(nombre));
  return drawer(nombre);
}

describe('PanelRoles create role', () => {
  it('posts the new role with the uppercased code and the next order, then reloads', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    expect(screen.getByRole('heading', { name: 'Nuevo Rol' })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)'), 'compras');
    await user.type(screen.getByPlaceholderText('Nombre'), 'Compras');
    await user.type(screen.getByPlaceholderText('Descripcion (opcional)'), 'Equipo de compras');
    await user.click(screen.getByRole('button', { name: 'Crear' }));

    expect(api.post).toHaveBeenCalledWith('/roles', {
      codigo: 'COMPRAS', nombre: 'Compras', descripcion: 'Equipo de compras', orden: 3,
    });
    expect(await screen.findByText('Rol creado correctamente')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Nuevo Rol' })).not.toBeInTheDocument();
    expect(queryDrawer()).not.toBeInTheDocument();
    await waitFor(() => expect(cargasDeRoles()).toBe(2));
  });

  it('disables the button and shows Guardando... while the create is in flight', async () => {
    const { promesa, resolver } = diferido();
    api.post.mockReturnValueOnce(promesa);
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.type(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)'), 'COMPRAS');
    await user.type(screen.getByPlaceholderText('Nombre'), 'Compras');
    await user.click(screen.getByRole('button', { name: 'Crear' }));

    expect(screen.getByRole('button', { name: 'Guardando...' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Crear' })).not.toBeInTheDocument();
    // Cancelar would unmount the drawer while the POST is pending.
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeDisabled();

    await act(async () => resolver({ data: {} }));

    expect(await screen.findByText('Rol creado correctamente')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    expect(screen.getByRole('button', { name: 'Crear' })).toBeEnabled();
  });

  it('requires code and name before posting', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.click(screen.getByRole('button', { name: 'Crear' }));

    expect(screen.getByText('Codigo y nombre son requeridos')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('shows the backend error and keeps the form open', async () => {
    api.post.mockRejectedValueOnce(errorConDetalle('El codigo ya existe'));
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.type(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)'), 'VENTAS');
    await user.type(screen.getByPlaceholderText('Nombre'), 'Ventas bis');
    await user.click(screen.getByRole('button', { name: 'Crear' }));

    expect(await screen.findByText('El codigo ya existe')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Nuevo Rol' })).toBeInTheDocument();
    expect(cargasDeRoles()).toBe(1);
  });

  it('closes the form on Cancelar without posting', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(screen.queryByRole('heading', { name: 'Nuevo Rol' })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe('PanelRoles edit role', () => {
  it('offers Editar and Eliminar only for non-system roles, and only inside the drawer', async () => {
    const user = userEvent.setup();
    await renderPanel();

    // The cards carry no management buttons any more.
    for (const nombre of ['Editar', 'Eliminar rol', 'X', /^Clonar /]) {
      expect(screen.queryByRole('button', { name: nombre })).not.toBeInTheDocument();
    }

    const ventas = await abrirRol(user, 'Ventas');
    expect(within(ventas).getByRole('button', { name: 'Editar' })).toBeInTheDocument();
    expect(within(ventas).getByRole('button', { name: 'Eliminar rol' })).toBeInTheDocument();

    const admin = await abrirRol(user, 'Administrador');
    expect(within(admin).queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(within(admin).queryByRole('button', { name: 'Eliminar rol' })).not.toBeInTheDocument();
    expect(within(admin).getByRole('button', { name: 'Clonar Administrador' })).toBeInTheDocument();

    const superAdmin = await abrirRol(user, 'Super Admin');
    expect(within(superAdmin).queryByRole('button', { name: 'Clonar Super Admin' })).not.toBeInTheDocument();
  });

  it('patches name, description and order with the code locked, then reloads', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    expect(screen.getByRole('heading', { name: 'Editar Rol' })).toBeInTheDocument();
    const codigo = screen.getByPlaceholderText('Codigo (ej: VENDEDOR)');
    expect(codigo).toHaveValue('VENTAS');
    expect(codigo).toBeDisabled();
    const nombre = screen.getByPlaceholderText('Nombre');
    expect(nombre).toHaveValue('Ventas');
    await user.clear(nombre);
    await user.type(nombre, 'Ventas mostrador');
    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(api.patch).toHaveBeenCalledWith('/roles/3', { nombre: 'Ventas mostrador', descripcion: '', orden: 2 });
    expect(await screen.findByText('Rol actualizado correctamente')).toBeInTheDocument();
    await waitFor(() => expect(cargasDeRoles()).toBe(2));
  });

  it('disables the button and shows Guardando... while the update is in flight', async () => {
    const { promesa, resolver } = diferido();
    api.patch.mockReturnValueOnce(promesa);
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(screen.getByRole('button', { name: 'Guardando...' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Actualizar' })).not.toBeInTheDocument();
    // Cancelar would discard the form before the PATCH resolves (nothing left to retry from).
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeDisabled();

    await act(async () => resolver({ data: {} }));

    expect(await screen.findByText('Rol actualizado correctamente')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    expect(screen.getByRole('button', { name: 'Actualizar' })).toBeEnabled();
  });

  it('shows the fallback error when the update fails without detail', async () => {
    api.patch.mockRejectedValueOnce(new Error('Network Error'));
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(await screen.findByText('Error al actualizar rol')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Editar Rol' })).toBeInTheDocument();
  });

  it('clears the edit state on Cancelar so + Nuevo Rol opens an empty create form', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    expect(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)')).toHaveValue('VENTAS');
    expect(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)')).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('heading', { name: 'Editar Rol' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));

    expect(screen.getByRole('heading', { name: 'Nuevo Rol' })).toBeInTheDocument();
    const codigo = screen.getByPlaceholderText('Codigo (ej: VENDEDOR)');
    expect(codigo).toHaveValue('');
    expect(codigo).toBeEnabled();
    expect(screen.getByPlaceholderText('Nombre')).toHaveValue('');
    expect(screen.getByPlaceholderText('Descripcion (opcional)')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Crear' })).toBeInTheDocument();
  });
});

const MENSAJE_ELIMINAR = '¿Eliminar el rol "Ventas"? Esta accion no se puede deshacer.';

async function abrirConfirmacionEliminar(user) {
  await abrirRol(user, 'Ventas');
  await user.click(screen.getByRole('button', { name: 'Eliminar rol' }));
  expect(screen.getByRole('heading', { name: 'Eliminar rol' })).toBeInTheDocument();
  expect(screen.getByText(MENSAJE_ELIMINAR)).toBeInTheDocument();
}

describe('PanelRoles delete role', () => {
  it('asks for confirmation in a dialog without deleting yet', async () => {
    const confirmNativo = vi.fn(() => true);
    vi.stubGlobal('confirm', confirmNativo);
    const user = userEvent.setup();
    await renderPanel();

    await abrirConfirmacionEliminar(user);

    expect(confirmNativo).not.toHaveBeenCalled();
    expect(api.delete).not.toHaveBeenCalled();
  });

  it('deletes the role and reloads when confirmed in the dialog', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirConfirmacionEliminar(user);
    await user.click(screen.getByRole('button', { name: 'Eliminar' }));

    expect(api.delete).toHaveBeenCalledWith('/roles/3');
    expect(await screen.findByText('Rol eliminado correctamente')).toBeInTheDocument();
    expect(screen.queryByText(MENSAJE_ELIMINAR)).not.toBeInTheDocument();
    expect(queryDrawer()).not.toBeInTheDocument();
    await waitFor(() => expect(cargasDeRoles()).toBe(2));
  });

  it('closes the dialog on Cancelar without deleting', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirConfirmacionEliminar(user);
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(screen.queryByText(MENSAJE_ELIMINAR)).not.toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();
  });

  it('closes the dialog on Escape without deleting', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirConfirmacionEliminar(user);
    await user.keyboard('{Escape}');

    expect(screen.queryByText(MENSAJE_ELIMINAR)).not.toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();
    // Escape closes only the confirmation: the drawer behind it stays open.
    expect(drawer('Ventas')).toBeInTheDocument();
  });

  it('disables both buttons and ignores Escape and Cancelar while the delete is in flight', async () => {
    const { promesa, resolver } = diferido();
    api.delete.mockReturnValueOnce(promesa);
    const user = userEvent.setup();
    await renderPanel();

    await abrirConfirmacionEliminar(user);
    await user.click(screen.getByRole('button', { name: 'Eliminar' }));

    const cancelar = screen.getByRole('button', { name: 'Cancelar' });
    expect(screen.getByRole('button', { name: 'Eliminando...' })).toBeDisabled();
    expect(cancelar).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(screen.getByText(MENSAJE_ELIMINAR)).toBeInTheDocument();
    expect(drawer('Ventas')).toBeInTheDocument();
    expect(api.delete).toHaveBeenCalledTimes(1);

    await act(async () => resolver({ data: {} }));

    expect(await screen.findByText('Rol eliminado correctamente')).toBeInTheDocument();
    expect(screen.queryByText(MENSAJE_ELIMINAR)).not.toBeInTheDocument();
  });

  it('closes the dialog and shows the backend error when the delete fails', async () => {
    api.delete.mockRejectedValueOnce(errorConDetalle('El rol tiene usuarios asignados'));
    const user = userEvent.setup();
    await renderPanel();

    await abrirConfirmacionEliminar(user);
    await user.click(screen.getByRole('button', { name: 'Eliminar' }));

    expect(await screen.findByText('El rol tiene usuarios asignados')).toBeInTheDocument();
    expect(screen.queryByText(MENSAJE_ELIMINAR)).not.toBeInTheDocument();
    expect(cargasDeRoles()).toBe(1);
  });

  it('shows the fallback error when the delete fails without detail', async () => {
    api.delete.mockRejectedValueOnce(new Error('Network Error'));
    const user = userEvent.setup();
    await renderPanel();

    await abrirConfirmacionEliminar(user);
    await user.click(screen.getByRole('button', { name: 'Eliminar' }));

    expect(await screen.findByText('Error al eliminar rol')).toBeInTheDocument();
  });
});

describe('PanelRoles clone role', () => {
  // Clonar lives in the role drawer, which stays open after the clone.
  async function abrirClonarVentas(user) {
    await renderPanel();
    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Clonar Ventas' }));
    expect(screen.getByRole('heading', { name: 'Clonar Rol: Ventas' })).toBeInTheDocument();
  }

  it('posts the clone of the selected role with the uppercased code, then reloads', async () => {
    const user = userEvent.setup();
    await abrirClonarVentas(user);

    await user.type(screen.getByPlaceholderText('Codigo del nuevo rol'), 'ventas_web');
    await user.type(screen.getByPlaceholderText('Nombre del nuevo rol'), 'Ventas web');
    await user.type(screen.getByPlaceholderText('Descripcion (opcional)'), 'Copia para la web');
    await user.click(screen.getByRole('button', { name: 'Clonar' }));

    expect(api.post).toHaveBeenCalledWith('/roles/3/clonar', {
      nuevo_codigo: 'VENTAS_WEB', nuevo_nombre: 'Ventas web', descripcion: 'Copia para la web',
    });
    expect(await screen.findByText('Rol clonado correctamente')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Clonar Rol: Ventas' })).not.toBeInTheDocument();
    expect(drawer('Ventas')).toBeInTheDocument();
    await waitFor(() => expect(cargasDeRoles()).toBe(2));
  });

  it('requires code and name before posting', async () => {
    const user = userEvent.setup();
    await abrirClonarVentas(user);

    await user.click(screen.getByRole('button', { name: 'Clonar' }));

    expect(screen.getByText('Codigo y nombre son requeridos')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('disables the button and shows Clonando... while the clone is in flight', async () => {
    const { promesa, resolver } = diferido();
    api.post.mockReturnValueOnce(promesa);
    const user = userEvent.setup();
    await abrirClonarVentas(user);

    await user.type(screen.getByPlaceholderText('Codigo del nuevo rol'), 'COPIA');
    await user.type(screen.getByPlaceholderText('Nombre del nuevo rol'), 'Copia');
    await user.click(screen.getByRole('button', { name: 'Clonar' }));

    expect(screen.getByRole('button', { name: 'Clonando...' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Clonar' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeDisabled();

    await act(async () => resolver({ data: {} }));

    expect(await screen.findByText('Rol clonado correctamente')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clonar Ventas' }));
    expect(screen.getByRole('button', { name: 'Clonar' })).toBeEnabled();
  });

  it('shows the fallback error and keeps the modal open when the clone fails', async () => {
    api.post.mockRejectedValueOnce(new Error('Network Error'));
    const user = userEvent.setup();
    await abrirClonarVentas(user);

    await user.type(screen.getByPlaceholderText('Codigo del nuevo rol'), 'COPIA');
    await user.type(screen.getByPlaceholderText('Nombre del nuevo rol'), 'Copia');
    await user.click(screen.getByRole('button', { name: 'Clonar' }));

    expect(await screen.findByText('Error al clonar rol')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Clonar Rol: Ventas' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Codigo del nuevo rol')).toHaveValue('COPIA');
  });

  it('clears the fields on Cancelar', async () => {
    const user = userEvent.setup();
    await abrirClonarVentas(user);

    await user.type(screen.getByPlaceholderText('Codigo del nuevo rol'), 'COPIA');
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('heading', { name: 'Clonar Rol: Ventas' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clonar Ventas' }));
    expect(screen.getByPlaceholderText('Codigo del nuevo rol')).toHaveValue('');
    expect(api.post).not.toHaveBeenCalled();
  });
});

const celda = (permisoNombre, rolNombre) =>
  screen.getByRole('checkbox', { name: `${permisoNombre} para ${rolNombre}` });

async function renderMatriz() {
  render(<PanelRoles />);
  await screen.findByRole('table', { name: 'Matriz de roles y permisos' });
  await waitFor(() => expect(celda('Ver productos', 'Ventas')).toBeChecked());
}

const barra = () => screen.queryByRole('region', { name: 'Cambios pendientes' });

/**
 * Fake backend that remembers each PUT, so a reload returns what was saved.
 * `fallaGet` / `fallaPut` decide per role id whether that call fails; both can
 * be swapped on the returned object between steps.
 */
function servidorConEstado({ fallaGet = () => false, fallaPut = () => false } = {}) {
  const servidor = {
    estado: { 2: ['productos.ver', 'admin.ver_panel'], 3: ['productos.ver'] },
    fallaGet,
    fallaPut,
  };
  const rolDe = (url) => Number(url.match(/^\/roles\/(\d+)\/permisos$/)?.[1]);
  api.get.mockImplementation((url) => {
    if (url === '/roles') return Promise.resolve({ data: ROLES });
    if (url === '/permisos/catalogo') return Promise.resolve({ data: CATALOGO });
    const rolId = rolDe(url);
    if (servidor.estado[rolId] && !servidor.fallaGet(rolId)) {
      return Promise.resolve({ data: permisosDeRol(rolId, servidor.estado[rolId]) });
    }
    return Promise.reject(new Error(`GET ${url} falló`));
  });
  api.put.mockImplementation((url, body) => {
    const rolId = rolDe(url);
    if (servidor.fallaPut(rolId)) return Promise.reject(errorConDetalle('Error de red'));
    servidor.estado[rolId] = body.permisos;
    return Promise.resolve({ data: { success: true } });
  });
  return servidor;
}

describe('PanelRoles matrix', () => {
  it('renders roles as columns and permissions grouped by category with their state', async () => {
    await renderMatriz();
    const tabla = screen.getByRole('table', { name: 'Matriz de roles y permisos' });

    for (const rol of ['Super Admin', 'Administrador', 'Ventas']) {
      expect(within(tabla).getByRole('columnheader', { name: rol })).toBeInTheDocument();
    }
    expect(within(tabla).getByText('Productos')).toBeInTheDocument();
    expect(within(tabla).getByText('Administración del sistema')).toBeInTheDocument();

    expect(celda('Ver panel de administración', 'Administrador')).toBeChecked();
    expect(celda('Ver panel de administración', 'Ventas')).not.toBeChecked();
    expect(celda('Editar precios', 'Ventas')).not.toBeChecked();
    // SUPERADMIN has every permission (backend refuses to change it) and is not fetched.
    expect(celda('Editar precios', 'Super Admin')).toBeChecked();
    expect(api.get).not.toHaveBeenCalledWith('/roles/1/permisos');
    expect(barra()).not.toBeInTheDocument();
  });

  it('keeps the SUPERADMIN column read-only', async () => {
    await renderMatriz();
    expect(celda('Ver productos', 'Super Admin')).toBeDisabled();
    expect(celda('Ver productos', 'Administrador')).toBeEnabled();
  });

  it('marks a toggled cell as pending and shows the save bar with the count', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    expect(celda('Editar precios', 'Ventas')).toBeChecked();
    expect(celda('Editar precios', 'Ventas').closest('td').className).toMatch(/pendiente/);
    expect(within(barra()).getByText('1 cambio pendiente')).toBeInTheDocument();

    await user.click(celda('Ver productos', 'Administrador'));
    expect(within(barra()).getByText('2 cambios pendientes')).toBeInTheDocument();
  });

  it('clears the pending mark when the cell is toggled back', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(celda('Editar precios', 'Ventas'));

    expect(celda('Editar precios', 'Ventas')).not.toBeChecked();
    expect(celda('Editar precios', 'Ventas').closest('td').className).not.toMatch(/pendiente/);
    expect(barra()).not.toBeInTheDocument();
  });

  it('reverts every pending change on Descartar', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(celda('Ver productos', 'Administrador'));
    await user.click(within(barra()).getByRole('button', { name: 'Descartar' }));

    expect(celda('Editar precios', 'Ventas')).not.toBeChecked();
    expect(celda('Ver productos', 'Administrador')).toBeChecked();
    expect(barra()).not.toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('PUTs only the dirty roles with their full resulting permission set, then reloads', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    // Administrador toggled and back: not dirty, must not be sent.
    await user.click(celda('Ver productos', 'Administrador'));
    await user.click(celda('Ver productos', 'Administrador'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put).toHaveBeenCalledWith('/roles/3/permisos', {
      permisos: ['productos.editar_precios', 'productos.ver'],
    });
    expect(await screen.findByText('Permisos guardados correctamente')).toBeInTheDocument();
    expect(barra()).not.toBeInTheDocument();
    expect(api.get.mock.calls.filter(([url]) => url === '/roles/3/permisos')).toHaveLength(2);
  });

  it('disables the controls while saving', async () => {
    const user = userEvent.setup();
    let resolver;
    api.put.mockReturnValue(new Promise((resolve) => { resolver = resolve; }));
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    expect(within(barra()).getByRole('button', { name: 'Guardando...' })).toBeDisabled();
    expect(within(barra()).getByRole('button', { name: 'Descartar' })).toBeDisabled();
    expect(celda('Ver productos', 'Ventas')).toBeDisabled();

    resolver({ data: { success: true } });
    expect(await screen.findByText('Permisos guardados correctamente')).toBeInTheDocument();
    expect(celda('Ver productos', 'Ventas')).toBeEnabled();
  });

  it('shows the backend error and keeps the pending changes when the save fails', async () => {
    const user = userEvent.setup();
    api.put.mockRejectedValue({ response: { data: { detail: 'No tienes permiso para gestionar roles' } } });
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByText('No tienes permiso para gestionar roles')).toBeInTheDocument();
    expect(within(barra()).getByText('1 cambio pendiente')).toBeInTheDocument();
    expect(celda('Editar precios', 'Ventas')).toBeChecked();
    expect(within(barra()).getByRole('button', { name: 'Guardar' })).toBeEnabled();
  });

  it('filters permission rows by code or name ignoring accents', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await user.type(screen.getByPlaceholderText(/Buscá un permiso/), 'administracion');
    expect(celda('Ver panel de administración', 'Ventas')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Ver productos para Ventas' })).not.toBeInTheDocument();
    expect(screen.queryByText('Productos')).not.toBeInTheDocument();

    await user.clear(screen.getByPlaceholderText(/Buscá un permiso/));
    await user.type(screen.getByPlaceholderText(/Buscá un permiso/), 'editar_precios');
    expect(celda('Editar precios', 'Ventas')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Ver productos para Ventas' })).not.toBeInTheDocument();
  });

  it('marks only the roles that failed when one of two dirty roles fails to save', async () => {
    const user = userEvent.setup();
    const servidor = servidorConEstado({ fallaPut: (rolId) => rolId === 2 });
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(celda('Ver productos', 'Administrador'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    expect(
      await screen.findByText('Se guardaron los permisos de Ventas, pero fallaron los de Administrador: Error de red'),
    ).toBeInTheDocument();
    expect(servidor.estado[3]).toEqual(['productos.editar_precios', 'productos.ver']);
    // Ventas saved: no longer pending and showing the new state.
    expect(celda('Editar precios', 'Ventas')).toBeChecked();
    expect(celda('Editar precios', 'Ventas').closest('td').className).not.toMatch(/pendiente/);
    // Administrador failed: its change stays pending.
    expect(celda('Ver productos', 'Administrador')).not.toBeChecked();
    expect(celda('Ver productos', 'Administrador').closest('td').className).toMatch(/pendiente/);
    expect(within(barra()).getByText('1 cambio pendiente')).toBeInTheDocument();
  });

  it('keeps the saved state as the base when the reload after saving fails', async () => {
    const user = userEvent.setup();
    const servidor = servidorConEstado();
    await renderMatriz();
    servidor.fallaGet = (rolId) => rolId === 3;

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    expect(
      await screen.findByText('Permisos guardados, pero no se pudieron recargar. Actualizá la página.'),
    ).toBeInTheDocument();
    expect(barra()).not.toBeInTheDocument();
    expect(celda('Editar precios', 'Ventas')).toBeChecked();
    expect(celda('Ver productos', 'Ventas')).toBeChecked();

    // A second save must start from what was saved, not from the pre-save state.
    await user.click(celda('Ver productos', 'Ventas'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    expect(api.put).toHaveBeenLastCalledWith('/roles/3/permisos', { permisos: ['productos.editar_precios'] });
  });

  it('does not claim the permissions were saved when a save and the reload both fail', async () => {
    const user = userEvent.setup();
    const servidor = servidorConEstado({ fallaPut: (rolId) => rolId === 2 });
    await renderMatriz();
    servidor.fallaGet = () => true;

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(celda('Ver productos', 'Administrador'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    expect(
      await screen.findByText(
        'Se guardaron los permisos de Ventas, pero fallaron los de Administrador: Error de red. ' +
          'No se pudieron recargar los permisos; actualizá la página.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Permisos guardados/)).not.toBeInTheDocument();
    expect(celda('Editar precios', 'Ventas')).toBeChecked();
    expect(celda('Ver productos', 'Administrador').closest('td').className).toMatch(/pendiente/);
  });

  it('locks the column of a role whose permissions failed to load and never saves it', async () => {
    const user = userEvent.setup();
    servidorConEstado({ fallaGet: (rolId) => rolId === 3 });
    render(<PanelRoles />);
    await screen.findByRole('table', { name: 'Matriz de roles y permisos' });
    await waitFor(() => expect(celda('Ver productos', 'Administrador')).toBeChecked());

    expect(await screen.findByText('No se pudieron cargar los permisos de: Ventas')).toBeInTheDocument();
    for (const nombre of ['Ver productos', 'Editar precios', 'Ver panel de administración']) {
      expect(celda(nombre, 'Ventas')).toBeDisabled();
      expect(celda(nombre, 'Ventas')).toHaveAttribute('title', 'No se pudieron cargar los permisos de este rol');
    }
    expect(screen.getByRole('columnheader', { name: 'Ventas' })).toHaveAttribute(
      'title',
      'No se pudieron cargar los permisos de este rol',
    );

    await user.click(celda('Editar precios', 'Administrador'));
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put).toHaveBeenCalledWith('/roles/2/permisos', {
      permisos: ['admin.ver_panel', 'productos.editar_precios', 'productos.ver'],
    });
    expect(api.put).not.toHaveBeenCalledWith('/roles/3/permisos', expect.anything());
  });

  it('locks role management while a matrix save is in flight', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    // The drawer shows one thing at a time: first the create form, then a role's actions.
    const fases = [
      { abrir: () => user.click(screen.getByRole('button', { name: '+ Nuevo Rol' })), botones: ['Crear'] },
      {
        // Leave the create form first: the cards are locked while a form is open.
        abrir: async () => {
          await user.click(screen.getByRole('button', { name: 'Cancelar' }));
          await abrirRol(user, 'Ventas');
        },
        botones: ['+ Nuevo Rol', 'Clonar Ventas', 'Editar', 'Eliminar rol'],
      },
    ];
    for (const { abrir, botones } of fases) {
      const { promesa, resolver } = diferido();
      api.put.mockReturnValueOnce(promesa);
      await abrir();
      await user.click(celda('Editar precios', 'Ventas'));
      await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

      for (const nombre of botones) {
        expect(screen.getByRole('button', { name: nombre })).toBeDisabled();
      }

      await act(async () => resolver({ data: { success: true } }));
      expect(await screen.findByText('Permisos guardados correctamente')).toBeInTheDocument();
      for (const nombre of botones) {
        expect(screen.getByRole('button', { name: nombre })).toBeEnabled();
      }
    }
  });

  it('locks the matrix while a role clone is in flight', async () => {
    const { promesa, resolver } = diferido();
    api.post.mockReturnValueOnce(promesa);
    const user = userEvent.setup();
    await renderMatriz();

    await user.click(celda('Editar precios', 'Ventas'));
    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Clonar Ventas' }));
    await user.type(screen.getByPlaceholderText('Codigo del nuevo rol'), 'VENTAS_WEB');
    await user.type(screen.getByPlaceholderText('Nombre del nuevo rol'), 'Ventas web');
    await user.click(screen.getByRole('button', { name: 'Clonar' }));

    expect(celda('Ver productos', 'Ventas')).toBeDisabled();
    expect(within(barra()).getByRole('button', { name: 'Guardar' })).toBeDisabled();
    expect(within(barra()).getByRole('button', { name: 'Descartar' })).toBeDisabled();

    await act(async () => resolver({ data: {} }));
    expect(await screen.findByText('Rol clonado correctamente')).toBeInTheDocument();
    expect(within(barra()).getByRole('button', { name: 'Guardar' })).toBeEnabled();
    expect(celda('Ver productos', 'Ventas')).toBeEnabled();
  });

  it('ignores an older permissions load that resolves after a newer one', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    const cargas = [];
    const getOriginal = api.get.getMockImplementation();
    api.get.mockImplementation((url) => {
      if (url !== '/roles/3/permisos') return getOriginal(url);
      const carga = diferido();
      cargas.push(carga);
      return carga.promesa;
    });

    const crear = async (codigo) => {
      await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
      await user.type(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)'), codigo);
      await user.type(screen.getByPlaceholderText('Nombre'), codigo);
      await user.click(screen.getByRole('button', { name: 'Crear' }));
    };
    await crear('UNO');
    await waitFor(() => expect(cargas).toHaveLength(1));
    await crear('DOS');
    await waitFor(() => expect(cargas).toHaveLength(2));

    await act(async () => cargas[1].resolver({ data: permisosDeRol(3, ['productos.ver', 'productos.editar_precios']) }));
    await waitFor(() => expect(celda('Editar precios', 'Ventas')).toBeChecked());
    await act(async () => cargas[0].resolver({ data: permisosDeRol(3, ['productos.ver']) }));

    expect(celda('Editar precios', 'Ventas')).toBeChecked();
    expect(celda('Editar precios', 'Ventas').closest('td').className).not.toMatch(/pendiente/);
  });

  it('loads the new role column when a matrix save started before the role reload finished', async () => {
    const user = userEvent.setup();
    const servidor = servidorConEstado();
    servidor.estado[4] = ['productos.ver'];
    const COMPRAS = { ...ROLES[2], id: 4, codigo: 'COMPRAS', nombre: 'Compras', orden: 3 };
    await renderMatriz();

    // The role reload after the create stays in flight while the matrix save starts.
    const recargaRoles = diferido();
    const getServidor = api.get.getMockImplementation();
    api.get.mockImplementation((url) => {
      if (url === '/roles') return recargaRoles.promesa;
      if (url === '/roles/4/permisos') return Promise.resolve({ data: { ...permisosDeRol(3, servidor.estado[4]), rol_id: 4 } });
      return getServidor(url);
    });
    const put = diferido();
    api.put.mockReturnValueOnce(put.promesa);

    await user.click(celda('Editar precios', 'Ventas'));
    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.type(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)'), 'COMPRAS');
    await user.type(screen.getByPlaceholderText('Nombre'), 'Compras');
    await user.click(screen.getByRole('button', { name: 'Crear' }));
    expect(await screen.findByText('Rol creado correctamente')).toBeInTheDocument();
    await user.click(within(barra()).getByRole('button', { name: 'Guardar' }));

    await act(async () => recargaRoles.resolver({ data: [...ROLES, COMPRAS] }));
    await waitFor(() => expect(celda('Ver productos', 'Compras')).toBeChecked());
    await act(async () => put.resolver({ data: { success: true } }));

    expect(await screen.findByText('Permisos guardados correctamente')).toBeInTheDocument();
    expect(celda('Ver productos', 'Compras')).toBeChecked();
    expect(celda('Ver productos', 'Compras')).toBeEnabled();
    expect(screen.getByRole('columnheader', { name: 'Compras' })).not.toHaveAttribute(
      'title',
      'No se pudieron cargar los permisos de este rol',
    );
  });

  it('keeps the create role flow working', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.type(screen.getByPlaceholderText('Codigo (ej: VENDEDOR)'), 'compras');
    await user.type(screen.getByPlaceholderText('Nombre'), 'Compras');
    await user.click(screen.getByRole('button', { name: 'Crear' }));

    expect(api.post).toHaveBeenCalledWith('/roles', expect.objectContaining({ codigo: 'COMPRAS', nombre: 'Compras' }));
    expect(await screen.findByText('Rol creado correctamente')).toBeInTheDocument();
  });
});

describe('PanelRoles role drawer', () => {
  it('opens from the role card with the role detail', async () => {
    const user = userEvent.setup();
    await renderMatriz();
    expect(queryDrawer()).not.toBeInTheDocument();

    const admin = await abrirRol(user, 'Administrador');
    expect(within(admin).getByRole('heading', { name: 'Administrador' })).toBeInTheDocument();
    expect(within(admin).getByText('SISTEMA')).toBeInTheDocument();
    const detalle = (termino) => within(admin).getByText(termino).nextElementSibling;
    expect(detalle('Código')).toHaveTextContent('ADMIN');
    expect(detalle('Descripción')).toHaveTextContent('Sin descripción');
    expect(detalle('Usuarios')).toHaveTextContent('2');
    expect(detalle('Permisos')).toHaveTextContent('2');

    const superAdmin = await abrirRol(user, 'Super Admin');
    expect(within(superAdmin).getByText('Permisos').nextElementSibling).toHaveTextContent('Todos');
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
  });

  it('moves focus into the drawer when it switches to another role, so Escape still closes it', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await abrirRol(user, 'Administrador');
    expect(drawer('Administrador')).toContainElement(document.activeElement);

    await user.keyboard('{Escape}');
    expect(queryDrawer()).not.toBeInTheDocument();
  });

  it('says Sin cargar for a role whose permissions failed to load', async () => {
    const user = userEvent.setup();
    servidorConEstado({ fallaGet: (rolId) => rolId === 3 });
    await renderPanel();
    expect(await screen.findByText('No se pudieron cargar los permisos de: Ventas')).toBeInTheDocument();

    const ventas = await abrirRol(user, 'Ventas');
    expect(within(ventas).getByText('Permisos').nextElementSibling).toHaveTextContent('Sin cargar');
  });

  it('opens in create mode from + Nuevo Rol', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));

    expect(within(drawer('Nuevo Rol')).getByPlaceholderText('Codigo (ej: VENDEDOR)')).toBeEnabled();
  });

  it('closes with the close button and with Escape', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Cerrar panel del rol' }));
    expect(queryDrawer()).not.toBeInTheDocument();

    await abrirRol(user, 'Ventas');
    await user.keyboard('{Escape}');
    expect(queryDrawer()).not.toBeInTheDocument();
  });

  it('closes on Escape only when it comes from inside the drawer, not from the matrix search', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.type(screen.getByPlaceholderText('Nombre'), 'Compras');
    await user.click(screen.getByPlaceholderText(/Buscá un permiso/));
    await user.keyboard('{Escape}');
    expect(drawer('Nuevo Rol')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Nombre')).toHaveValue('Compras');

    await user.click(screen.getByPlaceholderText('Nombre'));
    await user.keyboard('{Escape}');
    expect(queryDrawer()).not.toBeInTheDocument();
  });

  it('locks the role cards and + Nuevo Rol while the edit form is open, so typed input is never discarded', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.type(screen.getByPlaceholderText('Descripcion (opcional)'), 'Mostrador');

    expect(tarjeta('Administrador')).toBeDisabled();
    expect(screen.getByRole('button', { name: '+ Nuevo Rol' })).toBeDisabled();
    await user.click(tarjeta('Administrador'));
    expect(drawer('Editar Rol')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Descripcion (opcional)')).toHaveValue('Mostrador');

    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(tarjeta('Administrador')).toBeEnabled();
    expect(screen.getByRole('button', { name: '+ Nuevo Rol' })).toBeEnabled();
  });

  it('locks the role cards while the create form is open', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: '+ Nuevo Rol' }));
    await user.type(screen.getByPlaceholderText('Nombre'), 'Compras');

    expect(tarjeta('Ventas')).toBeDisabled();
    expect(screen.getByRole('button', { name: '+ Nuevo Rol' })).toBeDisabled();
    await user.click(tarjeta('Ventas'));
    expect(drawer('Nuevo Rol')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Nombre')).toHaveValue('Compras');

    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(tarjeta('Ventas')).toBeEnabled();
  });

  it('cannot be closed while a role save is in flight', async () => {
    const { promesa, resolver } = diferido();
    api.patch.mockReturnValueOnce(promesa);
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(screen.getByRole('button', { name: 'Cerrar panel del rol' })).toBeDisabled();
    expect(tarjeta('Administrador')).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(drawer('Editar Rol')).toBeInTheDocument();

    await act(async () => resolver({ data: {} }));
    expect(await screen.findByText('Rol actualizado correctamente')).toBeInTheDocument();
    // Back to the role detail, closable again.
    expect(drawer('Ventas')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cerrar panel del rol' })).toBeEnabled();
  });

  it('ignores Escape while the clone dialog is open on top of it', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await abrirRol(user, 'Ventas');
    await user.click(screen.getByRole('button', { name: 'Clonar Ventas' }));
    await user.keyboard('{Escape}');

    expect(drawer('Ventas')).toBeInTheDocument();
  });
});

describe('PanelRoles selected role in the matrix', () => {
  const tabla = () => screen.getByRole('table', { name: 'Matriz de roles y permisos' });
  const encabezado = (nombre) => within(tabla()).getByRole('columnheader', { name: nombre });
  const td = (permisoNombre, rolNombre) => celda(permisoNombre, rolNombre).closest('td');
  const soloDelRol = () => screen.queryByRole('checkbox', { name: /^Solo los permisos de este rol/ });
  const fila = (permisoNombre) => within(tabla()).queryByRole('rowheader', { name: new RegExp(`^${permisoNombre}`) });

  it('marks the header and every cell of the selected role column, granted cells more strongly', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await abrirRol(user, 'Ventas');

    expect(encabezado('Ventas (seleccionado)')).toHaveAttribute('aria-current', 'true');
    expect(td('Ver productos', 'Ventas').className).toMatch(/celdaSeleccionada/);
    expect(td('Ver productos', 'Ventas').className).toMatch(/celdaConcedida/);
    expect(td('Editar precios', 'Ventas').className).toMatch(/celdaSeleccionada/);
    expect(td('Editar precios', 'Ventas').className).not.toMatch(/celdaConcedida/);
    expect(td('Ver panel de administración', 'Ventas').className).toMatch(/celdaSeleccionada/);
  });

  it('leaves the other columns unmarked', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await abrirRol(user, 'Ventas');

    expect(encabezado('Administrador')).not.toHaveAttribute('aria-current');
    expect(encabezado('Super Admin')).not.toHaveAttribute('aria-current');
    for (const permisoNombre of ['Ver productos', 'Editar precios', 'Ver panel de administración']) {
      expect(td(permisoNombre, 'Administrador').className).not.toMatch(/celdaSeleccionada|celdaConcedida/);
      expect(td(permisoNombre, 'Super Admin').className).not.toMatch(/celdaSeleccionada|celdaConcedida/);
    }
  });

  it('hides the role filter toggle while no role is selected', async () => {
    await renderMatriz();
    expect(soloDelRol()).not.toBeInTheDocument();
    expect(within(tabla()).queryByRole('columnheader', { name: /seleccionado/ })).not.toBeInTheDocument();
  });

  it('filters the rows to the role permissions, counting a pending change, and hides empty categories', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await abrirRol(user, 'Ventas');
    expect(soloDelRol()).not.toBeChecked();
    expect(soloDelRol()).toHaveAccessibleName('Solo los permisos de este rol (1)');

    await user.click(celda('Editar precios', 'Ventas'));
    expect(soloDelRol()).toHaveAccessibleName('Solo los permisos de este rol (2)');

    await user.click(soloDelRol());

    expect(soloDelRol()).toBeChecked();
    expect(fila('Ver productos')).toBeInTheDocument();
    expect(fila('Editar precios')).toBeInTheDocument();
    expect(fila('Ver panel de administración')).not.toBeInTheDocument();
    expect(within(tabla()).getByText('Productos')).toBeInTheDocument();
    expect(within(tabla()).queryByText('Administración del sistema')).not.toBeInTheDocument();

    await user.click(soloDelRol());
    expect(fila('Ver panel de administración')).toBeInTheDocument();
  });

  it('keeps the filter on when switching to another role and applies it to that role', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await abrirRol(user, 'Ventas');
    await user.click(soloDelRol());
    await abrirRol(user, 'Administrador');

    expect(soloDelRol()).toBeChecked();
    expect(soloDelRol()).toHaveAccessibleName('Solo los permisos de este rol (2)');
    expect(fila('Ver panel de administración')).toBeInTheDocument();
    expect(fila('Editar precios')).not.toBeInTheDocument();
    expect(encabezado('Administrador (seleccionado)')).toHaveAttribute('aria-current', 'true');
    expect(encabezado('Ventas')).not.toHaveAttribute('aria-current');
  });

  it('clears the highlight and resets the filter when the drawer closes', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await abrirRol(user, 'Ventas');
    await user.click(soloDelRol());
    await user.click(screen.getByRole('button', { name: 'Cerrar panel del rol' }));

    expect(queryDrawer()).not.toBeInTheDocument();
    expect(encabezado('Ventas')).not.toHaveAttribute('aria-current');
    expect(td('Ver productos', 'Ventas').className).not.toMatch(/celdaSeleccionada|celdaConcedida/);
    expect(soloDelRol()).not.toBeInTheDocument();
    expect(fila('Ver panel de administración')).toBeInTheDocument();

    await abrirRol(user, 'Ventas');
    expect(soloDelRol()).not.toBeChecked();
  });

  it('keeps a row the selected role just unchecked visible while the filter is on, marked as pending', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    await abrirRol(user, 'Ventas');
    await user.click(soloDelRol());
    await user.click(celda('Ver productos', 'Ventas'));

    expect(fila('Ver productos')).toBeInTheDocument();
    expect(celda('Ver productos', 'Ventas')).not.toBeChecked();
    expect(td('Ver productos', 'Ventas').className).toMatch(/pendiente/);
    expect(soloDelRol()).toHaveAccessibleName('Solo los permisos de este rol (0)');

    // Undo it from the same row: it is granted again and no longer pending.
    await user.click(celda('Ver productos', 'Ventas'));
    expect(celda('Ver productos', 'Ventas')).toBeChecked();
    expect(td('Ver productos', 'Ventas').className).not.toMatch(/pendiente/);
  });

  describe('horizontal scroll to the selected column', () => {
    // jsdom has no layout: fake the live rects. The scroller sits at x=100 and shows 600px;
    // "Permiso" is sticky (always 100..360); role columns are 120px wide at these content
    // offsets and move left as the scroller scrolls. Ventas starts off to the right.
    const IZQUIERDA = { 'Super Admin': 260, Administrador: 380, Ventas: 900 };
    const SCROLLER_X = 100;
    let scrollLeft;
    let scrollTo;

    const nombreColumna = (el) => el.firstChild?.textContent;
    const rect = (left, width) => ({ left, right: left + width, width, top: 0, bottom: 40, height: 40, x: left, y: 0 });

    beforeEach(() => {
      scrollLeft = 0;
      scrollTo = vi.fn();
      Element.prototype.scrollTo = scrollTo;
      Element.prototype.scrollIntoView = vi.fn();
      vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
      vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function getBoundingClientRect() {
        if (this.tagName === 'DIV' && this.firstElementChild?.tagName === 'TABLE') return rect(SCROLLER_X, 600);
        if (this.tagName === 'TH' && nombreColumna(this) === 'Permiso') return rect(SCROLLER_X, 260);
        const izquierda = this.tagName === 'TH' ? IZQUIERDA[nombreColumna(this)] : undefined;
        if (izquierda !== undefined) return rect(SCROLLER_X + izquierda - scrollLeft, 120);
        return rect(0, 0);
      });
      vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(600);
      vi.spyOn(Element.prototype, 'scrollLeft', 'get').mockImplementation(() => scrollLeft);
    });

    afterEach(() => {
      delete Element.prototype.scrollTo;
      delete Element.prototype.scrollIntoView;
    });

    const scrollerDeLaTabla = () => tabla().parentElement;

    it('scrolls the matrix right so a selected column past the right edge is visible', async () => {
      const user = userEvent.setup();
      await renderMatriz();

      await abrirRol(user, 'Ventas');

      expect(scrollTo).toHaveBeenCalledTimes(1);
      expect(scrollTo.mock.contexts[0]).toBe(scrollerDeLaTabla());
      // Ventas ends at 1020px; the scroller shows 600px.
      expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ left: 420 }));
      expect(window.scrollTo).not.toHaveBeenCalled();
      expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    });

    it('scrolls back left past the sticky permission column when switching to a hidden role', async () => {
      const user = userEvent.setup();
      await renderMatriz();
      await abrirRol(user, 'Ventas');
      scrollLeft = 420;
      scrollTo.mockClear();

      await abrirRol(user, 'Administrador');

      // Administrador starts at 380px, but the first 260px of the view are covered by "Permiso".
      expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ left: 120 }));
      expect(scrollTo.mock.contexts[0]).toBe(scrollerDeLaTabla());
    });

    it('does not scroll when the selected column is already visible', async () => {
      const user = userEvent.setup();
      await renderMatriz();

      await abrirRol(user, 'Administrador');

      expect(scrollTo).not.toHaveBeenCalled();
    });
  });

  it('turns the filter on from the permission count in the role detail', async () => {
    const user = userEvent.setup();
    await renderMatriz();

    const admin = await abrirRol(user, 'Administrador');
    await user.click(within(admin).getByRole('button', { name: 'Ver solo los 2 permisos de Administrador en la matriz' }));

    expect(soloDelRol()).toBeChecked();
    expect(fila('Editar precios')).not.toBeInTheDocument();
  });
});
