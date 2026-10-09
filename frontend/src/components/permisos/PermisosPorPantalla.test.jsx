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

// Viewer permissions: everything granted except the codes listed here, so a
// test can play a viewer who cannot manage permissions.
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

// Mirrors GET /marcas-pm (MarcaPMResponse): one row per (marca, categoria) with its titular.
function paresDe({ titular = 0, delegados = 0 } = {}) {
  marcasPmAPI.listarTodosLosPares.mockResolvedValue({
    data: [
      ...Array.from({ length: titular }, (_, i) => ({
        id: i + 1,
        marca: `MARCA${i}`,
        categoria: 'NOTEBOOKS',
        usuario_id: USUARIO_ID,
        usuario_nombre: 'Ana Pérez',
        usuario_email: 'ana@example.com',
      })),
      { id: 99, marca: 'OTRA', categoria: 'MONITORES', usuario_id: null, usuario_nombre: null, usuario_email: null },
    ],
  });
  marcasPmAPI.obtenerConteosSubPMs.mockResolvedValue({
    data: { conteos: delegados ? [{ usuario_id: USUARIO_ID, total: delegados }] : [{ usuario_id: 99, total: 4 }] },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  permisosDenegados.clear();
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
    expect(screen.queryByRole('button', { name: ACCION })).not.toBeInTheDocument();
  });

  describe('override failures', () => {
    it('shows the backend detail when the POST fails, skips the reload and re-enables the buttons', async () => {
      const user = userEvent.setup();
      api.post.mockRejectedValue({ response: { data: { detail: 'Permiso inexistente' } } });
      const { onActualizado, onMensaje } = renderPanel();

      const boton = within(fila('/admin')).getByRole('button', { name: 'Conceder acceso a Admin' });
      await user.click(boton);

      await waitFor(() => expect(onMensaje).toHaveBeenCalledWith({ tipo: 'error', texto: 'Permiso inexistente' }));
      expect(onActualizado).not.toHaveBeenCalled();
      expect(onMensaje).not.toHaveBeenCalledWith(expect.objectContaining({ tipo: 'success' }));
      expect(boton).toBeEnabled();
    });

    it('falls back to a generic message when the DELETE fails without detail', async () => {
      const user = userEvent.setup();
      api.delete.mockRejectedValue(new Error('Network Error'));
      const datos = payload();
      datos.permisos_detallados.consultas = [
        permiso('traza.ver', { override: true, efectivo: true, origen: 'override_agregado' }),
      ];
      const { onActualizado, onMensaje } = renderPanel({ permisosUsuario: datos });

      await user.click(within(fila('/traza')).getByRole('button', { expanded: false }));
      const boton = within(fila('/traza')).getByRole('button', { name: 'Resetear traza.ver' });
      await user.click(boton);

      await waitFor(() =>
        expect(onMensaje).toHaveBeenCalledWith({ tipo: 'error', texto: 'Error al resetear permiso' }),
      );
      expect(onActualizado).not.toHaveBeenCalled();
      expect(boton).toBeEnabled();
    });

    it('reports a saved-but-not-reloaded change, without a success message, when the reload fails', async () => {
      const user = userEvent.setup();
      const onActualizado = vi.fn().mockRejectedValue(new Error('500'));
      const { onMensaje } = renderPanel({ onActualizado });

      const boton = within(fila('/admin')).getByRole('button', { name: 'Conceder acceso a Admin' });
      await user.click(boton);

      await waitFor(() =>
        expect(onMensaje).toHaveBeenCalledWith({
          tipo: 'error',
          texto: 'El cambio se guardó, pero no se pudo recargar la lista de permisos',
        }),
      );
      expect(onMensaje).not.toHaveBeenCalledWith(expect.objectContaining({ tipo: 'success' }));
      expect(boton).toBeEnabled();
    });

    it('announces success only after the reload finished', async () => {
      const user = userEvent.setup();
      let terminarRecarga;
      const onActualizado = vi.fn(() => new Promise((resolve) => { terminarRecarga = resolve; }));
      const { onMensaje } = renderPanel({ onActualizado });

      await user.click(within(fila('/admin')).getByRole('button', { name: 'Conceder acceso a Admin' }));
      await waitFor(() => expect(onActualizado).toHaveBeenCalled());
      expect(onMensaje).not.toHaveBeenCalled();

      await act(async () => terminarRecarga());
      expect(onMensaje).toHaveBeenCalledWith({ tipo: 'success', texto: 'Permiso concedido' });
    });
  });

  describe('edit gate (admin.gestionar_permisos)', () => {
    it('hides every override action from a viewer without the permission', async () => {
      const user = userEvent.setup();
      permisosDenegados.add('admin.gestionar_permisos');
      renderPanel();

      await user.click(within(fila('/productos')).getByRole('button', { expanded: false }));
      expect(screen.queryByRole('button', { name: ACCION })).not.toBeInTheDocument();
      // The view itself is still there, read-only.
      expect(within(fila('/admin')).getByText('Sin acceso')).toBeInTheDocument();
    });

    it('shows the actions to a viewer with the permission', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(within(fila('/productos')).getByRole('button', { expanded: false }));
      expect(within(fila('/productos')).getByRole('button', { name: 'Quitar productos.ver' })).toBeInTheDocument();
      expect(within(fila('/admin')).getByRole('button', { name: 'Conceder acceso a Admin' })).toBeInTheDocument();
    });
  });

  describe('"Permisos sin pantalla" group', () => {
    const sueltos = () => screen.queryByRole('region', { name: 'Permisos sin pantalla' });
    // Rows on screen = screen rows + loose permission rows (none expanded).
    const filasVisibles = () => screen.getAllByRole('listitem').length;
    const conteoChip = (nombre) =>
      Number(screen.getByRole('button', { name: new RegExp(`^${nombre}`) }).textContent.match(/(\d+)$/)[1]);

    it('follows the active filter, and its rows count in the chip', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(screen.getByRole('button', { name: /^Sin acceso/ }));
      expect(within(sueltos()).getByText('admin.sincronizar')).toBeInTheDocument();
      expect(conteoChip('Sin acceso')).toBe(filasVisibles());
    });

    it('is hidden under "Depende de datos" by design: a loose permission has no data scope', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.click(screen.getByRole('button', { name: /^Depende de datos/ }));
      expect(sueltos()).not.toBeInTheDocument();
      expect(conteoChip('Depende de datos')).toBe(filasVisibles());
    });

    it('follows the search box', async () => {
      const user = userEvent.setup();
      renderPanel();

      await user.type(screen.getByPlaceholderText(/Buscá una pantalla o permiso/), 'sincronizar');
      expect(within(sueltos()).getByText('admin.sincronizar')).toBeInTheDocument();
      expect(screen.queryByText('/productos', { selector: 'code' })).not.toBeInTheDocument();
      expect(conteoChip('Todas')).toBe(filasVisibles());
    });
  });
});
