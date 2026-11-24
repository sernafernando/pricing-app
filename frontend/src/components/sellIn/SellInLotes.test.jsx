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
  // The cost-mode panel inside the viewer (`SellInModoCosto.test.jsx`) is out of the way here: no `sell_in.ver`.
  sellInLotesAPI: {
    lotes: vi.fn(),
    consumos: vi.fn(),
    modos: vi.fn(() => Promise.reject(Object.assign(new Error('HTTP 403'), { response: { status: 403 } }))),
  },
}));
vi.mock('../../contexts/PermisosContext', () => ({ usePermisos: () => ({ tienePermiso: () => false }) }));

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
  // T5 PR A: the lots are history. One still holding units is closed, never current, queued or due on a date.
  it('come in FIFO order, each with its status, unit discount, units, the date it counted from and its purchase', async () => {
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
    expect(lotes[1]).toContain('Cerrado');
    expect(lotes[1]).toContain('$ 33,33 por unidad');
    expect(lotes[1]).toContain('Quedan 2 de 3 · 1 usada');
    expect(lotes[2]).toContain('Cerrado');
    // A USD purchase's discount is already in ARS (its own rate); the currency is said.
    expect(lotes[2]).toContain('$ 10.000,00 por unidad (compra en USD)');
    expect(lotes[2]).toContain('#43 · Sin proveedor');
    expect(lotes[3]).toContain('Cerrado');
    expect(lista.textContent).not.toMatch(/Vigente|En cola|Desde 03\/11/);
  });

  it('say they are history: no next sale discount, no cost bonus (T5 PR A, L24)', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(respuesta({ bono_costo: { bono_ids: [7], descuento_unit: 1500 } }));
    renderLotes();

    expect(await screen.findByText('Historial: los lotes ya no descuentan ventas. El sell in baja el costo SI a través de sus facturas.')).toBeInTheDocument();
    expect(screen.queryByText(/próxima venta/)).not.toBeInTheDocument();
    expect(screen.queryByText(/bono de costo|vuelve al normal/)).not.toBeInTheDocument();
  });
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

describe('a manual cost block', () => {
  it('is listed in its FIFO place with its figures, and the lots it replaced say so', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(
      respuesta({
        lotes: [
          lote({ cantidad: 10, consumidas: 4, restantes: 6, estado: 'reemplazado' }),
          lote({ numero: 2, compra_item_id: -7001, compra_id: 7001, proveedor: null, facturas: [], fecha_desde: '2026-10-25', cantidad: 30, consumidas: 3, restantes: 27, descuento_unit: '-2000.000000', estado: 'vigente', manual: true }),
        ],
        proxima: { numero: 2, compra_item_id: -7001, descuento_unit: '-2000.000000', restantes: 27, siguiente: null },
      }),
    );
    renderLotes();
    const lista = await screen.findByRole('list', { name: 'Lotes en orden FIFO' });
    const [reemplazado, bloque] = [...lista.children].map((item) => item.textContent);

    expect(reemplazado).toContain('Reemplazado');
    expect(bloque).toContain('Cerrado');
    expect(bloque).toContain('-$ 2.000,00 por unidad');
    expect(bloque).toContain('Carga manual #7001');
    expect(bloque).not.toContain('Sin proveedor');
  });
});

describe('with no lot', () => {
  it('a product that never had a lot says so, and nothing about a discount', async () => {
    sellInLotesAPI.lotes.mockResolvedValue(respuesta({ lotes: [], proxima: null }));
    renderLotes();

    expect(await screen.findByText('Este producto no tiene lotes de sell in.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Lotes en orden FIFO' })).not.toBeInTheDocument();
    expect(screen.queryByText(/bono de costo|vuelve al normal/)).not.toBeInTheDocument();
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

  it('a failed next page keeps the sales already listed and can be retried', async () => {
    const venta = (ref) => ({ canal: 'ml', venta_ref: ref, fecha_venta: '2026-10-02', unidades: 1, descuento_ars: '100.00' });
    let reintento;
    sellInLotesAPI.consumos
      .mockResolvedValueOnce({ data: { items: [venta(11)], total: 2, page: 1, page_size: 20 } })
      .mockRejectedValueOnce(httpError(500))
      .mockReturnValueOnce(new Promise((resolve) => (reintento = resolve)));
    renderLotes();

    await userEvent.click(await screen.findByRole('button', { name: 'Ver ventas del lote 1' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Ver más ventas' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar las ventas del lote.');
    const ventas = screen.getByRole('list', { name: 'Ventas del lote 1' });
    expect(within(ventas).getByText(/venta 11/)).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Reintentar' }));
    expect(sellInLotesAPI.consumos).toHaveBeenLastCalledWith(950, 501, { page: 2, page_size: 20 });
    expect(screen.getByRole('button', { name: 'Cargando ventas…' })).toBeDisabled();
    reintento({ data: { items: [venta(12)], total: 2, page: 2, page_size: 20 } });
    expect(await within(ventas).findByText(/venta 12/)).toBeInTheDocument();
    expect(within(ventas).getAllByRole('listitem')).toHaveLength(2);
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
