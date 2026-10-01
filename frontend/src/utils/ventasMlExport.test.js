import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import api from '../services/api';
import { exportVentasCsv, filenameFromDisposition } from './ventasMlExport';

describe('filenameFromDisposition', () => {
  it('reads the server filename', () => {
    expect(filenameFromDisposition('attachment; filename="ventas-ml-20260930-2230.csv"')).toBe(
      'ventas-ml-20260930-2230.csv',
    );
  });

  it('falls back to a sensible name', () => {
    expect(filenameFromDisposition(undefined)).toBe('ventas-ml.csv');
    expect(filenameFromDisposition('inline')).toBe('ventas-ml.csv');
  });
});

describe('exportVentasCsv', () => {
  let click;

  beforeEach(() => {
    api.get.mockReset();
    URL.createObjectURL = vi.fn(() => 'blob:fake');
    URL.revokeObjectURL = vi.fn();
    click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    click.mockRestore();
  });

  it('requests the export with the given params as a blob and downloads it', async () => {
    api.get.mockResolvedValue({
      data: new Blob(['a,b']),
      headers: { 'content-disposition': 'attachment; filename="x.csv"' },
    });
    await exportVentasCsv({ only_alerts: true });
    expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales/export', {
      params: { only_alerts: true },
      responseType: 'blob',
    });
    expect(click).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake');
  });

  it('turns a failed export into the backend message (the error body arrives as a blob)', async () => {
    const body = JSON.stringify({ error: { code: 'VALIDATION_ERROR', message: 'Son 20000 ventas. Acotá los filtros.' } });
    api.get.mockRejectedValue({ response: { status: 422, data: new Blob([body]) } });
    await expect(exportVentasCsv({})).rejects.toThrow('Son 20000 ventas. Acotá los filtros.');
    expect(click).not.toHaveBeenCalled();
  });

  it('uses a generic message when the failure has no readable body', async () => {
    api.get.mockRejectedValue(new Error('network'));
    await expect(exportVentasCsv({})).rejects.toThrow('No se pudo exportar las ventas.');
  });
});
