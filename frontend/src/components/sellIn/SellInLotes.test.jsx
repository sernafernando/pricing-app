/**
 * The sell-in lot viewer of a product (`GET /sell-in/productos/{id}/lotes`): its lots in the order the next sales take
 * them (FIFO), each with its status, units and unit discount; what the next sale gets; and, expanding a lot, the sales
 * that consumed it (`.../lotes/{compra_item_id}/consumos`, paginated). Owner: "podríamos tener un visualizador de
 * lotes? para saber como van a aplicar?".
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SellInLotes from './SellInLotes';
import { sellInLotesAPI } from '../../services/sellInAPI';

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { lotes: vi.fn(), consumos: vi.fn() },
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });

const lote = (overrides = {}) => ({
  numero: 1,
  compra_item_id: 501,
  compra_id: 41,
  proveedor: 'Gauss SA',
  facturas: ['A-0001-1'],
  moneda: 'ARS',
  fecha_desde: '2026-10-01',
  cantidad: 2,
  consumidas: 2,
  restantes: 0,
  descuento_unit: '100.000000',
  estado: 'agotado',
  ...overrides,
});

const LOTES = [
  lote(),
  lote({ numero: 2, compra_item_id: 502, compra_id: 42, fecha_desde: '2026-10-05', cantidad: 3, consumidas: 1, restantes: 2, descuento_unit: '33.333333', estado: 'vigente' }),
  lote({ numero: 3, compra_item_id: 503, compra_id: 43, proveedor: null, facturas: [], moneda: 'USD', fecha_desde: '2026-10-08', cantidad: 1, consumidas: 0, restantes: 1, descuento_unit: '10000.000000', estado: 'en_cola' }),
  lote({ numero: 4, compra_item_id: 504, compra_id: 44, fecha_desde: '2026-11-03', cantidad: 5, consumidas: 0, restantes: 5, descuento_unit: '10.000000', estado: 'desde' }),
];

const respuesta = (overrides = {}) => ({
  data: {
    item_id: 950,
    lotes: LOTES,
    proxima: {
      numero: 2,
      compra_item_id: 502,
      descuento_unit: '33.333333',
      restantes: 2,
      siguiente: { numero: 3, descuento_unit: '10000.000000', fecha_desde: '2026-10-08', estado: 'en_cola' },
    },
    bono_costo: null,
    ...overrides,
  },
});

const renderLotes = () => render(<SellInLotes productItemId={950} />);

beforeEach(() => {
  sellInLotesAPI.lotes.mockReset();
  sellInLotesAPI.consumos.mockReset();
  sellInLotesAPI.lotes.mockResolvedValue(respuesta());
});

describe('the lots', () => {
  it('come in FIFO order, each with its purchase, date, units and unit discount, and its status', async () => {
    renderLotes();
    const filas = await screen.findAllByRole('row');
    const datos = filas.slice(1).map((fila) => within(fila).getAllByRole('cell').map((celda) => celda.textContent));

    expect(sellInLotesAPI.lotes).toHaveBeenCalledWith(950);
    expect(datos.map((celdas) => celdas[0])).toEqual(['1', '2', '3', '4']);
    expect(datos.map((celdas) => celdas[1])).toEqual(['Agotado', 'Vigente', 'En cola', 'Desde 03/11']);
    expect(datos[0]).toEqual(expect.arrayContaining(['#41 · Gauss SA · A-0001-1', '01/10/2026', '2', '2', '0', '$ 100,00']));
    expect(datos[1]).toEqual(expect.arrayContaining(['$ 33,33', '3', '1', '2']));
    // A USD purchase's discount is already in ARS (its own rate); the currency is said.
    expect(datos[2]).toEqual(expect.arrayContaining(['#43 · Sin proveedor', '$ 10.000,00 (USD)']));
  });

  it('say what the next sale gets: the current lot, its units left at that value, then the next one', async () => {
    renderLotes();

    expect(
      await screen.findByText('La próxima venta descuenta $ 33,33 por unidad (lote 2); quedan 2 unidades a ese valor, después $ 10.000,00'),
    ).toBeInTheDocument();
  });

  it('with no next lot after the current one, the cost goes back to normal after it', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(
      respuesta({ proxima: { numero: 2, compra_item_id: 502, descuento_unit: '33.333333', restantes: 1, siguiente: null } }),
    );
    renderLotes();

    expect(
      await screen.findByText(
        'La próxima venta descuenta $ 33,33 por unidad (lote 2); queda 1 unidad a ese valor, después el costo vuelve al normal',
      ),
    ).toBeInTheDocument();
  });

  it('a future next lot says from when it counts', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(
      respuesta({
        proxima: {
          numero: 2,
          compra_item_id: 502,
          descuento_unit: '33.333333',
          restantes: 2,
          siguiente: { numero: 4, descuento_unit: '10.000000', fecha_desde: '2026-11-03', estado: 'desde' },
        },
      }),
    );
    renderLotes();

    expect(
      await screen.findByText(
        'La próxima venta descuenta $ 33,33 por unidad (lote 2); quedan 2 unidades a ese valor, después $ 10,00 (desde 03/11)',
      ),
    ).toBeInTheDocument();
  });
});

describe('with no lot left', () => {
  it('says the cost goes back to normal and that no cost bonus applies', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(respuesta({ lotes: [lote()], proxima: null }));
    renderLotes();

    expect(await screen.findByText('No quedan lotes con unidades: el costo vuelve al normal. Ningún bono de costo aplica.')).toBeInTheDocument();
  });

  it('names the cost bonus that applies instead, as Productos decides it', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(
      respuesta({ lotes: [lote()], proxima: null, bono_costo: { bono_ids: [7, 9], descuento_unit: 1500 } }),
    );
    renderLotes();

    expect(
      await screen.findByText(
        'No quedan lotes con unidades: el costo vuelve al normal. Aplica el bono de costo #7, #9: descuenta $ 1.500,00 por unidad.',
      ),
    ).toBeInTheDocument();
  });

  it('a product that never had a lot says so', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(respuesta({ lotes: [], proxima: null }));
    renderLotes();

    expect(await screen.findByText('Este producto no tiene lotes de sell in. Ningún bono de costo aplica.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});

describe('a lot expanded', () => {
  it('lists the sales that consumed it, paginated', async () => {
    const venta = (ref, fecha) => ({ canal: 'ml', venta_ref: ref, fecha_venta: fecha, unidades: 1, descuento_ars: '100.00' });
    sellInLotesAPI.consumos
      .mockResolvedValueOnce({ data: { items: [venta(11, '2026-10-02')], total: 2, page: 1, page_size: 20 } })
      .mockResolvedValueOnce({ data: { items: [venta(12, '2026-10-03')], total: 2, page: 2, page_size: 20 } });
    renderLotes();

    await userEvent.click(await screen.findByRole('button', { name: 'Ver ventas del lote 1' }));

    const ventas = await screen.findByRole('list', { name: 'Ventas del lote 1' });
    expect(sellInLotesAPI.consumos).toHaveBeenCalledWith(950, 501, { page: 1, page_size: 20 });
    expect(within(ventas).getByRole('listitem')).toHaveTextContent('ML · venta 11 · 02/10/2026 · 1 u. · $ 100,00');
    await userEvent.click(screen.getByRole('button', { name: 'Ver más ventas' }));
    expect(sellInLotesAPI.consumos).toHaveBeenLastCalledWith(950, 501, { page: 2, page_size: 20 });
    expect(await within(ventas).findByText(/venta 12/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ver más ventas' })).not.toBeInTheDocument();
  });

  it('a lot nothing consumed says so', async () => {
    sellInLotesAPI.consumos.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 20 } });
    renderLotes();

    await userEvent.click(await screen.findByRole('button', { name: 'Ver ventas del lote 3' }));

    expect(await screen.findByText('Ninguna venta consumió este lote todavía.')).toBeInTheDocument();
  });
});

describe('reading', () => {
  it('without the permission that shows the product, shows nothing', async () => {
    sellInLotesAPI.lotes.mockRejectedValue(httpError(403));
    const { container } = renderLotes();

    await vi.waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(sellInLotesAPI.lotes).toHaveBeenCalledWith(950);
  });

  it('a failed read can be retried', async () => {
    sellInLotesAPI.lotes.mockRejectedValueOnce(httpError(500));
    renderLotes();

    await userEvent.click(await screen.findByRole('button', { name: 'Reintentar' }));

    expect(await screen.findAllByRole('row')).toHaveLength(5);
  });
});
