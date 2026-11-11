/**
 * Sell in's Productos list (`GET /sell-in/productos/costos`): one row per product with units left in its lots, with
 * its "Modo de costo" (FIFO by default), units, the next sale's sell in per unit and its latest purchase, read in one
 * request for the whole list. Owner, 2026-11-10: "No tengo botones, filtros, nada, cómo lo uso?" / "no tengo el modal
 * para setear el fifo, ppp, o ultimo ingreso como default": a toolbar with the default mode, search, Marca and Modo
 * filters (client side: the endpoint already reads the whole list), sortable columns and a visible "Ver lotes".
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SellInProductosCosto from './SellInProductosCosto';
import { sellInLotesAPI } from '../../services/sellInAPI';

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { productos: vi.fn(), modoPorDefecto: vi.fn(), fijarModoPorDefecto: vi.fn() },
}));

let rol = 'VENTAS';
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true, rol }),
}));

const fila = (overrides = {}) => ({
  item_id: 4512,
  codigo: 'TPL-AX55',
  descripcion: 'Router TP-Link Archer AX55',
  marca: 'TP-LINK',
  modo: null,
  unidades: 200,
  sell_in_unit: '5472.000000',
  ultima_compra: '2026-11-02',
  ...overrides,
});

const PRODUCTOS = [
  fila(),
  fila({
    item_id: 4513,
    codigo: 'TPL-EAP225',
    descripcion: 'Access Point TP-Link EAP225',
    modo: 'ponderado',
    unidades: 312,
    sell_in_unit: '1200.000000',
    ultima_compra: '2026-10-15',
  }),
  fila({
    item_id: 4514,
    codigo: 'MER-MS108',
    descripcion: 'Switch Mercusys MS108',
    marca: 'MERCUSYS',
    modo: 'ultimo',
    unidades: 57,
    sell_in_unit: null,
    ultima_compra: '2026-11-05',
  }),
];

const tabla = () => screen.findByRole('table', { name: 'Productos con lotes de sell in' });
const nombres = (t) => within(t).getAllByRole('row').slice(1).map((x) => within(x).getAllByRole('cell')[0].textContent);

describe('SellInProductosCosto', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rol = 'VENTAS';
    sellInLotesAPI.productos.mockResolvedValue({ data: { productos: PRODUCTOS } });
    sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'fifo' } });
    sellInLotesAPI.fijarModoPorDefecto.mockImplementation((modo) => Promise.resolve({ data: { modo } }));
  });

  it('shows each product with its cost mode, units, sell in per unit and latest purchase, from one request', async () => {
    render(<SellInProductosCosto onVer={vi.fn()} />);

    const t = await tabla();
    const filas = within(t).getAllByRole('row').slice(1);
    expect(filas.map((x) => within(x).getAllByRole('cell').map((c) => c.textContent))).toEqual([
      ['Router TP-Link Archer AX55TPL-AX55', 'FIFO (por defecto)', '200 u', '$ 5.472,00', '02/11/2026', 'Ver lotes'],
      ['Access Point TP-Link EAP225TPL-EAP225', 'Ponderado (PPP)', '312 u', '$ 1.200,00', '15/10/2026', 'Ver lotes'],
      ['Switch Mercusys MS108MER-MS108', 'Último precio', '57 u', '—', '05/11/2026', 'Ver lotes'],
    ]);
    expect(within(t).getAllByRole('columnheader').map((x) => x.textContent)).toEqual([
      'Producto',
      'Modo de costo',
      'Unidades',
      'Sell in por unidad',
      'Últ. compra',
      'Acciones',
    ]);
    expect(screen.getByText('569 u')).toBeInTheDocument();
    expect(sellInLotesAPI.productos).toHaveBeenCalledTimes(1);
  });

  it('opens a product from its visible "Ver lotes" action', async () => {
    const onVer = vi.fn();
    render(<SellInProductosCosto onVer={onVer} />);

    const boton = await screen.findByRole('button', { name: 'Ver lotes y modo de costo de Switch Mercusys MS108' });
    expect(boton).toHaveTextContent('Ver lotes');
    await userEvent.click(boton);

    expect(onVer).toHaveBeenCalledWith(PRODUCTOS[2]);
  });

  describe('the toolbar', () => {
    it('searches by código or descripción, ignoring case and accents', async () => {
      const user = userEvent.setup();
      render(<SellInProductosCosto onVer={vi.fn()} />);
      const t = await tabla();

      await user.type(screen.getByPlaceholderText('Buscar por código o descripción'), 'mer-ms');
      await waitFor(() => expect(nombres(t)).toEqual(['Switch Mercusys MS108MER-MS108']));

      await user.clear(screen.getByPlaceholderText('Buscar por código o descripción'));
      await user.type(screen.getByPlaceholderText('Buscar por código o descripción'), 'ACCESS POÍNT');
      await waitFor(() => expect(nombres(t)).toEqual(['Access Point TP-Link EAP225TPL-EAP225']));
      expect(screen.getByText('312 u', { selector: 'div' })).toBeInTheDocument();
    });

    it('filters by marca, offering the brands in the list', async () => {
      const user = userEvent.setup();
      render(<SellInProductosCosto onVer={vi.fn()} />);
      const t = await tabla();
      const marca = screen.getByRole('combobox', { name: 'Marca' });

      expect(within(marca).getAllByRole('option').map((x) => x.textContent)).toEqual(['Todas', 'MERCUSYS', 'TP-LINK']);
      await user.selectOptions(marca, 'TP-LINK');

      expect(nombres(t)).toEqual(['Router TP-Link Archer AX55TPL-AX55', 'Access Point TP-Link EAP225TPL-EAP225']);
    });

    it('filters by modo de costo, "FIFO (por defecto)" being the products without a mode of their own', async () => {
      const user = userEvent.setup();
      const cable = fila({ item_id: 9, codigo: 'X-1', descripcion: 'Cable', modo: 'fifo' });
      sellInLotesAPI.productos.mockResolvedValue({ data: { productos: [...PRODUCTOS, cable] } });
      render(<SellInProductosCosto onVer={vi.fn()} />);
      const t = await tabla();
      const modo = screen.getByRole('combobox', { name: 'Modo de costo' });

      expect(within(modo).getAllByRole('option').map((x) => x.textContent)).toEqual([
        'Todos',
        'FIFO (por defecto)',
        'FIFO',
        'Ponderado (PPP)',
        'Último precio',
        'Manual',
      ]);
      await user.selectOptions(modo, 'FIFO (por defecto)');
      expect(nombres(t)).toEqual(['Router TP-Link Archer AX55TPL-AX55']);

      await user.selectOptions(modo, 'FIFO');
      expect(nombres(t)).toEqual(['CableX-1']);

      await user.selectOptions(modo, 'Ponderado (PPP)');
      expect(nombres(t)).toEqual(['Access Point TP-Link EAP225TPL-EAP225']);
    });

    it('says when nothing matches and "Limpiar filtros" brings every product back', async () => {
      const user = userEvent.setup();
      render(<SellInProductosCosto onVer={vi.fn()} />);
      await tabla();

      await user.selectOptions(screen.getByRole('combobox', { name: 'Marca' }), 'MERCUSYS');
      await user.selectOptions(screen.getByRole('combobox', { name: 'Modo de costo' }), 'Ponderado (PPP)');
      expect(screen.getByText('Ningún producto coincide con los filtros.')).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: 'Limpiar filtros' }));
      expect(nombres(await tabla())).toHaveLength(3);
    });
  });

  describe('sorting', () => {
    it.each([
      ['Producto', ['Access Point', 'Router', 'Switch'], ['Switch', 'Router', 'Access Point']],
      ['Modo de costo', ['Router', 'Access Point', 'Switch'], ['Switch', 'Access Point', 'Router']],
      ['Unidades', ['Switch', 'Router', 'Access Point'], ['Access Point', 'Router', 'Switch']],
      ['Sell in por unidad', ['Access Point', 'Router', 'Switch'], ['Router', 'Access Point', 'Switch']],
      ['Últ. compra', ['Access Point', 'Router', 'Switch'], ['Switch', 'Router', 'Access Point']],
    ])('sorts by %s, ascending then descending (no sell in last)', async (columna, asc, desc) => {
      const user = userEvent.setup();
      render(<SellInProductosCosto onVer={vi.fn()} />);
      const t = await tabla();
      const primeras = () => nombres(t).map((x) => x.split(' ').slice(0, x.startsWith('Access') ? 2 : 1).join(' '));

      await user.click(within(t).getByRole('button', { name: columna }));
      expect(primeras()).toEqual(asc);
      expect(within(t).getByRole('columnheader', { name: columna })).toHaveAttribute('aria-sort', 'ascending');

      await user.click(within(t).getByRole('button', { name: columna }));
      expect(primeras()).toEqual(desc);
      expect(within(t).getByRole('columnheader', { name: columna })).toHaveAttribute('aria-sort', 'descending');
    });
  });

  describe('the default mode', () => {
    it('shows the current default to everyone, without "Cambiar" for a non-admin', async () => {
      sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'ponderado' } });
      render(<SellInProductosCosto onVer={vi.fn()} />);

      expect(await screen.findByText('Ponderado (PPP)', { selector: 'strong' })).toBeInTheDocument();
      expect(screen.getByText('Modo por defecto:')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Cambiar modo por defecto' })).not.toBeInTheDocument();
    });

    it.each(['ADMIN', 'SUPERADMIN'])('lets an %s change it in the modal, and the toolbar shows the new one', async (r) => {
      rol = r;
      const user = userEvent.setup();
      render(<SellInProductosCosto onVer={vi.fn()} />);
      await screen.findByText('FIFO', { selector: 'strong' });

      await user.click(screen.getByRole('button', { name: 'Cambiar modo por defecto' }));
      expect(await screen.findByRole('heading', { name: 'Modo por defecto' })).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Último precio' }));
      await user.click(screen.getByRole('button', { name: 'Guardar' }));

      expect(sellInLotesAPI.fijarModoPorDefecto).toHaveBeenCalledWith('ultimo');
      expect(await screen.findByText('Último precio', { selector: 'strong' })).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Modo por defecto' })).not.toBeInTheDocument();
    });

    it('hides the default when it cannot be read, and the list still works', async () => {
      rol = 'ADMIN';
      sellInLotesAPI.modoPorDefecto.mockRejectedValue(new Error('HTTP 500'));
      render(<SellInProductosCosto onVer={vi.fn()} />);

      await tabla();
      await waitFor(() => expect(sellInLotesAPI.modoPorDefecto).toHaveBeenCalled());
      expect(screen.queryByText('Modo por defecto:')).not.toBeInTheDocument();
    });
  });

  it('reads the list again when its version changes', async () => {
    const { rerender } = render(<SellInProductosCosto onVer={vi.fn()} version={0} />);
    await screen.findByRole('table');

    rerender(<SellInProductosCosto onVer={vi.fn()} version={1} />);

    await vi.waitFor(() => expect(sellInLotesAPI.productos).toHaveBeenCalledTimes(2));
  });

  it('says so when no product has units in its lots', async () => {
    sellInLotesAPI.productos.mockResolvedValue({ data: { productos: [] } });
    render(<SellInProductosCosto onVer={vi.fn()} />);

    expect(await screen.findByText('Ningún producto tiene unidades en lotes de sell in.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('offers a retry when the list fails', async () => {
    sellInLotesAPI.productos.mockRejectedValueOnce(new Error('HTTP 500'));
    render(<SellInProductosCosto onVer={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los productos.');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findByRole('table')).toBeInTheDocument();
  });
});
