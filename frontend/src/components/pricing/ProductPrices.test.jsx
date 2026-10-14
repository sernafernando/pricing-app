/**
 * One product's prices (ML list and PVP, clásica and instalments) with their
 * markups, read from GET /productos/{item_id}. Without write permissions
 * the view is read-only (editing: ProductPrices.editing.test.jsx).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import ProductPrices from './ProductPrices';
import { preciosAPI } from '../../services/api';
import { PRODUCTO } from './ProductPrices.fixtures';

vi.mock('../../services/api', () => ({
  preciosAPI: { obtenerProducto: vi.fn(), tipoCambioActual: vi.fn() },
}));

const rowOf = (label) => screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });

beforeEach(() => {
  vi.clearAllMocks();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
});

describe('ProductPrices', () => {
  const LEGEND = 'El precio es del producto: cambiarlo afecta a todas sus publicaciones.';

  it('shows the product-wide legend while it loads and after', async () => {
    preciosAPI.obtenerProducto.mockReturnValue(new Promise(() => {}));
    const { unmount } = render(<ProductPrices productItemId={4101} />);
    expect(screen.getByRole('note')).toHaveTextContent(LEGEND);
    expect(screen.getByRole('status')).toHaveTextContent('Cargando precios');
    unmount();

    preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
    render(<ProductPrices productItemId={4101} />);
    await rowOf('Clásica');
    expect(screen.getByRole('note')).toHaveTextContent(LEGEND);
  });

  it('keeps the legend when the read fails', async () => {
    preciosAPI.obtenerProducto.mockRejectedValue(new Error('Network Error'));
    render(<ProductPrices productItemId={4101} />);
    await screen.findByRole('alert');
    expect(screen.getByRole('note')).toHaveTextContent(LEGEND);
  });

  it.each([
    ['a network error (no response)', new Error('Network Error')],
    ['a validation error (array detail)', { response: { data: { detail: [{ msg: 'bad', loc: ['path', 'item_id'] }] } } }],
  ])('shows the generic message on %s', async (_, error) => {
    preciosAPI.obtenerProducto.mockRejectedValue(error);
    render(<ProductPrices productItemId={4101} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los precios del producto.');
  });

  it('reads the product by item_id and shows each price with its markup', async () => {
    render(<ProductPrices productItemId={4101} />);
    const clasica = await rowOf('Clásica');
    expect(clasica).toHaveTextContent('98.500,50');
    expect(clasica).toHaveTextContent('18,40%');
    expect(await rowOf('6 cuotas')).toHaveTextContent('22,35%');
    expect(await rowOf('PVP clásica')).toHaveTextContent('99.000,00');
    expect(await rowOf('PVP 3 cuotas')).toHaveTextContent('21,00%');
    expect(screen.getByText('ARCHER-AX55')).toBeInTheDocument();
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledWith(4101);
  });

  it('shows "—" for a missing price or markup, never 0', async () => {
    render(<ProductPrices productItemId={4101} />);
    const nueve = await rowOf('9 cuotas');
    expect(nueve).not.toHaveTextContent('0,00');
    expect(nueve.textContent.match(/—/g)).toHaveLength(2);
  });

  it('shows the price with "—" as markup when the backend does not send the instalment markups yet', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({
      data: { ...PRODUCTO, markup_3_cuotas: null, markup_6_cuotas: null, markup_9_cuotas: null, markup_12_cuotas: null },
    });
    render(<ProductPrices productItemId={4101} />);
    const tres = await rowOf('3 cuotas');
    expect(tres).toHaveTextContent('101.200,00');
    expect(tres).toHaveTextContent('—');
  });

  it('marks a negative markup', async () => {
    render(<ProductPrices productItemId={4101} />);
    const doce = await rowOf('12 cuotas');
    expect(doce).toHaveTextContent('-2,00%');
    expect(doce.querySelector('[data-negative]')).not.toBeNull();
  });

  it('is read-only', async () => {
    render(<ProductPrices productItemId={4101} />);
    await rowOf('Clásica');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('says so when the product cannot be read', async () => {
    preciosAPI.obtenerProducto.mockRejectedValue({ response: { status: 404, data: { detail: 'Producto no encontrado' } } });
    render(<ProductPrices productItemId={4101} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Producto no encontrado');
  });

  it('reads again when the product changes, never showing the previous one', async () => {
    const { rerender } = render(<ProductPrices productItemId={4101} />);
    await screen.findByText('ARCHER-AX55');
    preciosAPI.obtenerProducto.mockReturnValue(new Promise(() => {}));
    rerender(<ProductPrices productItemId={4102} />);
    expect(screen.queryByText('ARCHER-AX55')).not.toBeInTheDocument();
    expect(preciosAPI.obtenerProducto).toHaveBeenLastCalledWith(4102);
  });
});

describe('cost and IVA next to the prices', () => {
  const facts = () => screen.findByRole('group', { name: 'Referencias del producto' });
  const USD_PRODUCT = { ...PRODUCTO, moneda_costo: 'USD', costo: 50, costo_ars: null };

  it('shows the IVA rate to anyone who sees the prices, and no cost without permission', async () => {
    render(<ProductPrices productItemId={4101} />);
    const group = await facts();
    expect(group).toHaveTextContent('IVA');
    expect(group).toHaveTextContent('21%');
    expect(group).not.toHaveTextContent('Costo');
    expect(group).not.toHaveTextContent('64.000');
  });

  it('writes a fractional IVA rate in es-AR', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, iva: 10.5 } });
    render(<ProductPrices productItemId={4101} />);
    expect(await facts()).toHaveTextContent('10,5%');
  });

  it('shows the cost in ARS to who may see it', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    expect(group).toHaveTextContent('Costo');
    expect(group).toHaveTextContent('$ 64.000,00');
    expect(preciosAPI.tipoCambioActual).not.toHaveBeenCalled();
  });

  it('converts a USD cost to ARS with the current exchange rate (venta), showing the original', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
    preciosAPI.tipoCambioActual.mockResolvedValue({ data: { moneda: 'USD', compra: 1250, venta: 1280, fecha: '2026-10-14' } });
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    await waitFor(() => expect(group).toHaveTextContent('$ 64.000,00'));
    expect(group).toHaveTextContent('USD 50,00');
    expect(group).toHaveTextContent('1.280,00');
  });

  it('without an exchange rate shows the USD cost and says it is not converted', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
    preciosAPI.tipoCambioActual.mockResolvedValue({ data: { error: 'No hay tipo de cambio disponible' } });
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    await waitFor(() => expect(group).toHaveTextContent('sin tipo de cambio'));
    expect(group).toHaveTextContent('USD 50,00');
  });

  it('a failed exchange-rate read does not break the prices', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
    preciosAPI.tipoCambioActual.mockRejectedValue(new Error('Network Error'));
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    await waitFor(() => expect(group).toHaveTextContent('sin tipo de cambio'));
    expect(await rowOf('Clásica')).toHaveTextContent('98.500,50');
  });

  it('never asks for the exchange rate when the cost is not shown', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
    render(<ProductPrices productItemId={4101} />);
    expect(await facts()).not.toHaveTextContent('USD');
    expect(preciosAPI.tipoCambioActual).not.toHaveBeenCalled();
  });

  it('a missing cost or IVA is "—", never 0', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, costo: null, costo_ars: null, iva: null } });
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    expect(group).toHaveTextContent('—');
    expect(group).not.toHaveTextContent('$ 0');
  });
});
