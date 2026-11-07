/**
 * tacticalRenovar: a tactical's detail (`GET /tacticals/{id}`, one line per child) as the Nuevo tactical screen's
 * values, for Renovar (tacticals F1): same type, lines, values and caps; new dates to pick.
 */
import { describe, it, expect } from 'vitest';
import { TACTICAL_BPS, TACTICAL_REBATE } from '../tacticals/tacticalsFixtures';
import { cuerpoDe, problemaDe } from './tacticalLineas';
import { renovacionDe } from './tacticalRenovar';

describe('renovacionDe', () => {
  it('copies the header but the dates, which the user picks again', () => {
    const { form } = renovacionDe({ ...TACTICAL_BPS, nota: 'Acuerdo por mail', incluye_iva: true });

    expect(form).toEqual({
      tipo: 'sell_out',
      nombre: 'Tacticals BPS Noviembre Q1FY27',
      marca: 'HP',
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
      },
    ]);
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
