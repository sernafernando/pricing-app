import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { sellInAPI } from '../services/sellInAPI';
import { COMPRA_AIR_TP_ARS, COMPRA_ARS, COMPRA_USD_ANULADA } from '../components/sellIn/sellInFixtures';
import SellInDetailPanel from '../components/sellIn/SellInDetailPanel';

// Sell in incident 2026-11-24, S3 (#2381 precedent): a purchase's amount as loaded, in its invoice's currency, with its
// USD equivalent below when it is in ARS, so USD costs stay visible in USD (owner L35).

vi.mock('../services/sellInAPI', () => ({
  sellInAPI: { detalle: vi.fn(), anular: vi.fn(), aprobar: vi.fn() },
}));

beforeEach(() => vi.clearAllMocks());

const montoTotal = async (compra) => {
  sellInAPI.detalle.mockResolvedValue({ data: compra });
  render(<SellInDetailPanel compraId={compra.id} puedeGestionar={false} onChanged={vi.fn()} onClose={vi.fn()} />);
  return (await screen.findByText('Monto total')).closest('div').querySelector('dd');
};

describe('Sell in purchase amount and its currency', () => {
  it('shows an ARS amount as loaded with its USD equivalent at the purchase rate below', async () => {
    const dd = await montoTotal(COMPRA_AIR_TP_ARS);
    expect(dd).toHaveTextContent('$ 393.467,14');
    expect(screen.getByText('USD 250,62 a TC 1.570')).toBeInTheDocument();
  });

  it('shows a USD amount alone (kept)', async () => {
    const dd = await montoTotal(COMPRA_USD_ANULADA);
    expect(dd).toHaveTextContent(/^USD 2,00$/);
  });

  it('shows an ARS amount with no rate alone (kept)', async () => {
    const dd = await montoTotal(COMPRA_ARS);
    expect(dd).toHaveTextContent(/^\$ 1\.000,00$/);
  });
});
