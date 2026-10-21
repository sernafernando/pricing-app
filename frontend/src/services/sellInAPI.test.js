import { describe, it, expect, beforeEach, vi } from 'vitest';
import api from './api';
import { sellInAPI, sellInBonosAPI } from './sellInAPI';

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

  it('searches Compras operations, sending the linked ones as a repeated query parameter', () => {
    sellInAPI.operaciones({ q: 'tp', proveedor_id: 7, moneda: 'USD', excluir: [15, 16] });
    expect(api.get).toHaveBeenCalledWith('/sell-in/compras/operaciones', {
      params: { q: 'tp', proveedor_id: 7, moneda: 'USD', excluir: [15, 16] },
      paramsSerializer: { indexes: null },
    });
  });

  it("reads one Compras operation's products for the picker's popover", () => {
    sellInAPI.operacionProductos(16);
    expect(api.get).toHaveBeenCalledWith('/sell-in/compras/operaciones/16/productos');
  });

  it('asks the prefill of several operations as a repeated query parameter', () => {
    sellInAPI.prefill([15, 16]);
    expect(api.get).toHaveBeenCalledWith('/sell-in/compras/prefill', {
      params: { pedido_compra_ids: [15, 16] },
      paramsSerializer: { indexes: null },
    });
  });

  it('voids without a reason as an empty one', () => {
    sellInAPI.anular(5, '  ');
    expect(api.post).toHaveBeenCalledWith('/sell-in/compras/5/anular', { motivo: null });
  });

  it('lists, reads, creates, edits and voids brand bonuses, and reads what one reaches', () => {
    sellInBonosAPI.listar({ page: 2, page_size: 10 });
    sellInBonosAPI.detalle(3);
    sellInBonosAPI.alcance(3);
    sellInBonosAPI.crear({ marca: 'TP-LINK' });
    sellInBonosAPI.editar(3, { marca: 'TP-LINK' });
    sellInBonosAPI.anular(3, '  mal cargado ');
    sellInBonosAPI.anular(4, '   ');
    expect(api.get).toHaveBeenCalledWith('/sell-in/bonos', { params: { page: 2, page_size: 10 } });
    expect(api.get).toHaveBeenCalledWith('/sell-in/bonos/3');
    expect(api.get).toHaveBeenCalledWith('/sell-in/bonos/3/alcance');
    expect(api.post).toHaveBeenCalledWith('/sell-in/bonos', { marca: 'TP-LINK' });
    expect(api.put).toHaveBeenCalledWith('/sell-in/bonos/3', { marca: 'TP-LINK' });
    expect(api.post).toHaveBeenCalledWith('/sell-in/bonos/3/anular', { motivo: 'mal cargado' });
    expect(api.post).toHaveBeenCalledWith('/sell-in/bonos/4/anular', { motivo: null });
  });
});
