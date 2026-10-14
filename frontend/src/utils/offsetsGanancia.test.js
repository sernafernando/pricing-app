/**
 * The cost offsets Productos applies to its "markup con offsets" (the "→ X%"
 * beside the clásica markup), as pure functions so the Publicaciones ML
 * Precios tab shows exactly the same figures.
 */
import { describe, it, expect, vi } from 'vitest';
import { cargarOffsetsVigentes, costoConOffset, markupConOffset, offsetsSinLimite, requiereTipoCambio } from './offsetsGanancia';

const PRODUCTO = {
  item_id: 4101,
  marca: 'TP-LINK',
  categoria: 'ROUTERS',
  subcategoria_id: 55,
  moneda_costo: 'ARS',
  costo: 64000,
  markup: 18.4,
};

const offset = (fields) => ({
  id: 1,
  marca: null,
  categoria: null,
  subcategoria_id: null,
  item_id: null,
  grupo_id: null,
  tipo_offset: 'porcentaje_costo',
  porcentaje: null,
  monto: null,
  moneda: 'ARS',
  descripcion: null,
  max_unidades: null,
  max_monto_usd: null,
  ...fields,
});

const ctx = (offsets, extra = {}) => ({ offsets, grupoFiltros: {}, tipoCambio: 1000, ...extra });

describe('offsetsSinLimite', () => {
  it('keeps only uncapped porcentaje_costo and monto_por_unidad offsets', () => {
    const kept = offsetsSinLimite([
      offset({ id: 1, tipo_offset: 'porcentaje_costo' }),
      offset({ id: 2, tipo_offset: 'monto_por_unidad' }),
      offset({ id: 3, tipo_offset: 'monto_fijo' }),
      offset({ id: 4, tipo_offset: 'porcentaje_costo', max_unidades: 10 }),
      offset({ id: 5, tipo_offset: 'monto_por_unidad', max_monto_usd: 500 }),
    ]);
    expect(kept.map((o) => o.id)).toEqual([1, 2]);
  });

  it('tolerates a missing list', () => {
    expect(offsetsSinLimite(undefined)).toEqual([]);
  });
});

describe('costoConOffset', () => {
  it('discounts a percentage of the cost and lists the offset that applied', () => {
    const result = costoConOffset(
      PRODUCTO,
      ctx([offset({ id: 7, marca: 'TP-LINK', porcentaje: 10, descripcion: 'Rebate TP-Link' })]),
    );
    expect(result).toEqual({
      costoARS: 64000,
      descuento: 6400,
      costoAjustado: 57600,
      aplicados: [{ id: 7, descripcion: 'Rebate TP-Link', monto: 6400 }],
    });
  });

  it('adds a per-unit amount, converting a USD amount with the rate', () => {
    const result = costoConOffset(
      PRODUCTO,
      ctx([offset({ id: 8, item_id: 4101, tipo_offset: 'monto_por_unidad', monto: 2, moneda: 'USD' })], { tipoCambio: 1200 }),
    );
    expect(result.descuento).toBe(2400);
    expect(result.costoAjustado).toBe(61600);
    expect(result.aplicados).toEqual([{ id: 8, descripcion: null, monto: 2400 }]);
  });

  it('converts a USD cost to ARS before discounting', () => {
    const result = costoConOffset(
      { ...PRODUCTO, moneda_costo: 'USD', costo: 50 },
      ctx([offset({ categoria: 'ROUTERS', porcentaje: 20 })], { tipoCambio: 1000 }),
    );
    expect(result.costoARS).toBe(50000);
    expect(result.costoAjustado).toBe(40000);
  });

  it('matches an individual offset by item, subcategory, category or brand', () => {
    const matches = (fields) => costoConOffset(PRODUCTO, ctx([offset({ porcentaje: 5, ...fields })])) !== null;
    expect(matches({ item_id: 4101 })).toBe(true);
    expect(matches({ subcategoria_id: 55 })).toBe(true);
    expect(matches({ categoria: 'ROUTERS' })).toBe(true);
    expect(matches({ marca: 'TP-LINK' })).toBe(true);
    expect(matches({ marca: 'OTRA' })).toBe(false);
    expect(matches({ item_id: 9999 })).toBe(false);
  });

  it('matches a group offset when ANY of its filters matches every field it sets', () => {
    const grupo = offset({ grupo_id: 3, porcentaje: 10 });
    const withFiltros = (filtros) => costoConOffset(PRODUCTO, ctx([grupo], { grupoFiltros: { 3: filtros } }));
    expect(withFiltros([{ marca: 'OTRA' }, { marca: 'TP-LINK', categoria: 'ROUTERS' }])).not.toBeNull();
    expect(withFiltros([{ marca: 'TP-LINK', categoria: 'SWITCHES' }])).toBeNull();
    expect(withFiltros([])).toBeNull();
  });

  it('adds every offset that applies', () => {
    const result = costoConOffset(
      PRODUCTO,
      ctx([
        offset({ id: 1, marca: 'TP-LINK', porcentaje: 10, descripcion: 'Marca' }),
        offset({ id: 2, item_id: 4101, tipo_offset: 'monto_por_unidad', monto: 600, descripcion: 'Item' }),
      ]),
    );
    expect(result.descuento).toBe(7000);
    expect(result.costoAjustado).toBe(57000);
    expect(result.aplicados.map((a) => a.descripcion)).toEqual(['Marca', 'Item']);
  });

  it('is null without a positive cost, without matching offsets, or when they add up to 0', () => {
    expect(costoConOffset({ ...PRODUCTO, costo: 0 }, ctx([offset({ marca: 'TP-LINK', porcentaje: 10 })]))).toBeNull();
    expect(costoConOffset({ ...PRODUCTO, costo: null }, ctx([offset({ marca: 'TP-LINK', porcentaje: 10 })]))).toBeNull();
    expect(costoConOffset(PRODUCTO, ctx([]))).toBeNull();
    expect(costoConOffset(PRODUCTO, ctx([offset({ marca: 'TP-LINK', porcentaje: 0 })]))).toBeNull();
  });

  it('with a channel, skips the offsets that do not apply to it; without one, counts them all (Productos)', () => {
    const offsets = [
      offset({ id: 1, marca: 'TP-LINK', porcentaje: 10, aplica_ml: false }),
      offset({ id: 2, marca: 'TP-LINK', porcentaje: 5, aplica_ml: true }),
      offset({ id: 3, marca: 'TP-LINK', porcentaje: 1 }),
    ];
    expect(costoConOffset(PRODUCTO, { ...ctx(offsets), canal: 'ml' }).aplicados.map((a) => a.id)).toEqual([2, 3]);
    expect(costoConOffset(PRODUCTO, ctx(offsets)).aplicados.map((a) => a.id)).toEqual([1, 2, 3]);
    expect(costoConOffset(PRODUCTO, { ...ctx([offsets[0]]), canal: 'ml' })).toBeNull();
  });

  it('is null when the offsets leave no cost', () => {
    expect(costoConOffset(PRODUCTO, ctx([offset({ marca: 'TP-LINK', porcentaje: 100 })]))).toBeNull();
  });
});

describe('requiereTipoCambio', () => {
  const usd = offset({ id: 2, item_id: 4101, tipo_offset: 'monto_por_unidad', monto: 2, moneda: 'USD' });

  it('needs a rate for a USD cost', () => {
    expect(requiereTipoCambio({ ...PRODUCTO, moneda_costo: 'USD' }, ctx([]))).toBe(true);
  });

  it('needs a rate for a USD per-unit offset that reaches the product on the channel', () => {
    expect(requiereTipoCambio(PRODUCTO, ctx([usd]))).toBe(true);
    expect(requiereTipoCambio(PRODUCTO, { ...ctx([{ ...usd, aplica_ml: false }]), canal: 'ml' })).toBe(false);
    expect(requiereTipoCambio(PRODUCTO, ctx([{ ...usd, item_id: 9999 }]))).toBe(false);
  });

  it('needs none for an ARS cost with ARS or percentage offsets', () => {
    expect(requiereTipoCambio(PRODUCTO, ctx([offset({ marca: 'TP-LINK', porcentaje: 10 }), { ...usd, moneda: 'ARS' }]))).toBe(false);
  });
});

describe('markupConOffset', () => {
  it('recomputes the markup over the adjusted cost, rounded to 2 decimals', () => {
    // limpio = 1.184 * 64000 = 75776; 75776 / 57600 - 1 = 31.555...%
    expect(markupConOffset(18.4, { costoARS: 64000, costoAjustado: 57600 })).toBe(31.56);
  });

  it('keeps a 0 markup as a real value', () => {
    expect(markupConOffset(0, { costoARS: 100, costoAjustado: 80 })).toBe(25);
  });

  it('turns a negative markup less negative (or positive) with the offset', () => {
    expect(markupConOffset(-2, { costoARS: 64000, costoAjustado: 57600 })).toBe(8.89);
  });

  it('is null without a markup or without an offset cost', () => {
    expect(markupConOffset(null, { costoARS: 100, costoAjustado: 80 })).toBeNull();
    expect(markupConOffset('', { costoARS: 100, costoAjustado: 80 })).toBeNull();
    expect(markupConOffset(undefined, { costoARS: 100, costoAjustado: 80 })).toBeNull();
    expect(markupConOffset(18.4, null)).toBeNull();
  });
});

describe('cargarOffsetsVigentes', () => {
  it('reads the current offsets, the rate and the filters of every group used', async () => {
    const fetchers = {
      offsets: vi.fn().mockResolvedValue({
        data: [
          offset({ id: 1, grupo_id: 3 }),
          offset({ id: 2, grupo_id: 3 }),
          offset({ id: 3, marca: 'X' }),
          offset({ id: 4, tipo_offset: 'monto_fijo', grupo_id: 9 }),
        ],
      }),
      tipoCambio: vi.fn().mockResolvedValue({ data: { tipo_cambio: 1350 } }),
      grupoFiltros: vi.fn().mockResolvedValue({ data: [{ marca: 'TP-LINK' }] }),
    };
    const loaded = await cargarOffsetsVigentes(fetchers);
    expect(loaded.tipoCambio).toBe(1350);
    expect(loaded.offsets.map((o) => o.id)).toEqual([1, 2, 3]);
    expect(fetchers.grupoFiltros).toHaveBeenCalledTimes(1);
    expect(fetchers.grupoFiltros).toHaveBeenCalledWith(3);
    expect(loaded.grupoFiltros).toEqual({ 3: [{ marca: 'TP-LINK' }] });
  });

  it('keeps the other offsets when the group filters cannot be read (group offsets then match nothing)', async () => {
    const fetchers = {
      offsets: vi.fn().mockResolvedValue({ data: [offset({ id: 1, grupo_id: 3 }), offset({ id: 2, marca: 'X' })] }),
      tipoCambio: vi.fn().mockResolvedValue({ data: { tipo_cambio: 1100 } }),
      grupoFiltros: vi.fn().mockRejectedValue(new Error('Network Error')),
    };
    const loaded = await cargarOffsetsVigentes(fetchers);
    expect(loaded.offsets.map((o) => o.id)).toEqual([1, 2]);
    expect(loaded.grupoFiltros).toEqual({});
    expect(loaded.tipoCambio).toBe(1100);
  });

  it('without a rate fetcher reads no rate and assumes none (no 1000 fallback)', async () => {
    const loaded = await cargarOffsetsVigentes({ offsets: vi.fn().mockResolvedValue({ data: [] }), grupoFiltros: vi.fn() });
    expect(loaded.tipoCambio).toBeNull();
  });

  it('falls back to 1000 without a rate and asks no group filters without groups', async () => {
    const fetchers = {
      offsets: vi.fn().mockResolvedValue({ data: [] }),
      tipoCambio: vi.fn().mockResolvedValue({ data: {} }),
      grupoFiltros: vi.fn(),
    };
    const loaded = await cargarOffsetsVigentes(fetchers);
    expect(loaded).toEqual({ offsets: [], grupoFiltros: {}, tipoCambio: 1000 });
    expect(fetchers.grupoFiltros).not.toHaveBeenCalled();
  });
});
