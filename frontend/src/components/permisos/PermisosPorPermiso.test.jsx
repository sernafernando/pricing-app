import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import PermisosPorPermiso from './PermisosPorPermiso';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const { permisosDenegados } = vi.hoisted(() => ({ permisosDenegados: new Set() }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => !permisosDenegados.has(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const USUARIO_ID = 7;
const ACCION = /^(Conceder|Quitar|Resetear)/;

function permiso(codigo, extra = {}) {
  return {
    codigo,
    nombre: `Nombre ${codigo}`,
    descripcion: '',
    es_critico: false,
    tiene_por_rol: false,
    override: null,
    efectivo: false,
    origen: 'sin_permiso',
    ...extra,
  };
}

// Mirrors GET /permisos/usuario/{id}: permissions grouped by backend category.
function payload(rol = 'PRICING') {
  return {
    usuario_id: USUARIO_ID,
    rol,
    permisos_detallados: {
      productos: [
        permiso('productos.ver', { tiene_por_rol: true, efectivo: true, origen: 'rol' }),
        permiso('productos.editar_precio', { nombre: 'Editar precio', override: true, efectivo: true, origen: 'override_agregado' }),
      ],
      administracion: [
        permiso('admin.ver_panel', { es_critico: true }),
        permiso('admin.sincronizar', { tiene_por_rol: true, override: false, origen: 'override_quitado' }),
      ],
    },
  };
}

function renderVista(props = {}) {
  const onActualizado = vi.fn().mockResolvedValue(undefined);
  const onMensaje = vi.fn();
  render(
    <PermisosPorPermiso
      usuarioId={USUARIO_ID}
      permisosUsuario={payload()}
      onActualizado={onActualizado}
      onMensaje={onMensaje}
      {...props}
    />,
  );
  return { onActualizado, onMensaje };
}

const grupo = (nombre) => screen.getByRole('region', { name: nombre });
const fila = (codigo) => screen.getByText(codigo, { selector: 'code' }).closest('li');

beforeEach(() => {
  vi.clearAllMocks();
  permisosDenegados.clear();
  api.post.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

describe('PermisosPorPermiso', () => {
  it('lists every permission grouped by its category label with a granted count', () => {
    renderVista();

    const productos = grupo('Productos');
    expect(within(productos).getByText('productos.ver')).toBeInTheDocument();
    expect(within(productos).getByText('productos.editar_precio')).toBeInTheDocument();
    expect(within(productos).getByText('2 de 2 concedidos')).toBeInTheDocument();

    const admin = grupo('Administración del sistema');
    expect(within(admin).getByText('admin.ver_panel')).toBeInTheDocument();
    expect(within(admin).getByText('0 de 2 concedidos')).toBeInTheDocument();
  });

  it('shows where each permission comes from', () => {
    renderVista();

    expect(within(fila('productos.ver')).getByText('Concedido por el rol')).toBeInTheDocument();
    expect(within(fila('productos.editar_precio')).getByText('Agregado por override')).toBeInTheDocument();
    expect(within(fila('admin.sincronizar')).getByText('Quitado por override')).toBeInTheDocument();
    expect(within(fila('admin.ver_panel')).getByText('Falta permiso')).toBeInTheDocument();
    expect(within(fila('admin.ver_panel')).getByText('Crítico')).toBeInTheDocument();
  });

  it('grants a missing permission with the same override endpoint and reloads before announcing it', async () => {
    const user = userEvent.setup();
    const { onActualizado, onMensaje } = renderVista();

    await user.click(within(fila('admin.ver_panel')).getByRole('button', { name: 'Conceder admin.ver_panel' }));

    expect(api.post).toHaveBeenCalledWith('/permisos/override', {
      usuario_id: USUARIO_ID,
      permiso_codigo: 'admin.ver_panel',
      concedido: true,
      motivo: 'Override desde panel de permisos',
    });
    await waitFor(() => expect(onMensaje).toHaveBeenCalledWith({ tipo: 'success', texto: 'Permiso concedido' }));
    expect(onActualizado).toHaveBeenCalledTimes(1);
  });

  it('removes a role permission and resets an override', async () => {
    const user = userEvent.setup();
    const { onMensaje } = renderVista();

    await user.click(within(fila('productos.ver')).getByRole('button', { name: 'Quitar productos.ver' }));
    expect(api.post).toHaveBeenCalledWith(
      '/permisos/override',
      expect.objectContaining({ permiso_codigo: 'productos.ver', concedido: false }),
    );
    await waitFor(() => expect(onMensaje).toHaveBeenCalledWith({ tipo: 'success', texto: 'Permiso quitado' }));

    await user.click(within(fila('admin.sincronizar')).getByRole('button', { name: 'Resetear admin.sincronizar' }));
    expect(api.delete).toHaveBeenCalledWith(`/permisos/override/${USUARIO_ID}/admin.sincronizar`);
    await waitFor(() =>
      expect(onMensaje).toHaveBeenCalledWith({ tipo: 'success', texto: 'Vuelto al permiso base del rol' }),
    );
  });

  it('reports a backend error and does not reload', async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValueOnce({ response: { data: { detail: 'No autorizado' } } });
    const { onActualizado, onMensaje } = renderVista();

    await user.click(within(fila('admin.ver_panel')).getByRole('button', { name: 'Conceder admin.ver_panel' }));

    await waitFor(() => expect(onMensaje).toHaveBeenCalledWith({ tipo: 'error', texto: 'No autorizado' }));
    expect(onActualizado).not.toHaveBeenCalled();
    expect(within(fila('admin.ver_panel')).getByRole('button', { name: 'Conceder admin.ver_panel' })).toBeEnabled();
  });

  it('filters by code or name ignoring case and accents, and says so when nothing matches', async () => {
    const user = userEvent.setup();
    renderVista();
    const buscador = screen.getByPlaceholderText(/Buscá un permiso/);

    await user.type(buscador, 'EDITAR PRÉCIO');
    expect(screen.getByText('productos.editar_precio')).toBeInTheDocument();
    expect(screen.queryByText('productos.ver')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Administración del sistema' })).not.toBeInTheDocument();

    await user.clear(buscador);
    await user.type(buscador, 'admin.sinc');
    expect(screen.getByText('admin.sincronizar')).toBeInTheDocument();
    expect(screen.queryByText('admin.ver_panel')).not.toBeInTheDocument();

    await user.clear(buscador);
    await user.type(buscador, 'nada que ver');
    expect(screen.getByText('No hay permisos que coincidan.')).toBeInTheDocument();
  });

  it('hides the actions for a viewer who cannot manage permissions', () => {
    permisosDenegados.add('admin.gestionar_permisos');
    renderVista();

    expect(screen.queryByRole('button', { name: ACCION })).not.toBeInTheDocument();
  });

  it('hides the actions for a SUPERADMIN target', () => {
    renderVista({ permisosUsuario: payload('SUPERADMIN') });

    expect(screen.queryByRole('button', { name: ACCION })).not.toBeInTheDocument();
  });
});
