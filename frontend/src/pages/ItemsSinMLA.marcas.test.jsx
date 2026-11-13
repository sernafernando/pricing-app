/**
 * marcas-sin-stock S4: the "Sin MLA" brand filter offers only the row brands that `GET /items-sin-mla/marcas`
 * (visibility-filtered on the server) lists; if that list fails, it falls back to the row brands.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import ItemsSinMLA from './ItemsSinMLA';
import api from '../services/api';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const fila = (item_id, marca) => ({
  item_id,
  codigo: `C${item_id}`,
  descripcion: `Producto ${item_id}`,
  marca,
  stock: 0,
  listas_sin_mla: [],
  listas_con_mla: [],
});

const FILAS = [fila(1, 'CON STOCK'), fila(2, 'OCULTA'), fila(3, 'EXCEPCION')];

function mockApi({ marcas }) {
  api.get.mockImplementation((url) => {
    if (url === '/items-sin-mla/items-sin-mla') return Promise.resolve({ data: FILAS });
    if (url === '/items-sin-mla/marcas') return marcas();
    return Promise.resolve({ data: [] });
  });
}

async function marcasOfrecidas() {
  const user = userEvent.setup();
  const { container } = await renderWithRouter(<ItemsSinMLA />);
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/items-sin-mla/items-sin-mla', expect.anything()));
  await user.click(await screen.findByRole('button', { name: /Todas las marcas/i }));
  const lista = container.querySelector('.dropdown-list');
  return () => within(lista).queryAllByRole('checkbox').map((checkbox) => checkbox.closest('label').textContent.trim());
}

beforeEach(() => {
  api.get.mockReset();
});

describe('ItemsSinMLA brand filter', () => {
  it('offers only the brands the server lists as visible', async () => {
    mockApi({ marcas: () => Promise.resolve({ data: [{ marca: 'CON STOCK' }, { marca: 'EXCEPCION' }] }) });
    const leer = await marcasOfrecidas();

    await waitFor(() => expect(leer()).toEqual(['CON STOCK', 'EXCEPCION']));
  });

  it('falls back to the row brands when the visible brand list fails to load', async () => {
    mockApi({ marcas: () => Promise.reject(new Error('boom')) });
    const leer = await marcasOfrecidas();

    await waitFor(() => expect(leer()).toEqual(['CON STOCK', 'EXCEPCION', 'OCULTA']));
  });
});
