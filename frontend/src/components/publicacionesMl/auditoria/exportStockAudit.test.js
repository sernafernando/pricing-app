import { describe, it, expect, vi } from 'vitest';
import { exportAuditoriaStockExcel } from './exportStockAudit';
import { downloadCsv } from '../../../utils/ventasMlExport';

vi.mock('../../../utils/ventasMlExport', () => ({ downloadCsv: vi.fn() }));

describe('exportAuditoriaStockExcel (auditoria-stock L7)', () => {
  it("downloads the audit's workbook with its params and the server's file name", async () => {
    downloadCsv.mockResolvedValue(undefined);
    await exportAuditoriaStockExcel({ q: 'x', orden: 'valor_total', dir: 'desc' });
    expect(downloadCsv).toHaveBeenCalledWith(
      '/ml-publications/view/stock-audit/export',
      { q: 'x', orden: 'valor_total', dir: 'desc' },
      { genericError: 'No se pudo exportar la auditoría de stock.' },
    );
  });

  it('passes a refusal on', async () => {
    downloadCsv.mockRejectedValue(new Error('Sin permiso'));
    await expect(exportAuditoriaStockExcel({})).rejects.toThrow('Sin permiso');
  });
});
