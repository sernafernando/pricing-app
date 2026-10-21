import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import api from '../services/api';
import { exportVentasCsv, fetchCsvText, filenameFromDisposition } from './ventasMlExport';

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

describe('fetchCsvText', () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it('reads the export as text, with the server filename unless one is given', async () => {
    api.get.mockResolvedValue({ data: new Blob(['A;B\n1;2\n']), headers: { 'content-disposition': 'attachment; filename="m.csv"' } });
    await expect(fetchCsvText('/x/export', { a: 1 })).resolves.toEqual({ text: 'A;B\n1;2\n', filename: 'm.csv' });
    expect(api.get).toHaveBeenCalledWith('/x/export', { params: { a: 1 }, responseType: 'blob' });
    await expect(fetchCsvText('/x/export', {}, { filename: 'own.csv' })).resolves.toMatchObject({ filename: 'own.csv' });
  });

  it('fails with the backend message, like the download', async () => {
    const body = JSON.stringify({ detail: 'consulta_lenta' });
    api.get.mockRejectedValue({ response: { status: 503, data: new Blob([body]) } });
    await expect(fetchCsvText('/x/export', {}, { genericError: 'Falló.' })).rejects.toThrow('consulta_lenta');
  });

  it('falls back to the given generic message', async () => {
    api.get.mockRejectedValue(new Error('network'));
    await expect(fetchCsvText('/x/export', {}, { genericError: 'Falló.' })).rejects.toThrow('Falló.');
  });
});
