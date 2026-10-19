import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import api from '../../services/api';
import { canExportVista, exportFilename, exportPublicacionesCsv } from '../publicacionesMlExport';

describe('exportFilename', () => {
  it('names the file after the view and the local day', () => {
    expect(exportFilename('publicacion', new Date(2026, 9, 5, 23, 30))).toBe('publicaciones-ml-publicacion-2026-10-05.csv');
    expect(exportFilename('producto', new Date(2026, 0, 31))).toBe('publicaciones-ml-producto-2026-01-31.csv');
  });
});

describe('canExportVista', () => {
  it('exports the Publicación and Producto views, never the Agrupado tree', () => {
    expect(canExportVista('publicacion')).toBe(true);
    expect(canExportVista('producto')).toBe(true);
    expect(canExportVista('agrupado')).toBe(false);
  });
});

describe('exportPublicacionesCsv', () => {
  let click;
  let downloaded;

  beforeEach(() => {
    api.get.mockReset();
    URL.createObjectURL = vi.fn(() => 'blob:fake');
    URL.revokeObjectURL = vi.fn();
    downloaded = [];
    click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function record() {
      downloaded.push(this.download);
    });
  });

  afterEach(() => {
    click.mockRestore();
  });

  const ok = () =>
    api.get.mockResolvedValue({
      data: new Blob(['a;b']),
      headers: { 'content-disposition': 'attachment; filename="publicaciones-ml-items-2026-10-19.csv"' },
    });

  it('asks the Publicación view for /view/items/export with the given params, as a blob', async () => {
    ok();
    await exportPublicacionesCsv('publicacion', { estado: 'active', orden: 'precio', dir: 'asc' });
    expect(api.get).toHaveBeenCalledWith('/ml-publications/view/items/export', {
      params: { estado: 'active', orden: 'precio', dir: 'asc' },
      responseType: 'blob',
    });
    expect(click).toHaveBeenCalledTimes(1);
    expect(downloaded[0]).toMatch(/^publicaciones-ml-publicacion-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake');
  });

  it('asks the Producto view for /view/products/export', async () => {
    ok();
    await exportPublicacionesCsv('producto', { orden: 'facturado_30d', dir: 'desc' });
    expect(api.get).toHaveBeenCalledWith('/ml-publications/view/products/export', {
      params: { orden: 'facturado_30d', dir: 'desc' },
      responseType: 'blob',
    });
    expect(downloaded[0]).toMatch(/^publicaciones-ml-producto-\d{4}-\d{2}-\d{2}\.csv$/);
  });

  it('refuses the Agrupado view without asking anything', async () => {
    await expect(exportPublicacionesCsv('agrupado', {})).rejects.toThrow();
    expect(api.get).not.toHaveBeenCalled();
  });

  it.each([
    [422, 'Son 12000 publicaciones (máximo 10000). Acotá los filtros.'],
    [503, 'La consulta tardó demasiado.'],
    [403, 'No tenés permiso.'],
  ])('turns a %i into the backend message (the error body arrives as a blob)', async (status, message) => {
    const body = JSON.stringify({ error: { code: 'X', message } });
    api.get.mockRejectedValue({ response: { status, data: new Blob([body]) } });
    await expect(exportPublicacionesCsv('publicacion', {})).rejects.toThrow(message);
    expect(click).not.toHaveBeenCalled();
  });

  it('uses a generic message of its own when the failure has no readable body', async () => {
    api.get.mockRejectedValue(new Error('network'));
    await expect(exportPublicacionesCsv('producto', {})).rejects.toThrow('No se pudo exportar las publicaciones.');
  });
});
