import { describe, it, expect, beforeEach, vi } from 'vitest';
import api from './api';
import { sellInAPI } from './sellInAPI';

describe('sellInAPI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists and summarises with the same filters', () => {
    sellInAPI.listar({ aplica: 'si', page: 2 });
    sellInAPI.resumen({ aplica: 'si' });
    expect(api.get).toHaveBeenCalledWith('/sell-in/compras', { params: { aplica: 'si', page: 2 } });
    expect(api.get).toHaveBeenCalledWith('/sell-in/compras/resumen', { params: { aplica: 'si' } });
  });

  it('reads one purchase, previews, creates and voids', () => {
    sellInAPI.detalle(5);
    sellInAPI.preview({ moneda: 'ARS' });
    sellInAPI.crear({ moneda: 'ARS' });
    sellInAPI.anular(5, 'cargada dos veces');
    expect(api.get).toHaveBeenCalledWith('/sell-in/compras/5');
    expect(api.post).toHaveBeenCalledWith('/sell-in/compras/preview', { moneda: 'ARS' });
    expect(api.post).toHaveBeenCalledWith('/sell-in/compras', { moneda: 'ARS' });
    expect(api.post).toHaveBeenCalledWith('/sell-in/compras/5/anular', { motivo: 'cargada dos veces' });
  });

  it('searches suppliers for the picker', () => {
    sellInAPI.proveedores('tp');
    expect(api.get).toHaveBeenCalledWith('/administracion/proveedores', { params: { search: 'tp', page_size: 10 } });
  });

  it('voids without a reason as an empty one', () => {
    sellInAPI.anular(5, '  ');
    expect(api.post).toHaveBeenCalledWith('/sell-in/compras/5/anular', { motivo: null });
  });
});
