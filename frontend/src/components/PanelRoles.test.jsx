import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
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

const CATALOGO = {
  productos: [{ codigo: 'productos.ver', nombre: 'Ver productos', descripcion: null, es_critico: false }],
};

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
  vi.stubGlobal('confirm', vi.fn(() => true));
  api.get.mockImplementation((url) => {
    if (url === '/roles') return Promise.resolve({ data: ROLES });
    if (url === '/permisos/catalogo') return Promise.resolve({ data: CATALOGO });
    if (url === '/roles/3/permisos') {
      return Promise.resolve({ data: { rol_id: 3, rol_codigo: 'VENTAS', permisos: [{ codigo: 'productos.ver' }] } });
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
  api.post.mockResolvedValue({ data: {} });
  api.patch.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function renderPanel() {
  render(<PanelRoles />);
  await screen.findByText('Ventas');
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
  it('offers Editar and X only for non-system roles', async () => {
    await renderPanel();

    expect(screen.getAllByRole('button', { name: 'Editar' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'X' })).toHaveLength(1);
  });

  it('patches name, description and order with the code locked, then reloads', async () => {
    const user = userEvent.setup();
    await renderPanel();

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

    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(screen.getByRole('button', { name: 'Guardando...' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Actualizar' })).not.toBeInTheDocument();

    await act(async () => resolver({ data: {} }));

    expect(await screen.findByText('Rol actualizado correctamente')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Editar' }));
    expect(screen.getByRole('button', { name: 'Actualizar' })).toBeEnabled();
  });

  it('shows the fallback error when the update fails without detail', async () => {
    api.patch.mockRejectedValueOnce(new Error('Network Error'));
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(await screen.findByText('Error al actualizar rol')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Editar Rol' })).toBeInTheDocument();
  });

  it('clears the edit state on Cancelar so + Nuevo Rol opens an empty create form', async () => {
    const user = userEvent.setup();
    await renderPanel();

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

describe('PanelRoles delete role', () => {
  it('asks for confirmation, deletes the role and reloads', async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: 'X' }));

    expect(globalThis.confirm).toHaveBeenCalledWith('¿Eliminar el rol "Ventas"? Esta accion no se puede deshacer.');
    expect(api.delete).toHaveBeenCalledWith('/roles/3');
    expect(await screen.findByText('Rol eliminado correctamente')).toBeInTheDocument();
    await waitFor(() => expect(cargasDeRoles()).toBe(2));
  });

  it('does nothing when the confirmation is cancelled', async () => {
    globalThis.confirm.mockReturnValue(false);
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: 'X' }));

    expect(api.delete).not.toHaveBeenCalled();
  });

  it('shows the backend error when the delete fails', async () => {
    api.delete.mockRejectedValueOnce(errorConDetalle('El rol tiene usuarios asignados'));
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole('button', { name: 'X' }));

    expect(await screen.findByText('El rol tiene usuarios asignados')).toBeInTheDocument();
    expect(cargasDeRoles()).toBe(1);
  });
});

describe('PanelRoles clone role', () => {
  async function abrirClonarVentas(user) {
    await renderPanel();
    await user.click(screen.getByText('Ventas'));
    await screen.findByRole('heading', { name: 'Permisos de: Ventas' });
    await user.click(screen.getByRole('button', { name: 'Clonar Rol' }));
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

    await act(async () => resolver({ data: {} }));

    expect(await screen.findByText('Rol clonado correctamente')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clonar Rol' }));
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

    await user.click(screen.getByRole('button', { name: 'Clonar Rol' }));
    expect(screen.getByPlaceholderText('Codigo del nuevo rol')).toHaveValue('');
    expect(api.post).not.toHaveBeenCalled();
  });
});
