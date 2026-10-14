/**
 * One product's prices (ML list and PVP, clásica and instalments) with their
 * markups, read from GET /productos/{item_id}. Read-only.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProductPrices from './ProductPrices';
import { preciosAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  preciosAPI: { obtenerProducto: vi.fn() },
}));

// Shape of GET /productos/{item_id} (ProductoResponse), as the endpoint returns
// it in backend/tests/integration/test_producto_detail_cuota_markups.py.
const PRODUCTO = {
  item_id: 4101,
  codigo: 'ARCHER-AX55',
  descripcion: 'Router Archer AX55',
  marca: 'TP-LINK',
  categoria: 'ROUTERS',
  subcategoria_id: 55,
  moneda_costo: 'ARS',
  costo: 64000,
  costo_ars: 64000,
  iva: 21,
  stock: 7,
  precio_lista_ml: 98500.5,
  markup: 18.4,
  tiene_precio: true,
  precio_3_cuotas: 101200,
  precio_6_cuotas: 104800.25,
  precio_9_cuotas: null,
  precio_12_cuotas: 110900,
  markup_3_cuotas: 20.1,
  markup_6_cuotas: 22.35,
  markup_9_cuotas: null,
  markup_12_cuotas: -2,
  precio_pvp: 99000,
  precio_pvp_3_cuotas: 102000,
  precio_pvp_6_cuotas: null,
  precio_pvp_9_cuotas: null,
  precio_pvp_12_cuotas: null,
  markup_pvp: 19.5,
  markup_pvp_3_cuotas: 21,
  markup_pvp_6_cuotas: null,
  markup_pvp_9_cuotas: null,
  markup_pvp_12_cuotas: null,
  recalcular_cuotas_auto: null,
};

const rowOf = (label) => screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });

beforeEach(() => {
  vi.clearAllMocks();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
});

describe('ProductPrices', () => {
  it('shows the product-wide legend while it loads and after', async () => {
    preciosAPI.obtenerProducto.mockReturnValue(new Promise(() => {}));
    render(<ProductPrices productItemId={4101} />);
    expect(screen.getByRole('note')).toHaveTextContent('El precio es del producto: cambiarlo afecta a todas sus publicaciones.');
    expect(screen.getByRole('status')).toHaveTextContent('Cargando precios');
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
