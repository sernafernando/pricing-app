/**
 * Sell in and sell out next to the plain figures (sell-in-sell-out T10). Owner
 * rule: "Always show both: cost and cost with sell in; markup and totals
 * without and with sell out." The figures come computed in the product's
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

describe('cost with sell in and sell out per unit', () => {
  it('shows the cost with sell in, with its discount per unit and the units left of the lot', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    const costo = factOf(group, 'Costo c/ sell in');
    expect(costo).toHaveTextContent('$ 60.000,00');
    const detalle = costo.querySelector('[title]').getAttribute('title');
    expect(detalle).toContain('Descuento por unidad: $ 4.000,00');
    expect(detalle).toContain('Unidades restantes del lote: 12');
    // The plain cost stays beside it.
    expect(factOf(group, 'Costo')).toHaveTextContent('$ 64.000,00');
  });

  it('names the % of cost bonus in the tooltip when the sell in has no lot (T25c)', async () => {
    const bono = { compra_item_id: null, bono_id: 4, descuento_unit: 4000, costo: 60000, unidades_restantes: null };
    preciosAPI.obtenerProducto.mockResolvedValue({
      data: { ...PRODUCTO_CON_SELL_IN_OUT, sell_in_out: { ...SELL_IN_OUT, sell_in: bono } },
    });
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    const detalle = factOf(group, 'Costo c/ sell in').querySelector('[title]').getAttribute('title');
    expect(detalle).toBe('Descuento por unidad: $ 4.000,00\nBono #4 sobre el costo');
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

  it('a lot whose cost has no ARS value says so', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_in: { ...SELL_IN_OUT.sell_in, costo: null } });
    render(<ProductPrices productItemId={4101} showCost />);
    expect(factOf(await facts(), 'Costo c/ sell in')).toHaveTextContent('Sin tipo de cambio');
  });

  it('a product without sell in or sell out shows "-" in both facts', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    expect(factOf(group, 'Costo c/ sell in')).toHaveTextContent(/^-$/);
    expect(factOf(group, 'Sell out por unidad')).toHaveTextContent(/^-$/);
  });

  it('none of it is shown without the cost permission', async () => {
    render(<ProductPrices productItemId={4101} />);
    const group = await facts();
    expect(group).not.toHaveTextContent('Costo c/ sell in');
    expect(group).not.toHaveTextContent('Sell out por unidad');
    expect(screen.queryByText('c/ sell in/out')).not.toBeInTheDocument();
  });
});

describe('markup with sell in and sell out', () => {
  it('shows each row the markup with sell in + sell out of its own key', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    await screen.findByRole('table', { name: 'Precios por plan' });
    expect(screen.getAllByText('c/ sell in/out')).toHaveLength(10);
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

  it('without sell out shows the markup with sell in', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: null, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent('26,30%'));
    expect(sellCell(await priceOf('PVP 3 cuotas'))).toHaveTextContent('29,10%');
  });

  it('with a pending sell out falls back to the markup with sell in', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('12 cuotas'))).toHaveTextContent('4,50%'));
  });

  it('a pending sell out says so in the tooltip of the markup with sell in', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent('26,30%'));
    expect(sellCell(await priceOf('Clásica')).firstChild).toHaveAttribute('title', 'Con sell in; el sell out está pendiente');
  });

  it('with a pending sell out, a row without price still shows "—", never "Pendiente"', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('9 cuotas'))).toHaveTextContent(/^—$/));
    expect(sellCell(await priceOf('PVP 6 cuotas'))).toHaveTextContent(/^—$/);
  });

  it('a lot without an ARS cost leaves the row without price as "—"', async () => {
    withSellInOut({
      ...SELL_IN_OUT,
      sell_in: { ...SELL_IN_OUT.sell_in, costo: null },
      markups_sell_in: {},
      markups_sell_in_out: {},
    });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('9 cuotas'))).toHaveTextContent(/^—$/));
  });

  it('a lot without an ARS cost leaves the markup pending, not as a row without price', async () => {
    withSellInOut({
      ...SELL_IN_OUT,
      sell_in: { ...SELL_IN_OUT.sell_in, costo: null },
      markups_sell_in: {},
      markups_sell_in_out: {},
    });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await priceOf('Clásica'))).toHaveTextContent(/^Pendiente$/));
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
