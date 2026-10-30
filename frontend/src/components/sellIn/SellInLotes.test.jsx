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
    compra_visible: true,
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
  it('come in FIFO order, each with its status, unit discount, units, the date it counts from and its purchase', async () => {
    renderLotes();
    const lista = await screen.findByRole('list', { name: 'Lotes en orden FIFO' });
    const lotes = [...lista.children].map((item) => item.textContent);

    expect(sellInLotesAPI.lotes).toHaveBeenCalledWith(950);
    expect(lotes).toHaveLength(4);
    expect(lotes[0]).toContain('Lote 1');
    expect(lotes[0]).toContain('Agotado');
    expect(lotes[0]).toContain('$ 100,00 por unidad');
    expect(lotes[0]).toContain('Quedan 0 de 2 · 2 usadas · desde 01/10/2026');
    expect(lotes[0]).toContain('#41 · Gauss SA · A-0001-1');
    expect(lotes[1]).toContain('Vigente');
    expect(lotes[1]).toContain('$ 33,33 por unidad');
    expect(lotes[1]).toContain('Quedan 2 de 3 · 1 usada');
    expect(lotes[2]).toContain('En cola');
    // A USD purchase's discount is already in ARS (its own rate); the currency is said.
    expect(lotes[2]).toContain('$ 10.000,00 por unidad (compra en USD)');
    expect(lotes[2]).toContain('#43 · Sin proveedor');
    expect(lotes[3]).toContain('Desde 03/11');
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

  it('with no next lot but a cost bonus, says the bonus applies after the current lot', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(
      respuesta({
        proxima: { numero: 2, compra_item_id: 502, descuento_unit: '33.333333', restantes: 2, siguiente: null },
        bono_costo: { bono_ids: [7], descuento_unit: 1500 },
      }),
    );
    renderLotes();

    expect(
      await screen.findByText(
        'La próxima venta descuenta $ 33,33 por unidad (lote 2); quedan 2 unidades a ese valor, después aplica el bono de costo #7: $ 1.500,00 por unidad',
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
        'La próxima venta descuenta $ 33,33 por unidad (lote 2); quedan 2 unidades a ese valor, después el costo vuelve al normal hasta el 03/11 y desde entonces $ 10,00',
      ),
    ).toBeInTheDocument();
  });
});

it('until a future next lot counts, names the cost bonus that applies in between', async () => {
  sellInLotesAPI.lotes.mockResolvedValue(
    respuesta({
      proxima: {
        numero: 2,
        compra_item_id: 502,
        descuento_unit: '33.333333',
        restantes: 2,
        siguiente: { numero: 4, descuento_unit: '10.000000', fecha_desde: '2026-11-03', estado: 'desde' },
      },
      bono_costo: { bono_ids: [7], descuento_unit: 1500 },
    }),
  );
  renderLotes();

  expect(
    await screen.findByText(
      'La próxima venta descuenta $ 33,33 por unidad (lote 2); quedan 2 unidades a ese valor, después aplica el bono de costo #7: $ 1.500,00 por unidad hasta el 03/11 y desde entonces $ 10,00',
    ),
  ).toBeInTheDocument();
});

it('without the purchases permission, a lot names only its purchase number, never "Sin proveedor"', async () => {
  sellInLotesAPI.lotes.mockResolvedValue(
    respuesta({ compra_visible: false, lotes: LOTES.map((x) => ({ ...x, proveedor: null, facturas: [] })) }),
  );
  renderLotes();
  const lista = await screen.findByRole('list', { name: 'Lotes en orden FIFO' });

  expect(lista.children[0]).toHaveTextContent('Compra #41');
  expect(lista).not.toHaveTextContent('Sin proveedor');
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

  it('with only a future lot left, says the cost is normal until that lot counts', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(respuesta({ lotes: [lote(), LOTES[3]], proxima: null }));
    renderLotes();

    expect(
      await screen.findByText(
        'Ningún lote tiene unidades hoy: el costo vuelve al normal hasta el 03/11 (lote 4, $ 10,00 por unidad). Ningún bono de costo aplica.',
      ),
    ).toBeInTheDocument();
  });

  it('a product that never had a lot says so', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(respuesta({ lotes: [], proxima: null }));
    renderLotes();

    expect(await screen.findByText('Este producto no tiene lotes de sell in. Ningún bono de costo aplica.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Lotes en orden FIFO' })).not.toBeInTheDocument();
  });
});

describe('a lot expanded', () => {
  it('lists the sales that consumed it, paginated', async () => {
    const venta = (ref, fecha) => ({ canal: 'ml', venta_ref: ref, fecha_venta: fecha, unidades: 1, descuento_ars: '100.00' });
    let segunda;
    sellInLotesAPI.consumos
      .mockResolvedValueOnce({ data: { items: [venta(11, '2026-10-02')], total: 2, page: 1, page_size: 20 } })
      .mockReturnValueOnce(new Promise((resolve) => (segunda = resolve)));
    renderLotes();

    await userEvent.click(await screen.findByRole('button', { name: 'Ver ventas del lote 1' }));

    const ventas = await screen.findByRole('list', { name: 'Ventas del lote 1' });
    expect(sellInLotesAPI.consumos).toHaveBeenCalledWith(950, 501, { page: 1, page_size: 20 });
    expect(within(ventas).getByRole('listitem')).toHaveTextContent('ML · venta 11 · 02/10/2026 · 1 u. · $ 100,00');
    await userEvent.click(screen.getByRole('button', { name: 'Ver más ventas' }));
    expect(sellInLotesAPI.consumos).toHaveBeenLastCalledWith(950, 501, { page: 2, page_size: 20 });
    // While the next page loads, the button says so and cannot be pressed again.
    expect(screen.getByRole('button', { name: 'Cargando ventas…' })).toBeDisabled();
    segunda({ data: { items: [venta(12, '2026-10-03')], total: 2, page: 2, page_size: 20 } });
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

    const lista = await screen.findByRole('list', { name: 'Lotes en orden FIFO' });
    expect(lista.children).toHaveLength(4);
  });
});
