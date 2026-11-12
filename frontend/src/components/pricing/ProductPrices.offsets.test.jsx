/**
 * Every price's markup with offset, as Productos
 * computes its "markup con offsets aplicados" (utils/offsetsGanancia), shown
 * only to who may see the cost (ml_metricas.ver_ganancia); and every markup
 * painted by the app's markup scale (utils/ventasMlTone.markupTone).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPrices from './ProductPrices';
import { priceOf } from './priceTestUtils';
import { pricePermissions } from './productPricePermissions';
import { offsetsGananciaAPI, preciosAPI } from '../../services/api';
import { PRODUCTO } from './ProductPrices.fixtures';

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

// PRODUCTO: TP-LINK / ROUTERS, ARS cost 64.000.
const OFFSETS = [
  { id: 7, marca: 'TP-LINK', tipo_offset: 'porcentaje_costo', porcentaje: 10, descripcion: 'Rebate TP-Link', grupo_id: null },
  { id: 8, item_id: 4101, tipo_offset: 'monto_por_unidad', monto: 600, moneda: 'ARS', descripcion: null, grupo_id: null },
  { id: 9, marca: 'OTRA', tipo_offset: 'porcentaje_costo', porcentaje: 50, descripcion: 'No aplica', grupo_id: null },
];

const USD_PER_UNIT = { id: 11, item_id: 4101, tipo_offset: 'monto_por_unidad', monto: 2, moneda: 'USD', descripcion: 'Bonificación USD', grupo_id: null };

const facts = () => screen.findByRole('group', { name: 'Referencias del producto' });
const offsetCell = (price) => price.querySelector('[data-col="markup-offset"]');

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
  offsetsGananciaAPI.vigentes.mockResolvedValue({ data: OFFSETS });
  offsetsGananciaAPI.grupoFiltros.mockResolvedValue({ data: [] });
});

describe('cost and markup with offset', () => {
  it('no longer shows a "Costo con offset" fact (the cost with sell in replaced it)', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('32,94%'));
    expect(group).not.toHaveTextContent('Costo con offset');
    expect(within(group).queryByRole('list', { name: 'Offsets aplicados' })).not.toBeInTheDocument();
    expect(group).toHaveTextContent('Costo c/ sell in');
    expect(offsetsGananciaAPI.vigentes).toHaveBeenCalled();
  });

  it('shows the markup with offset of EVERY price row, as Productos computes it', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    // Every price of the table carries its markup with offset, labelled in its cell.
    await screen.findByRole('table', { name: 'Precios por plan' });
    expect(document.querySelectorAll('[data-col="markup-offset"]')).toHaveLength(10);
    expect(screen.getAllByText('c/ offset')).toHaveLength(10);
    // clásica 18,4% -> (1.184 * 64000 / 57000 - 1) = 32,94%
    await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('32,94%'));
    // 3 cuotas 20,1% -> 34,85%; 12 cuotas -2% -> 10,04%
    expect(offsetCell(await priceOf('3 cuotas'))).toHaveTextContent('34,85%');
    expect(offsetCell(await priceOf('12 cuotas'))).toHaveTextContent('10,04%');
    // PVP clásica 19,5% -> 34,18%; PVP 3 cuotas 21% -> 35,86%
    expect(offsetCell(await priceOf('PVP clásica'))).toHaveTextContent('34,18%');
    expect(offsetCell(await priceOf('PVP 3 cuotas'))).toHaveTextContent('35,86%');
    // A row without a markup has no markup with offset either.
    expect(offsetCell(await priceOf('9 cuotas'))).toHaveTextContent('—');
  });

  it('shows "—" as markup with offset when no offset applies', async () => {
    offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[2]] });
    render(<ProductPrices productItemId={4101} showCost />);
    await waitFor(() => expect(offsetsGananciaAPI.vigentes).toHaveBeenCalled());
    await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('—'));
  });

  it('a failed offsets read does not break the prices', async () => {
    offsetsGananciaAPI.vigentes.mockRejectedValue(new Error('Network Error'));
    render(<ProductPrices productItemId={4101} showCost />);
    expect(await priceOf('Clásica')).toHaveTextContent('98.500,50');
    await waitFor(() => expect(offsetsGananciaAPI.vigentes).toHaveBeenCalled());
    expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('—');
  });

  it('counts only the offsets that apply to Mercado Libre (aplica_ml)', async () => {
    offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[0], { ...OFFSETS[1], aplica_ml: false, descripcion: 'Solo fuera de ML' }] });
    render(<ProductPrices productItemId={4101} showCost />);
    // 64.000 - 6.400 (only the 10%): clásica 18,4% -> 31,56%
    await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('31,56%'));
  });

  describe('a USD cost', () => {
    const USD_PRODUCT = { ...PRODUCTO, moneda_costo: 'USD', costo: 50, costo_ars: null };

    it('converts the cost for the markup with offset with the SAME rate (venta), not the offsets one', async () => {
      preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { moneda: 'USD', compra: 1250, venta: 1280, fecha: '2026-10-14' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[0]] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      // USD 50 x 1280 = 64.000; minus 10% = 57.600 (with the offsets rate it would be 45.000)
      await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('31,56%'));
      expect(group).toHaveTextContent('$ 64.000,00');
    });

    it('without that rate shows no markup with offset', async () => {
      preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { error: 'No hay tipo de cambio disponible' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[0]] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      await waitFor(() => expect(group).toHaveTextContent('sin tipo de cambio'));
      expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('—');
    });

    it('converts a USD per-unit offset with that same rate (venta) too', async () => {
      preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { moneda: 'USD', compra: 1250, venta: 1280, fecha: '2026-10-14' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [USD_PER_UNIT] });
      render(<ProductPrices productItemId={4101} showCost />);
      // USD 50 x 1280 = 64.000; USD 2 x 1280 = 2.560; clásica 18,4% -> 1.184 x 64.000 / 61.440 - 1 = 23,33%
      await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('23,33%'));
    });
  });

  describe('an ARS cost with a USD per-unit offset', () => {
    it('converts the offset with the venta rate', async () => {
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { moneda: 'USD', compra: 1250, venta: 1280, fecha: '2026-10-14' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [USD_PER_UNIT] });
      render(<ProductPrices productItemId={4101} showCost />);
      await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('23,33%'));
    });

    it('never falls back to an assumed rate: without venta it shows no markup with offset', async () => {
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { error: 'No hay tipo de cambio disponible' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [USD_PER_UNIT] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      await waitFor(() => expect(preciosAPI.tipoCambioActual).toHaveBeenCalled());
      expect(group).toHaveTextContent('$ 64.000,00');
      expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('—');
    });

    it('asks for no rate when no USD amount is involved', async () => {
      render(<ProductPrices productItemId={4101} showCost />);
      await waitFor(async () => expect(offsetCell(await priceOf('Clásica'))).toHaveTextContent('32,94%'));
      expect(preciosAPI.tipoCambioActual).not.toHaveBeenCalled();
    });
  });

  it('never reads nor shows offsets without permission to see the cost', async () => {
    render(<ProductPrices productItemId={4101} />);
    const group = await facts();
    expect(group).not.toHaveTextContent('Costo con offset');
    expect(screen.queryByText('c/ offset')).not.toBeInTheDocument();
    expect(offsetCell(await priceOf('Clásica'))).toBeNull();
    expect(offsetsGananciaAPI.vigentes).not.toHaveBeenCalled();
  });
});

describe('markup colour', () => {
  const toneOf = (price) => price.querySelector('[data-col="markup"] [data-tone]')?.getAttribute('data-tone');

  it('paints each markup by the app scale: negative, low (under 6%) or good', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, markup_3_cuotas: 4.5, markup_6_cuotas: 6 } });
    render(<ProductPrices productItemId={4101} />);
    expect(toneOf(await priceOf('Clásica'))).toBe('good');
    expect(toneOf(await priceOf('3 cuotas'))).toBe('low');
    expect(toneOf(await priceOf('6 cuotas'))).toBe('good');
    expect(toneOf(await priceOf('12 cuotas'))).toBe('negative');
    // Unknown is no colour, never a zero.
    expect(toneOf(await priceOf('9 cuotas'))).toBeUndefined();
  });

  it('paints the markup with offset by the same scale', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const clasica = await priceOf('Clásica');
    await waitFor(() => expect(offsetCell(clasica).querySelector('[data-tone]')).toHaveAttribute('data-tone', 'good'));
  });
});

describe('editing by markup is in plain sight', () => {
  it('each editable row offers "edit by markup" next to "edit the price", opening the markup editor', async () => {
    const user = userEvent.setup();
    render(<ProductPrices productItemId={4101} permissions={pricePermissions(() => true)} onWritten={vi.fn()} />);
    const row = await priceOf('3 cuotas');
    await user.click(within(row).getByRole('button', { name: 'Editar 3 cuotas por markup' }));
    expect(within(row).getByRole('textbox', { name: '3 cuotas markup objetivo' })).toHaveValue('20,1');
    expect(within(row).getByRole('button', { name: 'Por markup' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/fijar su markup/)).toBeInTheDocument();
  });

  it('read-only users get no markup editor', async () => {
    render(<ProductPrices productItemId={4101} />);
    await priceOf('Clásica');
    expect(screen.queryByRole('button', { name: /por markup/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/fijar su markup/)).not.toBeInTheDocument();
  });
});
