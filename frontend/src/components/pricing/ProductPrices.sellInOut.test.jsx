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

const rowOf = (label) => screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });
const facts = () => screen.findByRole('group', { name: 'Referencias del producto' });
const sellCell = (row) => row.querySelector('[data-col="markup-sell-in-out"]');
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
    expect(screen.queryByRole('columnheader', { name: 'Markup c/ sell in/out' })).not.toBeInTheDocument();
  });
});

describe('markup with sell in and sell out', () => {
  it('shows each row the markup with sell in + sell out of its own key', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    expect(await screen.findAllByRole('columnheader', { name: 'Markup c/ sell in/out' })).toHaveLength(2);
    await waitFor(async () => expect(sellCell(await rowOf('Clásica'))).toHaveTextContent('28,80%'));
    expect(sellCell(await rowOf('3 cuotas'))).toHaveTextContent('30,60%');
    expect(sellCell(await rowOf('6 cuotas'))).toHaveTextContent('32,90%');
    expect(sellCell(await rowOf('12 cuotas'))).toHaveTextContent('7,00%');
    expect(sellCell(await rowOf('PVP clásica'))).toHaveTextContent('30,00%');
    expect(sellCell(await rowOf('PVP 3 cuotas'))).toHaveTextContent('31,60%');
    // A row without a price has no markup with sell in/out either.
    expect(sellCell(await rowOf('9 cuotas'))).toHaveTextContent('—');
    // The plain markup and the legacy offset column stay.
    expect((await rowOf('Clásica')).querySelector('[data-col="markup"]')).toHaveTextContent('18,40%');
    expect((await rowOf('Clásica')).querySelector('[data-col="markup-offset"]')).toBeInTheDocument();
  });

  it('without sell out shows the markup with sell in', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: null, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await rowOf('Clásica'))).toHaveTextContent('26,30%'));
    expect(sellCell(await rowOf('PVP 3 cuotas'))).toHaveTextContent('29,10%');
  });

  it('with a pending sell out falls back to the markup with sell in', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await rowOf('12 cuotas'))).toHaveTextContent('4,50%'));
  });

  it('a pending sell out says so in the tooltip of the markup with sell in', async () => {
    withSellInOut({ ...SELL_IN_OUT, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in_out: {} });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await rowOf('Clásica'))).toHaveTextContent('26,30%'));
    expect(sellCell(await rowOf('Clásica')).firstChild).toHaveAttribute('title', 'Con sell in; el sell out está pendiente');
  });

  it('a lot without an ARS cost leaves the markup pending, not as a row without price', async () => {
    withSellInOut({
      ...SELL_IN_OUT,
      sell_in: { ...SELL_IN_OUT.sell_in, costo: null },
      markups_sell_in: {},
      markups_sell_in_out: {},
    });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await rowOf('Clásica'))).toHaveTextContent(/^Pendiente$/));
  });

  it('a product without sell_in_out shows "-" in every row', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(async () => expect(sellCell(await rowOf('Clásica'))).toHaveTextContent(/^-$/));
    expect(sellCell(await rowOf('PVP clásica'))).toHaveTextContent(/^-$/);
  });
});
