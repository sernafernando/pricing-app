/**
 * SellOutConsumos: what a sell-out campaign credited, sale line by sale line (`GET /{id}/consumos`, T8d).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CONSUMOS_USD } from './sellOutFixtures';
import SellOutConsumos from './SellOutConsumos';

vi.mock('../../services/sellOutAPI', () => ({ sellOutAPI: { consumos: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe('SellOutConsumos', () => {
  it('lists each credited sale line with its channel, product, units, amount and ARS conversion', async () => {
    sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
    render(<SellOutConsumos campanaId={55} />);

    const venta = (await screen.findByText('Epson EcoTank L8180')).closest('tr');
    expect(sellOutAPI.consumos).toHaveBeenCalledWith(55, { page: 1, page_size: 25 });
    expect(venta).toHaveTextContent('20/10/2026');
    expect(venta).toHaveTextContent('Mercado Libre');
    expect(venta).toHaveTextContent('C13T00R120');
    expect(venta).toHaveTextContent('USD 72,00');
    expect(venta).toHaveTextContent('1.415,50');
    expect(venta).toHaveTextContent('$ 101.916,00');
    // A return netted into its sale: negative units and amount; a product without description shows its id.
    const devolucion = screen.getByText('Fuera de ML').closest('tr');
    expect(devolucion).toHaveTextContent('-1');
    expect(devolucion).toHaveTextContent('USD -36,00');
    expect(devolucion).toHaveTextContent('Producto 4172');
    expect(screen.getByText(/estimados con el dólar BNA/)).toBeInTheDocument();
  });

  it('pages through the lines', async () => {
    const user = userEvent.setup();
    sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
    render(<SellOutConsumos campanaId={55} />);
    await screen.findByText('Epson EcoTank L8180');
    await user.click(screen.getByRole('button', { name: /siguiente/i }));
    await waitFor(() => expect(sellOutAPI.consumos).toHaveBeenLastCalledWith(55, { page: 2, page_size: 25 }));
  });

  it('an ARS campaign has no conversion columns; no lines says so; an error shows', async () => {
    sellOutAPI.consumos.mockResolvedValueOnce({ data: { ...CONSUMOS_USD, moneda: 'ARS', ars_estimado: false, items: [], total: 0 } });
    const { unmount } = render(<SellOutConsumos campanaId={60} />);
    expect(await screen.findByText('Todavía no hay ventas acreditadas.')).toBeInTheDocument();
    expect(screen.queryByText('Monto en pesos')).not.toBeInTheDocument();
    unmount();

    sellOutAPI.consumos.mockRejectedValueOnce({ response: { data: { detail: 'Campaña no encontrada' } } });
    render(<SellOutConsumos campanaId={99} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Campaña no encontrada');
  });
});
