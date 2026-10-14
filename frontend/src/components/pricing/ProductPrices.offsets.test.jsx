/**
 * The cost with offset and every price's markup with offset, as Productos
 * computes its "markup con offsets aplicados" (utils/offsetsGanancia), shown
 * only to who may see the cost (ml_metricas.ver_ganancia); and every markup
 * painted by the app's markup scale (utils/ventasMlTone.markupTone).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPrices from './ProductPrices';
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

const rowOf = (label) => screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });
const facts = () => screen.findByRole('group', { name: 'Referencias del producto' });
const offsetCell = (row) => row.querySelector('[data-col="markup-offset"]');

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
  offsetsGananciaAPI.vigentes.mockResolvedValue({ data: OFFSETS });
  offsetsGananciaAPI.grupoFiltros.mockResolvedValue({ data: [] });
});

describe('cost and markup with offset', () => {
  it('shows the cost with the offsets that apply, each with its description and amount', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    // 64.000 - 6.400 (10%) - 600 = 57.000
    await waitFor(() => expect(group).toHaveTextContent('$ 57.000,00'));
    expect(group).toHaveTextContent('Costo con offset');
    const aplicados = within(group).getByRole('list', { name: 'Offsets aplicados' });
    expect(aplicados).toHaveTextContent('Rebate TP-Link');
    expect(aplicados).toHaveTextContent('$ 6.400,00');
    expect(aplicados).toHaveTextContent('Offset #8');
    expect(aplicados).toHaveTextContent('$ 600,00');
    expect(aplicados).not.toHaveTextContent('No aplica');
    expect(offsetsGananciaAPI.vigentes).toHaveBeenCalled();
  });

  it('shows the markup with offset of EVERY price row, as Productos computes it', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    expect(await screen.findAllByRole('columnheader', { name: 'Markup con offset' })).toHaveLength(2);
    // clásica 18,4% -> (1.184 * 64000 / 57000 - 1) = 32,94%
    await waitFor(async () => expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('32,94%'));
    // 3 cuotas 20,1% -> 34,85%; 12 cuotas -2% -> 10,04%
    expect(offsetCell(await rowOf('3 cuotas'))).toHaveTextContent('34,85%');
    expect(offsetCell(await rowOf('12 cuotas'))).toHaveTextContent('10,04%');
    // PVP clásica 19,5% -> 34,18%; PVP 3 cuotas 21% -> 35,86%
    expect(offsetCell(await rowOf('PVP clásica'))).toHaveTextContent('34,18%');
    expect(offsetCell(await rowOf('PVP 3 cuotas'))).toHaveTextContent('35,86%');
    // A row without a markup has no markup with offset either.
    expect(offsetCell(await rowOf('9 cuotas'))).toHaveTextContent('—');
  });

  it('says there are no offsets when none applies, and shows "—" as markup with offset', async () => {
    offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[2]] });
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    await waitFor(() => expect(group).toHaveTextContent('Sin offsets vigentes'));
    expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('—');
  });

  it('a failed offsets read does not break the prices', async () => {
    offsetsGananciaAPI.vigentes.mockRejectedValue(new Error('Network Error'));
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    await waitFor(() => expect(group).toHaveTextContent('No se pudieron leer los offsets'));
    expect(await rowOf('Clásica')).toHaveTextContent('98.500,50');
    expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('—');
  });

  it('counts only the offsets that apply to Mercado Libre (aplica_ml)', async () => {
    offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[0], { ...OFFSETS[1], aplica_ml: false, descripcion: 'Solo fuera de ML' }] });
    render(<ProductPrices productItemId={4101} showCost />);
    const group = await facts();
    // 64.000 - 6.400 (only the 10%)
    await waitFor(() => expect(group).toHaveTextContent('$ 57.600,00'));
    expect(group).not.toHaveTextContent('Solo fuera de ML');
    expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('31,56%');
  });

  describe('a USD cost', () => {
    const USD_PRODUCT = { ...PRODUCTO, moneda_costo: 'USD', costo: 50, costo_ars: null };

    it('converts the cost and the cost with offset with the SAME rate (venta), not the offsets one', async () => {
      preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { moneda: 'USD', compra: 1250, venta: 1280, fecha: '2026-10-14' } });
          offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[0]] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      // USD 50 x 1280 = 64.000; minus 10% = 57.600 (with the offsets rate it would be 45.000)
      await waitFor(() => expect(group).toHaveTextContent('$ 57.600,00'));
      expect(group).toHaveTextContent('$ 64.000,00');
      expect(within(group).getByRole('list', { name: 'Offsets aplicados' })).toHaveTextContent('$ 6.400,00');
      expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('31,56%');
    });

    it('without that rate shows no cost with offset nor markup with offset', async () => {
      preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { error: 'No hay tipo de cambio disponible' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [OFFSETS[0]] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      await waitFor(() => expect(group).toHaveTextContent('Sin tipo de cambio para el offset'));
      expect(within(group).queryByRole('list', { name: 'Offsets aplicados' })).not.toBeInTheDocument();
      expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('—');
    });

    it('converts a USD per-unit offset with that same rate (venta) too', async () => {
      preciosAPI.obtenerProducto.mockResolvedValue({ data: USD_PRODUCT });
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { moneda: 'USD', compra: 1250, venta: 1280, fecha: '2026-10-14' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [USD_PER_UNIT] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      // USD 50 x 1280 = 64.000; USD 2 x 1280 = 2.560; 64.000 - 2.560 = 61.440
      await waitFor(() => expect(group).toHaveTextContent('$ 61.440,00'));
      expect(within(group).getByRole('list', { name: 'Offsets aplicados' })).toHaveTextContent('$ 2.560,00');
      // clásica 18,4% -> 1.184 x 64.000 / 61.440 - 1 = 23,33%
      expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('23,33%');
    });
  });

  describe('an ARS cost with a USD per-unit offset', () => {
    it('converts the offset with the venta rate', async () => {
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { moneda: 'USD', compra: 1250, venta: 1280, fecha: '2026-10-14' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [USD_PER_UNIT] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      await waitFor(() => expect(group).toHaveTextContent('$ 61.440,00'));
      expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('23,33%');
    });

    it('never falls back to an assumed rate: without venta it says so and shows no markup with offset', async () => {
      preciosAPI.tipoCambioActual.mockResolvedValue({ data: { error: 'No hay tipo de cambio disponible' } });
      offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [USD_PER_UNIT] });
      render(<ProductPrices productItemId={4101} showCost />);
      const group = await facts();
      await waitFor(() => expect(group).toHaveTextContent('Sin tipo de cambio para el offset'));
      expect(group).toHaveTextContent('$ 64.000,00');
      expect(within(group).queryByRole('list', { name: 'Offsets aplicados' })).not.toBeInTheDocument();
      expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('—');
    });

    it('asks for no rate when no USD amount is involved', async () => {
      render(<ProductPrices productItemId={4101} showCost />);
      await waitFor(async () => expect(offsetCell(await rowOf('Clásica'))).toHaveTextContent('32,94%'));
      expect(preciosAPI.tipoCambioActual).not.toHaveBeenCalled();
    });
  });

  it('never reads nor shows offsets without permission to see the cost', async () => {
    render(<ProductPrices productItemId={4101} />);
    const group = await facts();
    expect(group).not.toHaveTextContent('Costo con offset');
    expect(screen.queryByRole('columnheader', { name: 'Markup con offset' })).not.toBeInTheDocument();
    expect(offsetCell(await rowOf('Clásica'))).toBeNull();
    expect(offsetsGananciaAPI.vigentes).not.toHaveBeenCalled();
  });
});

describe('markup colour', () => {
  const toneOf = (row) => row.querySelector('[data-col="markup"] [data-tone]')?.getAttribute('data-tone');

  it('paints each markup by the app scale: negative, low (under 6%) or good', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, markup_3_cuotas: 4.5, markup_6_cuotas: 6 } });
    render(<ProductPrices productItemId={4101} />);
    expect(toneOf(await rowOf('Clásica'))).toBe('good');
    expect(toneOf(await rowOf('3 cuotas'))).toBe('low');
    expect(toneOf(await rowOf('6 cuotas'))).toBe('good');
    expect(toneOf(await rowOf('12 cuotas'))).toBe('negative');
    // Unknown is no colour, never a zero.
    expect(toneOf(await rowOf('9 cuotas'))).toBeUndefined();
  });

  it('paints the markup with offset by the same scale', async () => {
    render(<ProductPrices productItemId={4101} showCost />);
    const clasica = await rowOf('Clásica');
    await waitFor(() => expect(offsetCell(clasica).querySelector('[data-tone]')).toHaveAttribute('data-tone', 'good'));
  });
});

describe('editing by markup is in plain sight', () => {
  it('each editable row offers "edit by markup" next to "edit the price", opening the markup editor', async () => {
    const user = userEvent.setup();
    render(<ProductPrices productItemId={4101} permissions={pricePermissions(() => true)} onWritten={vi.fn()} />);
    const row = await rowOf('3 cuotas');
    await user.click(within(row).getByRole('button', { name: 'Editar 3 cuotas por markup' }));
    expect(within(row).getByRole('textbox', { name: '3 cuotas markup objetivo' })).toHaveValue('20,1');
    expect(within(row).getByRole('button', { name: 'Por markup' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/fijar su markup/)).toBeInTheDocument();
  });

  it('read-only users get no markup editor', async () => {
    render(<ProductPrices productItemId={4101} />);
    await rowOf('Clásica');
    expect(screen.queryByRole('button', { name: /por markup/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/fijar su markup/)).not.toBeInTheDocument();
  });
});
