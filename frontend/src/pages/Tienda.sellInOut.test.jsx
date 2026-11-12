import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, act, within } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import Tienda from './Tienda';
import api, { productosAPI } from '../services/api';

// Live color sync is not exercised here; stub the subscription so the page renders without an SSEProvider.
vi.mock('../hooks/useSSEChannel', () => ({ useSSEChannel: vi.fn() }));

// Owner (2026-11-12): Tienda shows the lower cost with sell in and the extra profit with sell in / sell out, on
// Tienda's own nets. Sell in is one figure per row; sell out is per key (backend `SellInOutTienda`).
const BASE = {
  marca: 'BRAND_X',
  stock: 5,
  moneda_costo: 'USD',
  costo: 10,
  precio_gremio_sin_iva: 12780,
  precio_gremio_con_iva: 15463.8,
  markup_gremio: 20,
  precio_sugerido_sin_iva: 13845,
  precio_sugerido_con_iva: 16752.45,
  markup_sugerido_total: 30,
  participa_web_transferencia: true,
  porcentaje_markup_web: 6,
  precio_web_transferencia: 16000,
  markup_web_real: 21.5,
};

const CON_SELL_IN_OUT = {
  ...BASE,
  item_id: 1,
  codigo: 'SKU-SIO',
  descripcion: 'Producto SISO',
  sell_in_out: {
    sell_in: {
      compra_item_id: 7,
      bono_id: null,
      bono_ids: [],
      descuento_unit: 1000,
      costo: 9000,
      unidades_restantes: 2,
      moneda_costo: 'USD',
      costo_moneda: 9,
      descuento_unit_moneda: 1,
    },
    sell_out: { gremio: { monto_unit: 500, campana_ids: [3] }, sugerido: { monto_unit: 500, campana_ids: [3] } },
    markups_sell_in: { gremio: 33.33, sugerido: 44.44, web_transf: 27.12 },
    markups_sell_in_out: { gremio: 38.89, sugerido: 50 },
  },
};

const SIN_SELL_IN_OUT = { ...BASE, item_id: 2, codigo: 'SKU-NADA', descripcion: 'Producto normal', sell_in_out: null };

function setupApiMocks(productos) {
  productosAPI.listarTienda.mockResolvedValue({ data: { productos, total: productos.length } });
  productosAPI.statsDinamicos.mockResolvedValue({ data: {} });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
  api.get.mockImplementation((url) => {
    if (url === '/tipo-cambio/actual') return Promise.resolve({ data: { compra: 1000, venta: 1000 } });
    if (url.startsWith('/auditoria') || url.startsWith('/usuarios/pms')) return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
}

async function renderFila(producto) {
  setupApiMocks([producto]);
  await act(async () => {
    renderWithRouter(<Tienda />);
  });
  await waitFor(() => expect(screen.getByText(producto.descripcion)).toBeInTheDocument());
  return screen.getByText(producto.descripcion).closest('tr');
}

describe('Tienda sell in / sell out', () => {
  it('shows the cost with sell in in the cost currency, on the cost line', async () => {
    const fila = await renderFila(CON_SELL_IN_OUT);

    expect(within(fila).getByText('c/ sell in USD $9.00', { exact: false })).toBeInTheDocument();
    expect(within(fila).getByText('USD $10.00', { exact: false })).toBeInTheDocument();
  });

  it('shows the extra profit per key, with sell out only where that key has one', async () => {
    const fila = await renderFila(CON_SELL_IN_OUT);

    expect(within(fila).getByText('c/ sell in: 33.33%')).toBeInTheDocument();
    expect(within(fila).getByText('c/ sell in + sell out: 38.89%')).toBeInTheDocument();
    expect(within(fila).getByText('c/ sell in: 44.44%')).toBeInTheDocument();
    expect(within(fila).getByText('c/ sell in + sell out: 50.00%')).toBeInTheDocument();
    expect(within(fila).getByText('c/ sell in: 27.12%')).toBeInTheDocument();
    // web_transf has no sell out: only two "sell in + sell out" lines in the row.
    expect(within(fila).getAllByText(/c\/ sell in \+ sell out/)).toHaveLength(2);
  });

  it('labels the markup "c/ sell out" when the row has sell out but no sell in', async () => {
    const fila = await renderFila({
      ...BASE,
      item_id: 3,
      codigo: 'SKU-SO',
      descripcion: 'Solo campañas',
      sell_in_out: {
        sell_in: null,
        sell_out: { gremio: { monto_unit: 500, campana_ids: [3] } },
        markups_sell_in: {},
        markups_sell_in_out: { gremio: 25.5 },
      },
    });

    expect(within(fila).getByText('c/ sell out: 25.50%')).toBeInTheDocument();
    expect(within(fila).queryByText(/c\/ sell in/)).not.toBeInTheDocument();
    expect(within(fila).getByText('USD $10.00')).toBeInTheDocument();
  });

  it('shows a Tienda Nube sell out only under Web Transf. when only that key has one', async () => {
    const fila = await renderFila({
      ...BASE,
      item_id: 4,
      codigo: 'SKU-TN',
      descripcion: 'Solo Tienda Nube',
      sell_in_out: {
        sell_in: null,
        sell_out: { web_transf: { monto_unit: 800, campana_ids: [9] } },
        markups_sell_in: {},
        markups_sell_in_out: { web_transf: 26.5 },
      },
    });

    const lineas = within(fila).getAllByText(/c\/ sell out/);
    expect(lineas).toHaveLength(1);
    expect(lineas[0]).toHaveTextContent('c/ sell out: 26.50%');
    expect(lineas[0].closest('.web-transf-info')).not.toBeNull();
  });

  it('shows the empty marker, never "undefined", for a row without a cost', async () => {
    const fila = await renderFila({ ...SIN_SELL_IN_OUT, item_id: 5, descripcion: 'Sin costo', costo: null });

    expect(fila).not.toHaveTextContent('undefined');
    // Marca, stock, then the cost cell.
    const costo = within(fila).getByText('BRAND_X').closest('td').nextElementSibling.nextElementSibling;
    expect(costo).toHaveTextContent(/^-$/);
  });

  it('keeps a row without sell in or sell out as it was', async () => {
    const fila = await renderFila(SIN_SELL_IN_OUT);

    expect(within(fila).queryByText(/sell in/)).not.toBeInTheDocument();
    expect(within(fila).getByText('USD $10.00')).toBeInTheDocument();
    expect(within(fila).getByText('Markup: 20.0%')).toBeInTheDocument();
  });
});
