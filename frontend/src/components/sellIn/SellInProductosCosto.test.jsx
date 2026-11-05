/**
 * Sell in's Productos list (`GET /sell-in/productos/costos`): one row per product with units left in its lots, with
 * its "Modo de costo" (FIFO by default), units, the next sale's sell in per unit and its latest purchase, read in one
 * request for the whole list; a row opens the product's lots and cost mode.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SellInProductosCosto from './SellInProductosCosto';
import { sellInLotesAPI } from '../../services/sellInAPI';

vi.mock('../../services/sellInAPI', () => ({ sellInLotesAPI: { productos: vi.fn() } }));

const fila = (overrides = {}) => ({
  item_id: 4512,
  codigo: 'TPL-AX55',
  descripcion: 'Router TP-Link Archer AX55',
  modo: null,
  unidades: 200,
  sell_in_unit: '5472.000000',
  ultima_compra: '2026-11-02',
  ...overrides,
});

const PRODUCTOS = [
  fila(),
  fila({ item_id: 4513, codigo: 'TPL-EAP225', descripcion: 'Access Point TP-Link EAP225', modo: 'ponderado', unidades: 312 }),
  fila({ item_id: 4514, codigo: 'TPL-SG1016D', descripcion: 'Switch TP-Link SG1016D', modo: 'ultimo', unidades: 57, sell_in_unit: null }),
];

describe('SellInProductosCosto', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sellInLotesAPI.productos.mockResolvedValue({ data: { productos: PRODUCTOS } });
  });

  it('shows each product with its cost mode, units, sell in per unit and latest purchase, from one request', async () => {
    render(<SellInProductosCosto onVer={vi.fn()} />);

    const tabla = await screen.findByRole('table', { name: 'Productos con lotes de sell in' });
    const filas = within(tabla).getAllByRole('row').slice(1);
    expect(filas.map((x) => within(x).getAllByRole('cell').map((c) => c.textContent))).toEqual([
      ['Router TP-Link Archer AX55TPL-AX55', 'FIFO (por defecto)', '200 u', '$ 5.472,00', '02/11/2026'],
      ['Access Point TP-Link EAP225TPL-EAP225', 'Ponderado (PPP)', '312 u', '$ 5.472,00', '02/11/2026'],
      ['Switch TP-Link SG1016DTPL-SG1016D', 'Último precio', '57 u', '—', '02/11/2026'],
    ]);
    expect(within(tabla).getAllByRole('columnheader').map((x) => x.textContent)).toEqual([
      'Producto',
      'Modo de costo',
      'Unidades',
      'Sell in por unidad',
      'Últ. compra',
    ]);
    expect(screen.getByText('569 u')).toBeInTheDocument();
    expect(sellInLotesAPI.productos).toHaveBeenCalledTimes(1);
  });

  it('opens a product from its row', async () => {
    const onVer = vi.fn();
    render(<SellInProductosCosto onVer={onVer} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Ver lotes y modo de costo de Switch TP-Link SG1016D' }));

    expect(onVer).toHaveBeenCalledWith(PRODUCTOS[2]);
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
