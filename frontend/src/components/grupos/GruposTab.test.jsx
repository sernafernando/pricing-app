import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../../test/renderWithRouter';
import { productosAPI } from '../../services/api';
import { offsetGruposAPI } from '../../services/offsetGruposAPI';
import GruposTab from './GruposTab';

vi.mock('../../services/offsetGruposAPI', () => ({
  offsetGruposAPI: {
    listar: vi.fn(),
    alcance: vi.fn(),
    opciones: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    eliminar: vi.fn(),
    agregarFiltro: vi.fn(),
    eliminarFiltro: vi.fn(),
  },
}));

const TPLINK = {
  id: 1,
  nombre: 'TP-Link redes',
  descripcion: 'Routers y switches',
  filtros: [
    { id: 11, grupo_id: 1, marca: 'TP-LINK', categoria: 'Routers', subcategoria_id: null, item_id: null, producto_descripcion: null },
    { id: 12, grupo_id: 1, marca: null, categoria: null, subcategoria_id: 7, item_id: null, producto_descripcion: null },
  ],
};
const VACIO = { id: 2, nombre: 'Sin filtros', descripcion: null, filtros: [] };
const ALCANCE = [
  {
    grupo_id: 1,
    productos: 42,
    campanas: [
      { id: 5, nombre: 'Noviembre TP-Link', estado: 'activa' },
      { id: 6, nombre: 'Octubre TP-Link', estado: 'anulada' },
    ],
  },
  { grupo_id: 2, productos: 0, campanas: [] },
];
const OPCIONES = {
  marcas: ['MERCUSYS', 'TP-LINK'],
  categorias: ['Routers', 'Switches'],
  subcategorias: [{ id: 7, nombre: 'Wi-Fi 6' }],
};
const RECHAZO = 'El grupo está asignado a la campaña de sell out activa «Noviembre TP-Link». Quite el grupo de la campaña antes de eliminarlo.';

beforeEach(() => {
  vi.clearAllMocks();
  offsetGruposAPI.listar.mockResolvedValue({ data: [TPLINK, VACIO] });
  offsetGruposAPI.alcance.mockResolvedValue({ data: ALCANCE });
  offsetGruposAPI.opciones.mockResolvedValue({ data: OPCIONES });
});

const fila = async (nombre) => (await screen.findByText(nombre)).closest('tr');

async function abrir(user, nombre) {
  await user.click(within(await fila(nombre)).getByRole('button', { name: 'Editar' }));
  return screen.getByRole('complementary', { name: 'Grupo' });
}

describe('GruposTab — list', () => {
  it('lists each group with its description, filters, products reached and the campaigns using it', async () => {
    renderWithRouter(<GruposTab />);
    const tplink = await fila('TP-Link redes');
    expect(within(tplink).getByText('Routers y switches')).toBeInTheDocument();
    expect(within(tplink).getByText('Marca TP-LINK · Categoría Routers')).toBeInTheDocument();
    expect(within(tplink).getByText('Subcategoría Wi-Fi 6')).toBeInTheDocument();
    expect(within(tplink).getByText('42')).toBeInTheDocument();
    expect(within(tplink).getByText('Noviembre TP-Link')).toBeInTheDocument();
    expect(within(tplink).getByText('1 anulada')).toBeInTheDocument();
    const vacio = await fila('Sin filtros');
    expect(within(vacio).getByText('Sin filtros: no alcanza productos')).toBeInTheDocument();
    expect(within(vacio).getByText('Ninguna')).toBeInTheDocument();
  });

  it('says it is loading while the groups and their reach are asked, and never together with the error', async () => {
    let responder;
    offsetGruposAPI.alcance.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    renderWithRouter(<GruposTab />);
    expect(screen.getByText('Cargando grupos…')).toBeInTheDocument();
    responder({ data: ALCANCE });
    expect(await screen.findByText('TP-Link redes')).toBeInTheDocument();
    expect(screen.queryByText('Cargando grupos…')).not.toBeInTheDocument();
  });

  it('a failed load shows the error without the loading text', async () => {
    offsetGruposAPI.alcance.mockRejectedValue(new Error('500'));
    renderWithRouter(<GruposTab />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los grupos.');
    expect(screen.queryByText('Cargando grupos…')).not.toBeInTheDocument();
  });

  it('a new version asks the groups again and keeps the open panel', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<GruposTab version={0} />);
    await abrir(user, 'TP-Link redes');
    rerender(<GruposTab version={1} />);
    await waitFor(() => expect(offsetGruposAPI.listar).toHaveBeenCalledTimes(2));
    expect(offsetGruposAPI.alcance).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('complementary', { name: 'Grupo' })).toBeInTheDocument();
  });

  it('a reload without the open group (someone deleted it) closes the panel', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<GruposTab version={0} />);
    await abrir(user, 'TP-Link redes');
    offsetGruposAPI.listar.mockResolvedValue({ data: [VACIO] });
    rerender(<GruposTab version={1} />);
    await waitFor(() => expect(screen.queryByText('TP-Link redes')).not.toBeInTheDocument());
    expect(screen.queryByRole('complementary', { name: 'Grupo' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Crear grupo' })).not.toBeInTheDocument();
  });

  it('when the filter options fail it says so, and the next reload asks them again', async () => {
    offsetGruposAPI.opciones.mockRejectedValueOnce(new Error('500'));
    const { rerender } = render(<GruposTab version={0} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar las marcas, categorías y subcategorías');
    expect(screen.getByText('TP-Link redes')).toBeInTheDocument();
    rerender(<GruposTab version={1} />);
    await waitFor(() => expect(offsetGruposAPI.opciones).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Subcategoría Wi-Fi 6')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says so when the groups cannot be read', async () => {
    offsetGruposAPI.listar.mockRejectedValue(new Error('500'));
    renderWithRouter(<GruposTab />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los grupos.');
  });

  it('warns that changing a group changes which products its campaigns reach', async () => {
    renderWithRouter(<GruposTab />);
    await fila('TP-Link redes');
    expect(screen.getByText(/Cambiar un grupo cambia los productos que alcanzan las campañas de sell out que lo usan/)).toBeInTheDocument();
  });
});

describe('GruposTab — create, rename, delete', () => {
  it('"Nuevo grupo" creates it, opens it in the side panel and reloads the list', async () => {
    const user = userEvent.setup();
    const NUEVO = { id: 3, nombre: 'Mercusys', descripcion: null, filtros: [] };
    offsetGruposAPI.crear.mockResolvedValue({ data: NUEVO });
    renderWithRouter(<GruposTab />);
    await fila('TP-Link redes');
    await user.click(screen.getByRole('button', { name: 'Nuevo grupo' }));
    const panel = screen.getByRole('complementary', { name: 'Grupo' });
    offsetGruposAPI.listar.mockResolvedValue({ data: [TPLINK, VACIO, NUEVO] });
    await user.type(within(panel).getByLabelText('Nombre'), 'Mercusys');
    await user.click(within(panel).getByRole('button', { name: 'Crear grupo' }));
    expect(offsetGruposAPI.crear).toHaveBeenCalledWith({ nombre: 'Mercusys', descripcion: null, filtros: [] });
    expect(await within(panel).findByRole('heading', { name: 'Mercusys' })).toBeInTheDocument();
    expect(offsetGruposAPI.listar).toHaveBeenCalledTimes(2);
  });

  it('renames and describes a group', async () => {
    const user = userEvent.setup();
    offsetGruposAPI.editar.mockResolvedValue({ data: { id: 1, nombre: 'Redes TP-Link', descripcion: 'Todo TP-Link' } });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    const nombre = within(panel).getByLabelText('Nombre');
    await user.clear(nombre);
    await user.type(nombre, 'Redes TP-Link');
    const descripcion = within(panel).getByLabelText('Descripción');
    await user.clear(descripcion);
    await user.type(descripcion, 'Todo TP-Link');
    await user.click(within(panel).getByRole('button', { name: 'Guardar nombre' }));
    expect(offsetGruposAPI.editar).toHaveBeenCalledWith(1, { nombre: 'Redes TP-Link', descripcion: 'Todo TP-Link' });
    await waitFor(() => expect(offsetGruposAPI.listar).toHaveBeenCalledTimes(2));
  });

  it('deleting a group used by an active campaign shows the refusal and keeps the group', async () => {
    const user = userEvent.setup();
    offsetGruposAPI.eliminar.mockRejectedValue({ response: { status: 400, data: { error: { message: RECHAZO } } } });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    await user.click(within(panel).getByRole('button', { name: 'Eliminar grupo' }));
    await user.click(within(panel).getByRole('button', { name: 'Confirmar eliminación' }));
    expect(offsetGruposAPI.eliminar).toHaveBeenCalledWith(1);
    expect(await within(panel).findByRole('alert')).toHaveTextContent(RECHAZO);
    expect(screen.getByRole('complementary', { name: 'Grupo' })).toBeInTheDocument();
  });

  it('deleting a group closes the panel and reloads the list', async () => {
    const user = userEvent.setup();
    offsetGruposAPI.eliminar.mockResolvedValue({ data: { mensaje: 'Grupo eliminado' } });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'Sin filtros');
    offsetGruposAPI.listar.mockResolvedValue({ data: [TPLINK] });
    await user.click(within(panel).getByRole('button', { name: 'Eliminar grupo' }));
    await user.click(within(panel).getByRole('button', { name: 'Confirmar eliminación' }));
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Grupo' })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText('Sin filtros')).not.toBeInTheDocument());
  });
});

describe('GruposTab — filters and preview', () => {
  it('the panel shows the products reached and the campaigns using the group', async () => {
    const user = userEvent.setup();
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    expect(within(panel).getByText('Alcanza 42 productos.')).toBeInTheDocument();
    expect(within(panel).getByText('Noviembre TP-Link')).toBeInTheDocument();
    expect(within(panel).getByText(/Cambiar un grupo cambia los productos que alcanzan/)).toBeInTheDocument();
  });

  it('adds a filter row with brand and category, then the preview refreshes', async () => {
    const user = userEvent.setup();
    offsetGruposAPI.agregarFiltro.mockResolvedValue({ data: { id: 13 } });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    expect(within(panel).getByRole('button', { name: 'Agregar filtro' })).toBeDisabled();
    await user.selectOptions(within(panel).getByLabelText('Marca'), 'MERCUSYS');
    await user.selectOptions(within(panel).getByLabelText('Categoría'), 'Switches');
    offsetGruposAPI.alcance.mockResolvedValue({ data: [{ ...ALCANCE[0], productos: 50 }, ALCANCE[1]] });
    await user.click(within(panel).getByRole('button', { name: 'Agregar filtro' }));
    expect(offsetGruposAPI.agregarFiltro).toHaveBeenCalledWith(1, { marca: 'MERCUSYS', categoria: 'Switches', subcategoria_id: null, item_id: null });
    expect(await within(panel).findByText('Alcanza 50 productos.')).toBeInTheDocument();
    expect(offsetGruposAPI.alcance).toHaveBeenCalledTimes(2);
  });

  it('adds a filter by product with the catalog search', async () => {
    const user = userEvent.setup();
    productosAPI.listar.mockResolvedValue({ data: { productos: [{ item_id: 2964, codigo: 'ARCHER', descripcion: 'Archer C6', marca: 'TP-LINK' }] } });
    offsetGruposAPI.agregarFiltro.mockResolvedValue({ data: { id: 13 } });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    await user.type(within(panel).getByPlaceholderText('Buscar producto por código o descripción…'), 'archer');
    await user.click(await within(panel).findByRole('button', { name: /ARCHER · Archer C6/ }));
    expect(within(panel).getByText('Producto: ARCHER · Archer C6')).toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: 'Agregar filtro' }));
    expect(offsetGruposAPI.agregarFiltro).toHaveBeenCalledWith(1, { marca: null, categoria: null, subcategoria_id: null, item_id: 2964 });
  });

  it('removes a filter row, then the preview refreshes', async () => {
    const user = userEvent.setup();
    offsetGruposAPI.eliminarFiltro.mockResolvedValue({ data: {} });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    offsetGruposAPI.alcance.mockResolvedValue({ data: [{ ...ALCANCE[0], productos: 30 }, ALCANCE[1]] });
    await user.click(within(panel).getByRole('button', { name: 'Quitar Subcategoría Wi-Fi 6' }));
    expect(offsetGruposAPI.eliminarFiltro).toHaveBeenCalledWith(1, 12);
    expect(await within(panel).findByText('Alcanza 30 productos.')).toBeInTheDocument();
  });

  it('after a filter change the panel stays busy until the list and the preview come back', async () => {
    const user = userEvent.setup();
    offsetGruposAPI.eliminarFiltro.mockResolvedValue({ data: {} });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    let responder;
    offsetGruposAPI.alcance.mockReturnValue(new Promise((r) => (responder = r)));
    await user.click(within(panel).getByRole('button', { name: 'Quitar Subcategoría Wi-Fi 6' }));
    await waitFor(() => expect(offsetGruposAPI.alcance).toHaveBeenCalledTimes(2));
    expect(within(panel).getByRole('button', { name: 'Quitar Marca TP-LINK · Categoría Routers' })).toBeDisabled();
    responder({ data: [{ ...ALCANCE[0], productos: 30 }, ALCANCE[1]] });
    expect(await within(panel).findByText('Alcanza 30 productos.')).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Quitar Marca TP-LINK · Categoría Routers' })).toBeEnabled();
  });

  it('a failed filter change says so', async () => {
    const user = userEvent.setup();
    offsetGruposAPI.eliminarFiltro.mockRejectedValue({ response: { data: { error: { message: 'Filtro no encontrado' } } } });
    renderWithRouter(<GruposTab />);
    const panel = await abrir(user, 'TP-Link redes');
    await user.click(within(panel).getByRole('button', { name: 'Quitar Subcategoría Wi-Fi 6' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Filtro no encontrado');
  });
});
