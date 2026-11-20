import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import useStockAudit from './useStockAudit';
import { publicacionesMlAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  publicacionesMlAPI: { items: vi.fn(), stockAudit: vi.fn() },
}));

const FILTERS = {
  q: '', familia: '', evento_desde: '', estado: ['active'], estado_excluir: [], tiendas: [], marcas: [], categorias: [],
  subcategorias: [], pms: [], tipo: [], vinculo: [], stock: [], evento: [], markup_neg: '', markup_min: '',
  markup_max: '', orden: '', dir: '', pagina: 1, limite: 50, abiertos: '',
};

const setup = () =>
  renderHook(
    ({ filters }) =>
      useStockAudit({ filters, pageSize: 50, canSeeSales: true, canSeeMargin: true, enabled: true, expanded: [], onExpandedChange: () => {} }),
    { initialProps: { filters: FILTERS } },
  );

beforeEach(() => {
  publicacionesMlAPI.stockAudit.mockReset();
  publicacionesMlAPI.stockAudit.mockReturnValue(new Promise(() => {}));
});

describe('useStockAudit cancellation (pubml-lentitud S3)', () => {
  it('a new list aborts the audit request the old one still has in flight', async () => {
    const { rerender } = setup();
    await waitFor(() => expect(publicacionesMlAPI.stockAudit).toHaveBeenCalledTimes(1));
    const old = publicacionesMlAPI.stockAudit.mock.calls[0][1].signal;
    expect(old.aborted).toBe(false);
    rerender({ filters: { ...FILTERS, estado: ['paused'] } });
    await waitFor(() => expect(publicacionesMlAPI.stockAudit).toHaveBeenCalledTimes(2));
    expect(old.aborted).toBe(true);
    expect(publicacionesMlAPI.stockAudit.mock.calls[1][1].signal.aborted).toBe(false);
  });

  it('an old answer that lands anyway never replaces the new list', async () => {
    let settleOld;
    publicacionesMlAPI.stockAudit
      .mockReturnValueOnce(new Promise((resolve) => { settleOld = resolve; }))
      .mockResolvedValueOnce({ data: { rows: [{ key: 'new' }], total: 1 } });
    const { result, rerender } = setup();
    await waitFor(() => expect(publicacionesMlAPI.stockAudit).toHaveBeenCalledTimes(1));
    rerender({ filters: { ...FILTERS, estado: ['paused'] } });
    await waitFor(() => expect(result.current.data?.total).toBe(1));
    settleOld({ data: { rows: [], total: 99 } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(result.current.data.total).toBe(1);
  });
});
