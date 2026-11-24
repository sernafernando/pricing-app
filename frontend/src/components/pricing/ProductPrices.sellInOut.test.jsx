/**
 * Sell out next to the plain figures (sell-in-sell-out T10; no cost with sell
 * in since costo SI T5 PR B: costo SI already holds it). The figures come computed in the product's
 * `sell_in_out` (GET /productos/{item_id}); they are shown only to who may see
 * the cost (ml_metricas.ver_ganancia), like the offsets.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import ProductPrices from './ProductPrices';
import { priceOf } from './priceTestUtils';
import { offsetsGananciaAPI, preciosAPI } from '../../services/api';
import { PRODUCTO, PRODUCTO_CON_SELL_IN_OUT, SELL_IN_OUT } from './ProductPrices.fixtures';

vi.mock('../../services/api', () => ({
  preciosAPI: {
    obtenerProducto: vi.fn(),
    tipoCambioActual: vi.fn(),
    calcularMarkup: vi.fn(),
    calcularPorMarkup: vi.fn(),
    setRapido: vi.fn(),
    setCuota: vi.fn(),
  },
  offsetsGananciaAPI: { vigentes: vi.fn(), grupoFiltros: vi.fn() },
}));

const facts = () => screen.findByRole('group', { name: 'Referencias del producto' });
const sellCell = (price) => price.querySelector('[data-col="markup-sell-in-out"]');
const factOf = (group, label) => within(group).getByText(label, { selector: 'dt' }).nextElementSibling;

const withSellInOut = (sellInOut) => preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, sell_in_out: sellInOut } });

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO_CON_SELL_IN_OUT });
  offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
  offsetsGananciaAPI.grupoFiltros.mockResolvedValue({ data: [] });
});

describe('sell out per unit, no cost with sell in', () => {
  // costo SI T5 PR B: costo SI replaced the FIFO lots and the per-sale cost bonuses, so the payload has no
  // sell in and there is no "Costo c/ sell in" fact any more.
  it('shows no "Costo c/ sell in" fact, the cost, the costo SI and the sell out beside each other', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    expect(within(group).queryByText('Costo c/ sell in', { selector: 'dt' })).not.toBeInTheDocument();
    expect(group).not.toHaveTextContent(/sell in/);
    expect(factOf(group, 'Costo')).toHaveTextContent('$ 64.000,00');
    expect(factOf(group, 'Sell out por unidad')).toHaveTextContent('$ 1.500,00');
  });

  it('shows the sell out per unit', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    expect(factOf(await facts(), 'Sell out por unidad')).toHaveTextContent('$ 1.500,00');
  });

  it('a sell out without an amount yet is pending, never a made-up number', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    const sellOut = factOf(await facts(), 'Sell out por unidad');
    expect(sellOut).toHaveTextContent('Pendiente');
    expect(sellOut).not.toHaveTextContent('$');
  });

  it('a product without sell out shows "-" in its fact', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
    render(<ProductPrices productItemId={4101} showCost />);
    expect(factOf(await facts(), 'Sell out por unidad')).toHaveTextContent(/^-$/);
  });

  it('none of it is shown without the cost permission', async () => {
    render(<ProductPrices productItemId={4101} />);
    const group = await facts();
    expect(group).not.toHaveTextContent('Sell out por unidad');
    expect(screen.queryByText('c/ SO')).not.toBeInTheDocument();
  });
});

describe('markup with sell in and sell out', () => {
  it('shows each row the markup with sell in + sell out of its own key', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    await screen.findByRole('table', { name: 'Precios por plan' });
    expect(screen.getAllByText('c/ SO')).toHaveLength(10);
    expect(screen.queryByText('c/ sell in/out')).not.toBeInTheDocument();
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent('28,80%'));
    expect(sellCell(await priceOf('3 cuotas'))).toHaveTextContent('30,60%');
    expect(sellCell(await priceOf('6 cuotas'))).toHaveTextContent('32,90%');
    expect(sellCell(await priceOf('12 cuotas'))).toHaveTextContent('7,00%');
    expect(sellCell(await priceOf('PVP clásica'))).toHaveTextContent('30,00%');
    expect(sellCell(await priceOf('PVP 3 cuotas'))).toHaveTextContent('31,60%');
    // A row without a price has no markup with sell in/out either.
    expect(sellCell(await priceOf('9 cuotas'))).toHaveTextContent('—');
    // The plain markup and the legacy offset column stay.
    expect((await priceOf('Clásica')).querySelector('[data-col="markup"]')).toHaveTextContent('18,40%');
    expect((await priceOf('Clásica')).querySelector('[data-col="markup-offset"]')).toBeInTheDocument();
  });

  it('a product without sell out reads "-" with a tooltip naming only the sell out (D1)', async () => {
    withSellInOut(null);
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent('-'));
    expect(sellCell(await priceOf('Clásica')).firstChild).toHaveAttribute('title', 'Sin sell out');
  });

  it('the c/ SO markup says in its tooltip that it is the one with sell out', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent('28,80%'));
    expect(sellCell(await priceOf('Clásica')).firstChild).toHaveAttribute('title', 'Con sell out');
  });

  it('with sell in but no sell out shows "-", never a markup with sell in (D1: the sell in is in the costo SI)', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: null, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent(/^-$/));
    expect(sellCell(await priceOf('Clásica')).firstChild).toHaveAttribute('title', 'Sin sell out');
    expect(sellCell(await priceOf('PVP 3 cuotas'))).toHaveTextContent(/^-$/);
  });

  it('a pending sell out reads "Pendiente" with why, never the markup with sell in', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('12 cuotas'))).toHaveTextContent(/^Pendiente$/));
    expect(sellCell(await priceOf('Clásica')).firstChild).toHaveAttribute(
      'title',
      'Falta el tipo de cambio o la base para calcular el markup',
    );
  });

  it('with a pending sell out, a row without price still shows "—", never "Pendiente"', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('9 cuotas'))).toHaveTextContent(/^—$/));
    expect(sellCell(await priceOf('PVP 6 cuotas'))).toHaveTextContent(/^—$/);
  });

  it('a block with no sell out leaves the c/ SO markup as "-", never pending', async () => {
    withSellInOut({
      ...SELL_IN_OUT,
      sell_out: null,
      markups_sell_in: {},
      markups_sell_in_out: {},
    });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent(/^-$/));
  });

  it('a product without sell_in_out shows "-" in every row', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent(/^-$/));
    expect(sellCell(await priceOf('PVP clásica'))).toHaveTextContent(/^-$/);
  });
});

describe('installment row labels', () => {
  it("names each plan in full in its row, and each price by its list's own name", async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const ml = await priceOf('12 cuotas');
    const pvp = await priceOf('PVP 12 cuotas');
    // One row, two prices: the plan heads the row, the columns say which list.
    expect(ml.closest('tr')).toBe(pvp.closest('tr'));
    expect(within(ml.closest('tr')).getByRole('rowheader')).toHaveTextContent(/^12 cuotas$/);
  });

});
