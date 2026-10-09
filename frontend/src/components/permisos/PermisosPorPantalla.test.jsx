import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import api, { marcasPmAPI } from '../../services/api';
import PermisosPorPantalla from './PermisosPorPantalla';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
  marcasPmAPI: {
    listarTodosLosPares: vi.fn(),
    obtenerConteosSubPMs: vi.fn(),
  },
}));

const USUARIO_ID = 7;

function permiso(codigo, extra = {}) {
  return {
    codigo,
    nombre: `Nombre ${codigo}`,
    descripcion: `Descripción de ${codigo}`,
    es_critico: false,
    tiene_por_rol: false,
    override: null,
    efectivo: false,
    origen: 'sin_permiso',
    ...extra,
  };
}

const delRol = (codigo) => permiso(codigo, { tiene_por_rol: true, efectivo: true, origen: 'rol' });

function payload(rol = 'PRICING') {
  return {
    usuario_id: USUARIO_ID,
    rol,
    permisos_detallados: {
      productos: [delRol('productos.ver')],
      ventas_ml: [delRol('ml_metricas.ver')],
      administracion: [permiso('admin.ver_panel', { es_critico: true }), permiso('admin.sincronizar')],
      consultas: [delRol('traza.ver')],
    },
  };
}

function renderPanel(props = {}) {
  const onActualizado = vi.fn().mockResolvedValue(undefined);
  const onMensaje = vi.fn();
  render(
    <MemoryRouter>
      <PermisosPorPantalla
        usuarioId={USUARIO_ID}
        permisosUsuario={payload()}
        onActualizado={onActualizado}
        onMensaje={onMensaje}
        {...props}
      />
    </MemoryRouter>,
  );
  return { onActualizado, onMensaje };
}

// Lets the pair-count requests settle, so an "absent" assertion is not vacuous.
const flush = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

// The row of a screen, found by its unique monospace path.
const fila = (path) => screen.getByText(path, { selector: 'code' }).closest('li');

function paresDe({ titular = 0, delegados = 0 } = {}) {
  marcasPmAPI.listarTodosLosPares.mockResolvedValue({
    data: Array.from({ length: titular }, (_, i) => ({ id: i, marca: `M${i}`, categoria: 'C', usuario_id: USUARIO_ID })),
  });
  marcasPmAPI.obtenerConteosSubPMs.mockResolvedValue({
    data: { conteos: delegados ? [{ usuario_id: USUARIO_ID, total: delegados }] : [{ usuario_id: 99, total: 4 }] },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  api.post.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
  paresDe({ delegados: 3 });
});

describe('PermisosPorPantalla', () => {
  it('groups screens by sidebar section with accessible counts', async () => {
    renderPanel();
    const productos = await screen.findByRole('region', { name: 'Productos' });
    expect(within(productos).getByText(/de 6 accesibles/)).toBeInTheDocument();
    expect(within(productos).getByText('/productos', { selector: 'code' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Gestión' })).toBeInTheDocument();
  });

  it('shows SIN ACCESO and grants the missing permission via override', async () => {
    const user = userEvent.setup();
    const { onActualizado } = renderPanel();

    const admin = fila('/admin');
    expect(within(admin).getByText('Sin acceso')).toBeInTheDocument();
    expect(within(fila('/productos')).getByText('Accede')).toBeInTheDocument();

    await user.click(within(admin).getByRole('button', { name: 'Conceder acceso a Admin' }));

    expect(api.post).toHaveBeenCalledWith('/permisos/override', {
      usuario_id: USUARIO_ID,
      permiso_codigo: 'admin.ver_panel',
      concedido: true,
      motivo: 'Override desde panel de permisos',
    });
    await waitFor(() => expect(onActualizado).toHaveBeenCalled());
  });

  it('expands a screen to remove or reset its permissions', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(within(fila('/productos')).getByRole('button', { expanded: false }));
    await user.click(within(fila('/productos')).getByRole('button', { name: 'Quitar productos.ver' }));
    expect(api.post).toHaveBeenCalledWith('/permisos/override', expect.objectContaining({
      permiso_codigo: 'productos.ver',
      concedido: false,
    }));
  });

  it('resets an existing override', async () => {
    const user = userEvent.setup();
    const datos = payload();
    datos.permisos_detallados.consultas = [
      permiso('traza.ver', { override: true, efectivo: true, origen: 'override_agregado' }),
    ];
    renderPanel({ permisosUsuario: datos });

    await user.click(within(fila('/traza')).getByRole('button', { expanded: false }));
    await user.click(within(fila('/traza')).getByRole('button', { name: 'Resetear traza.ver' }));
    expect(api.delete).toHaveBeenCalledWith(`/permisos/override/${USUARIO_ID}/traza.ver`);
  });

  it('marks a data-scoped screen CONDICIONAL when the user has no marca/categoría pairs', async () => {
    paresDe({ titular: 0, delegados: 0 });
    renderPanel();

    const metricas = fila('/metricas-ml');
    expect(await within(metricas).findByText('Condicional')).toBeInTheDocument();
    expect(within(metricas).getByText(/no tiene pares marca\/categoría delegados/)).toBeInTheDocument();
    expect(within(metricas).getByRole('link', { name: /Mis Sub-PMs/ })).toHaveAttribute('href', '/mis-sub-pms');
  });

  it('is not CONDICIONAL when the user has pairs (delegated or as titular)', async () => {
    paresDe({ titular: 2, delegados: 0 });
    renderPanel();

    await flush();
    expect(within(fila('/metricas-ml')).getByText('Accede')).toBeInTheDocument();
    expect(screen.queryByText('Condicional')).not.toBeInTheDocument();
  });

  it('does not claim CONDICIONAL when the pair count cannot be loaded', async () => {
    marcasPmAPI.obtenerConteosSubPMs.mockRejectedValue(new Error('403'));
    marcasPmAPI.listarTodosLosPares.mockResolvedValue({ data: [] });
    renderPanel();

    await flush();
    expect(within(fila('/metricas-ml')).getByText('Accede')).toBeInTheDocument();
    expect(screen.queryByText('Condicional')).not.toBeInTheDocument();
  });

  it('filters rows with the search box', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByPlaceholderText(/Buscá una pantalla o permiso/), 'traza');
    expect(screen.getByText('/traza', { selector: 'code' })).toBeInTheDocument();
    expect(screen.queryByText('/productos', { selector: 'code' })).not.toBeInTheDocument();
  });

  it('filters rows with the "Sin acceso" chip', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole('button', { name: /^Sin acceso/ }));
    expect(screen.getByText('/admin', { selector: 'code' })).toBeInTheDocument();
    expect(screen.queryByText('/productos', { selector: 'code' })).not.toBeInTheDocument();
  });

  it('keeps permissions without a screen editable', async () => {
    renderPanel();
    const sueltos = screen.getByRole('region', { name: 'Permisos sin pantalla' });
    expect(within(sueltos).getByText('admin.sincronizar')).toBeInTheDocument();
    expect(within(sueltos).getByRole('button', { name: 'Conceder admin.sincronizar' })).toBeInTheDocument();
  });

  it('shows everything as accessible and no actions for a SUPERADMIN target', async () => {
    renderPanel({ permisosUsuario: payload('SUPERADMIN') });
    expect(within(fila('/admin')).getByText('Accede')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^(Conceder|Quitar|Resetear)/ })).not.toBeInTheDocument();
  });
});
