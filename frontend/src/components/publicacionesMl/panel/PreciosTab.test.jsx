/**
 * A publication's Precios tab (S2): one table with a row per plan, the reference line with Calcular above it and the
 * rebate, offer and transfer table (with the Tienda Nube price) below. Hard rule (orchestrator, 2026-11-02): "no price
 * appears twice anywhere in the Precios tab, including the reference line and the rebate table".
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PreciosTab from './PreciosTab';
import { offsetsGananciaAPI, preciosAPI, productosAPI } from '../../../services/api';
import { PRODUCTO_CON_REBATE_Y_OFERTA } from '../../pricing/ProductPrices.fixtures';

vi.mock('../../../services/api', () => ({
  preciosAPI: { obtenerProducto: vi.fn(), tipoCambioActual: vi.fn() },
  productosAPI: { listar: vi.fn() },
  offsetsGananciaAPI: { vigentes: vi.fn() },
}));

vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true }),
}));

// The same product as Productos' listing sends it, with its Tienda Nube price.
const LISTED = { ...PRODUCTO_CON_REBATE_Y_OFERTA, tn_price: 99999, tn_has_promotion: false };

const tab = ({ canSeeMargin = false, onCalculate = null, version = 0 } = {}) => (
  <PreciosTab
    detail={{ product: { item_id: PRODUCTO_CON_REBATE_Y_OFERTA.item_id } }}
    canSeeMargin={canSeeMargin}
    onWritten={vi.fn()}
    priceGroup={{ version, onCalculate, tnCardPercent: 10 }}
  />
);
const renderTab = (props) => render(tab(props));

const loaded = async () => {
  await screen.findByRole('table', { name: 'Precios por plan' });
  // The listing's part (Calcular, the Tienda Nube price) arrives on its own request.
  await waitFor(() => expect(screen.getByRole('row', { name: /^Web transferencia/ })).toHaveTextContent('99.999,00'));
};

beforeEach(() => {
  vi.clearAllMocks();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO_CON_REBATE_Y_OFERTA });
  preciosAPI.tipoCambioActual.mockResolvedValue({ data: { venta: 1000 } });
  productosAPI.listar.mockResolvedValue({ data: { productos: [LISTED], total: 1 } });
  offsetsGananciaAPI.vigentes.mockResolvedValue({ data: [] });
});

describe('PreciosTab (S2)', () => {
  it('shows one table, a row per plan, and no separate list group', async () => {
    renderTab();
    await loaded();
    expect(screen.getAllByRole('table', { name: 'Precios por plan' })).toHaveLength(1);
    expect(screen.queryByRole('region', { name: 'Precios de la lista' })).not.toBeInTheDocument();
  });

  it.each([
    ['without', false],
    ['with', true],
  ])('shows no price twice, %s permission to see the cost', async (_, canSeeMargin) => {
    renderTab({ canSeeMargin, onCalculate: vi.fn() });
    await loaded();
    const amounts = document.body.textContent.match(/\$ ?[\d.]+,\d{2}/g) ?? [];
    expect(amounts.length).toBeGreaterThan(8);
    const seen = new Map();
    for (const amount of amounts) seen.set(amount, (seen.get(amount) ?? 0) + 1);
    expect([...seen].filter(([, times]) => times > 1)).toEqual([]);
  });

  it("puts Calcular in the reference line, opening the pricing on the listing's product", async () => {
    const onCalculate = vi.fn();
    renderTab({ onCalculate });
    await loaded();
    const references = screen.getByRole('group', { name: 'Referencias del producto' });
    await userEvent.click(within(references).getByRole('button', { name: /^Calcular el precio de/ }));
    expect(onCalculate).toHaveBeenCalledWith(LISTED);
  });

  it('has no Calcular for who may not price', async () => {
    renderTab({ onCalculate: null });
    await loaded();
    expect(screen.queryByRole('button', { name: /^Calcular/ })).not.toBeInTheDocument();
  });

  it('puts the Tienda Nube price with its transfer price, by the page card surcharge, in the web transfer row', async () => {
    renderTab();
    await loaded();
    expect(screen.getByRole('row', { name: /^Web transferencia/ })).toHaveTextContent('Tienda Nube$ 99.999,00$90.908,18 transf.');
  });

  it("keeps the prices, without Calcular nor the Tienda Nube price, when the listing's request fails", async () => {
    productosAPI.listar.mockRejectedValue(new Error('offline'));
    renderTab({ onCalculate: vi.fn() });
    const table = await screen.findByRole('table', { name: 'Precios por plan' });
    await waitFor(() => expect(productosAPI.listar).toHaveBeenCalled());
    expect(within(table).getByText('$ 98.500,50')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Calcular/ })).not.toBeInTheDocument();
    expect(screen.getByRole('row', { name: /^Web transferencia/ })).not.toHaveTextContent('99.999,00');
  });

  it('drops Calcular and the Tienda Nube price when a later read of the listing fails, keeping the prices', async () => {
    const onCalculate = vi.fn();
    const { rerender } = renderTab({ onCalculate });
    await loaded();
    expect(screen.getByRole('button', { name: /^Calcular el precio de/ })).toBeInTheDocument();
    productosAPI.listar.mockRejectedValue(new Error('offline'));
    // A write elsewhere bumps the list's version: the listing is read again, and fails.
    rerender(tab({ onCalculate, version: 1 }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /^Calcular/ })).not.toBeInTheDocument());
    expect(screen.getByRole('row', { name: /^Web transferencia/ })).not.toHaveTextContent('99.999,00');
    expect(screen.getByRole('table', { name: 'Precios por plan' })).toHaveTextContent('$ 98.500,50');
  });
});
