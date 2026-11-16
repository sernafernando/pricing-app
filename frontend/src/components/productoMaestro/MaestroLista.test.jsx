/**
 * The product master's list (abm-productos T8, S5): Todos / Notebooks / PCs, "Specs incompletas", search and brand,
 * ordered by stock, with each notebook's and PC's specs completeness.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MaestroLista from './MaestroLista';
import { productoMaestroAPI, productoMarcasAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  productoMaestroAPI: { listar: vi.fn() },
  productoMarcasAPI: { listar: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const ITEMS = [
  { item_id: 455, codigo: '4897098683446', ean: '4897098683446', nombre: 'BLUETOOTH TPLINK NANO USB UB500 BT 5.0', marca: 'TP-LINK', stock: 964, tipo: null, specs_completos: null, specs_total: null },
  { item_id: 4874, codigo: '4711387', ean: '4711387', nombre: 'NB ASUS VIVOBOOK 15 R5 7520U 8GB 512GB', marca: 'ASUS', stock: 12, tipo: 'notebook', specs_completos: 9, specs_total: 17 },
];

const TOTALES = { todos: 4561, notebook: 671, pc: 133 };

beforeEach(() => {
  vi.clearAllMocks();
  productoMaestroAPI.listar.mockImplementation((params) =>
    Promise.resolve({ data: { total: TOTALES[params.tipo ?? 'todos'], items: params.limit === 1 ? [] : ITEMS } }),
  );
  productoMarcasAPI.listar.mockResolvedValue({
    data: [
      { id: 7, nombre: 'ASUS', activa: true, productos: 300 },
      { id: 12, nombre: 'TP-LINK', activa: true, productos: 520 },
      { id: 99, nombre: 'SIN USO', activa: true, productos: 0 },
      { id: 98, nombre: 'VIEJA', activa: false, productos: 4 },
    ],
  });
});

const lastParams = () => productoMaestroAPI.listar.mock.calls.filter(([p]) => p.limit !== 1).at(-1)[0];

describe('MaestroLista', () => {
  it('lists the products with stock and specs completeness, and the totals per tab', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<MaestroLista selectedId={455} onSelect={onSelect} />);

    expect(await screen.findByText('NB ASUS VIVOBOOK 15 R5 7520U 8GB 512GB')).toBeInTheDocument();
    expect(screen.getByText('item 4874 · 4711387')).toBeInTheDocument();
    expect(screen.getByText('9 / 17')).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: 'Notebooks 671' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Todos 4.561' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('2 de 4.561 · ordenado por stock')).toBeInTheDocument();

    await user.click(screen.getByText('NB ASUS VIVOBOOK 15 R5 7520U 8GB 512GB'));
    expect(onSelect).toHaveBeenCalledWith(4874);
  });

  it('filters by type, incomplete specs, text and brand', async () => {
    const user = userEvent.setup();
    render(<MaestroLista selectedId={null} onSelect={vi.fn()} />);
    await screen.findByText('NB ASUS VIVOBOOK 15 R5 7520U 8GB 512GB');

    await user.click(screen.getByRole('tab', { name: /PCs/ }));
    await waitFor(() => expect(lastParams()).toMatchObject({ tipo: 'pc', offset: 0 }));

    await user.click(screen.getByRole('checkbox', { name: 'Specs incompletas' }));
    await waitFor(() => expect(lastParams()).toMatchObject({ tipo: 'pc', incompletos: true }));

    await user.type(screen.getByRole('searchbox', { name: 'Buscar por nombre, EAN o código' }), 'vivobook');
    await waitFor(() => expect(lastParams()).toMatchObject({ q: 'vivobook' }));

    await user.selectOptions(screen.getByRole('combobox', { name: 'Marca' }), 'ASUS');
    await waitFor(() => expect(lastParams()).toMatchObject({ marca: 'ASUS' }));
  });

  it('offers only the active brands that have products', async () => {
    render(<MaestroLista selectedId={null} onSelect={vi.fn()} />);
    expect(await screen.findByRole('option', { name: 'TP-LINK' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'SIN USO' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'VIEJA' })).not.toBeInTheDocument();
  });

  it('"Ver más" brings the page after the loaded rows', async () => {
    const user = userEvent.setup();
    render(<MaestroLista selectedId={null} onSelect={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Ver más' }));
    await waitFor(() => expect(lastParams()).toMatchObject({ offset: 2, limit: 50 }));
  });
  it('the type tabs move with the arrow keys and control the list', async () => {
    const user = userEvent.setup();
    render(<MaestroLista selectedId={null} onSelect={vi.fn()} />);

    const todos = await screen.findByRole('tab', { name: /Todos/ });
    expect(screen.getByRole('tabpanel', { name: /Todos/ })).toHaveAttribute('id', todos.getAttribute('aria-controls'));
    todos.focus();
    await user.keyboard('{ArrowRight}');

    expect(screen.getByRole('tab', { name: /Notebooks/ })).toHaveFocus();
    expect(screen.getByRole('tab', { name: /Notebooks/ })).toHaveAttribute('aria-selected', 'true');
  });
});
