/**
 * tacticalRenovar: a tactical's detail (`GET /tacticals/{id}`, one line per child) as the Nuevo tactical screen's
 * values, for Renovar (tacticals F1): same type, lines, values and caps; new dates to pick.
 */
import { describe, it, expect } from 'vitest';
import { TACTICAL_BPS, TACTICAL_REBATE } from '../tacticals/tacticalsFixtures';
import { cuerpoDe, problemaDe } from './tacticalLineas';
import { conFacturas, edicionDe, impactoDe, renovacionDe } from './tacticalRenovar';

describe('renovacionDe', () => {
  it('copies the header but the dates, which the user picks again', () => {
    const { form } = renovacionDe({ ...TACTICAL_BPS, nota: 'Acuerdo por mail', incluye_iva: true });

    expect(form).toEqual({
      tipo: 'sell_out',
      nombre: 'Tacticals BPS Noviembre Q1FY27',
      marcas: ['HP'], // a tactical read before S3 has only `marca`
      referencia: 'Q1 FY27 · BPS',
      fechaDesde: '',
      fechaHasta: '',
      moneda: 'USD',
      tcModo: 'al_cobro',
      tipoCambio: '',
      incluyeIva: true,
      acumulable: true,
      todasTiendas: true,
      topeCompartido: false,
      tiendaKeys: [],
      nota: 'Acuerdo por mail',
    });
  });

  it('joins the children of a per-product line back into one line, and keeps a shared line shared', () => {
    const { lineas } = renovacionDe(TACTICAL_BPS);

    expect(lineas.map((l) => ({ ...l, id: undefined }))).toEqual([
      {
        alcance: 'productos',
        productos: [
          { item_id: 101, codigo: 'AIO-G2-R5', descripcion: 'AIO HP G2 R5 16G 512 W11H' },
          { item_id: 102, codigo: 'NB-250RG10', descripcion: 'Notebook HP 250RG10 5-120U' },
        ],
        facturas: [],
        marca: '',
        categoria: '',
        monto: '220',
        modo: 'por_unidad',
        topeUnidades: '90',
        topeMonto: '',
        compartido: false,
        reparto: '',
      },
      {
        alcance: 'productos',
        productos: [
          { item_id: 201, codigo: 'MON-V24I', descripcion: 'Monitor V24i G5' },
          { item_id: 202, codigo: 'MON-V27I', descripcion: 'Monitor V27i G5' },
        ],
        facturas: [],
        marca: '',
        categoria: '',
        monto: '12',
        modo: 'por_unidad',
        topeUnidades: '300',
        topeMonto: '3000',
        compartido: true,
        reparto: '',
      },
    ]);
  });

  it('copies every brand of a tactical with several (S3)', () => {
    const { form } = renovacionDe({ ...TACTICAL_BPS, marca: 'HP', marcas: ['HP', 'TP-Link'] });

    expect(form.marcas).toEqual(['HP', 'TP-Link']);
  });

  it('writes decimals the way the screen reads them, so the POST sends the same values', () => {
    const renovado = renovacionDe(TACTICAL_REBATE);
    const [linea] = renovado.lineas;

    expect((({ alcance, marca, monto, modo }) => ({ alcance, marca, monto, modo }))(linea)).toEqual({
      alcance: 'marca',
      marca: 'HP',
      monto: '3,5',
      modo: 'porcentaje',
    });
    const form = { ...renovado.form, fechaDesde: '2027-02-01', fechaHasta: '2027-04-30' };
    expect(cuerpoDe(form, renovado.lineas).body.lineas).toEqual([
      { alcance: 'marca', marca: 'HP', modo_monto: 'porcentaje', valor: 3.5, tope_unidades: null, tope_monto: null },
    ]);
  });

  it('keeps the split criterion of a sell out total amount, and posts it again (S1)', () => {
    const tactical = {
      ...TACTICAL_BPS,
      lineas: [{ ...TACTICAL_BPS.lineas[2], modo_monto: 'monto_total', valor: '1200', tope_unidades: null, tope_monto: null, reparto_criterio: 'unidades' }],
    };

    const renovado = renovacionDe(tactical);

    expect(renovado.lineas[0]).toMatchObject({ modo: 'monto_total', monto: '1200', reparto: 'unidades' });
    const form = { ...renovado.form, fechaDesde: '2027-02-01', fechaHasta: '2027-04-30' };
    expect(cuerpoDe(form, renovado.lineas).body.lineas).toEqual([
      { alcance: 'productos', item_ids: [201, 202], modo_monto: 'monto_total', valor: 1200, tope_unidades: null, tope_monto: null, reparto_criterio: 'unidades' },
    ]);
  });

  it('renews a sell in total amount with its criterion, and a USD one with the USD amount it was loaded with (S4)', () => {
    const total = { ...TACTICAL_REBATE.lineas[0], modo_monto: 'monto_total', valor: '300000', reparto_criterio: 'iguales' };
    const enPesos = renovacionDe({ ...TACTICAL_REBATE, lineas: [total] });
    expect(enPesos.lineas[0]).toMatchObject({ alcance: 'marca', modo: 'monto_total', monto: '300000', reparto: 'iguales' });

    const enDolares = renovacionDe({
      ...TACTICAL_REBATE,
      moneda: 'USD',
      tc_modo: 'fijo',
      tipo_cambio: '1000.5',
      lineas: [{ ...total, valor: '1200610.01', valor_usd: '1200.01' }],
    });
    expect(enDolares.form).toMatchObject({ moneda: 'USD', tcModo: 'fijo', tipoCambio: '1000,5' });
    expect(enDolares.lineas[0]).toMatchObject({ modo: 'monto_total', monto: '1200,01', reparto: 'iguales' });
    const form = { ...enDolares.form, fechaDesde: '2027-02-01', fechaHasta: '2027-04-30' };
    expect(cuerpoDe(form, enDolares.lineas).body.lineas).toEqual([
      { alcance: 'marca', marca: 'HP', modo_monto: 'monto_total', valor: 1200.01, tope_unidades: null, tope_monto: null, reparto_criterio: 'iguales' },
    ]);
  });

  it('leaves an invoice line without its invoice: the old one already got its bonus', () => {
    const tactical = {
      ...TACTICAL_REBATE,
      lineas: [{ ...TACTICAL_REBATE.lineas[0], alcance: 'factura', marca: null, pedido_compra_id: 9, pedido_numero: '16' }],
    };

    const { form, lineas } = renovacionDe(tactical);

    expect(lineas[0]).toMatchObject({ alcance: 'factura', facturas: [] });
    expect(problemaDe({ ...form, fechaDesde: '2027-02-01', fechaHasta: '2027-04-30' }, lineas)).toMatch(/sin factura/);
  });
});

describe('edicionDe (S8)', () => {
  it('keeps the dates, which the edit replaces in the same tactical', () => {
    const { form, lineas } = edicionDe(TACTICAL_BPS);

    expect([form.fechaDesde, form.fechaHasta]).toEqual(['2026-11-01', '2026-11-30']);
    expect(lineas).toHaveLength(2);
    expect(lineas.map((l) => l.facturas)).toEqual([[], []]);
  });

  it("keeps each invoice line's invoice, and Renovar still leaves it out", () => {
    const factura = { ...TACTICAL_REBATE.lineas[0], alcance: 'factura', pedido_compra_id: 5001, pedido_numero: 'OC-77' };
    const tactical = { ...TACTICAL_REBATE, lineas: [factura] };

    expect(edicionDe(tactical).lineas[0].facturas).toEqual([{ id: 5001, numero: 'OC-77' }]);
    expect(renovacionDe(tactical).lineas[0].facturas).toEqual([]);
  });

  it("keeps the invoices an invoice line was limited to, and the Compras search does not drop them", () => {
    const factura = {
      ...TACTICAL_REBATE.lineas[0],
      alcance: 'factura',
      pedido_compra_id: 5001,
      pedido_numero: 'OC-77',
      facturas_ct: [70002],
      facturas_elegidas: [{ ct_transaction_id: 70002, numero: 'A-0001-124' }],
    };
    const { lineas } = edicionDe({ ...TACTICAL_REBATE, lineas: [factura] });
    const elegida = {
      id: 5001,
      numero: 'OC-77',
      facturasCt: [70002],
      facturasElegidas: [{ ct_transaction_id: 70002, numero: 'A-0001-124' }],
    };
    expect(lineas[0].facturas).toEqual([elegida]);

    const facturas = [
      { ct_transaction_id: 70001, numero: 'A-0001-123', fecha_factura: '2026-11-03' },
      { ct_transaction_id: 70002, numero: 'A-0001-124', fecha_factura: '2026-11-05' },
    ];
    expect(conFacturas(lineas, [{ id: 5001, numero: 'OC-77', facturas }])[0].facturas).toEqual([{ ...elegida, facturas }]);
  });

  it('fills an invoice with what the Compras search found, by id', () => {
    const lineas = [{ id: 'a', facturas: [{ id: 5001, numero: 'OC-77' }] }];
    const encontrada = { id: 5001, numero: 'OC-77', numero_factura: 'A-0001-123', proveedor_nombre: 'TP-Link', fecha: '2026-11-03' };

    expect(conFacturas(lineas, [encontrada, { id: 9 }])[0].facturas).toEqual([encontrada]);
    expect(conFacturas(lineas, [])[0].facturas).toEqual([{ id: 5001, numero: 'OC-77' }]);
  });
});

describe('impactoDe (S8)', () => {
  const form = (cambios = {}) => ({ ...edicionDe(TACTICAL_BPS).form, ...cambios });

  it('adds up what the active lines already applied, per currency', () => {
    const anulada = { ...TACTICAL_BPS.lineas[0], id: 99, estado: 'anulada', monto_usado: '500', unidades_usadas: 5 };
    const tactical = { ...TACTICAL_BPS, lineas: [...TACTICAL_BPS.lineas, anulada] };

    expect(impactoDe(tactical, form())).toEqual({ aplicado: { USD: 20544 }, unidades: 252, tcDescartado: null });
  });

  it('warns that a set al_cobro rate is discarded only when type, currency or FX mode change', () => {
    const conTasa = { ...TACTICAL_BPS, lineas: [{ ...TACTICAL_BPS.lineas[0], tc_al_cobro: '1450.000000' }] };

    expect(impactoDe(conTasa, form()).tcDescartado).toBeNull();
    expect(impactoDe(conTasa, form({ moneda: 'ARS' })).tcDescartado).toBe(1450);
    expect(impactoDe(conTasa, form({ tcModo: 'fijo' })).tcDescartado).toBe(1450);
    expect(impactoDe(conTasa, form({ tipo: 'sell_in' })).tcDescartado).toBe(1450);
  });
});
