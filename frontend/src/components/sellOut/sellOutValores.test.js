/**
 * sellOutValores: the campaign form's values to and from the API (`SellOutCampanaIn` / `SellOutCampanaOut`).
 */
import { describe, it, expect } from 'vitest';
import { CAMPANA_MIGRADA, CAMPANA_PORCENTAJE_ANULADA } from './sellOutFixtures';
import { CAMPANA_VACIA, bodyDeCampana, faltantes, valoresDeCampana } from './sellOutValores';

const POR_UNIDAD = {
  ...CAMPANA_VACIA,
  nombre: ' RB 8180 ',
  fechaDesde: '2026-01-01',
  fechaHasta: '2026-12-31',
  montoUnit: '36',
  grupoIds: [301],
};

describe('bodyDeCampana', () => {
  it('a per-unit USD campaign sends its amount and FX mode, and no percentage or rate', () => {
    expect(bodyDeCampana(POR_UNIDAD)).toEqual({
      nombre: 'RB 8180',
      descripcion: null,
      fecha_desde: '2026-01-01',
      fecha_hasta: '2026-12-31',
      tipo: 'por_unidad',
      monto_unit: '36',
      porcentaje: null,
      base_porcentaje: 'costo',
      moneda: 'USD',
      tc_modo: 'al_cobro',
      tipo_cambio: null,
      tope_unidades: null,
      tope_monto: null,
      acumulable: true,
      monto_incluye_iva: false,
      grupo_ids: [301],
    });
  });

  it('a fixed rate is sent only with tc_modo fijo', () => {
    const body = bodyDeCampana({ ...POR_UNIDAD, tcModo: 'fijo', tipoCambio: '1420' });
    expect(body).toMatchObject({ tc_modo: 'fijo', tipo_cambio: '1420' });
    expect(bodyDeCampana({ ...POR_UNIDAD, tcModo: 'al_cobro', tipoCambio: '1420' }).tipo_cambio).toBeNull();
  });

  it('an ARS percentage campaign sends its base and caps, and neither FX field nor amount', () => {
    const body = bodyDeCampana({
      ...POR_UNIDAD,
      tipo: 'porcentaje',
      porcentaje: '2',
      basePorcentaje: 'precio_neto',
      moneda: 'ARS',
      tcModo: 'fijo',
      tipoCambio: '1420',
      topeUnidades: '500',
      topeMonto: '1000000',
    });
    expect(body).toMatchObject({
      tipo: 'porcentaje',
      monto_unit: null,
      porcentaje: '2',
      base_porcentaje: 'precio_neto',
      moneda: 'ARS',
      tc_modo: null,
      tipo_cambio: null,
      tope_unidades: 500,
      tope_monto: '1000000',
    });
  });
});

describe('valoresDeCampana', () => {
  it('reads a stored campaign back into the form, so saving it unchanged sends the same terms', () => {
    const valores = valoresDeCampana(CAMPANA_MIGRADA);
    expect(valores).toMatchObject({ nombre: 'RB 8180', montoUnit: '36.00', tcModo: 'al_cobro', grupoIds: [301] });
    expect(bodyDeCampana(valores)).toMatchObject({ monto_unit: '36.00', tc_modo: 'al_cobro', grupo_ids: [301] });
  });

  it('reads a percentage campaign with caps and flags', () => {
    expect(valoresDeCampana(CAMPANA_PORCENTAJE_ANULADA)).toMatchObject({
      tipo: 'porcentaje',
      porcentaje: '2.0000',
      basePorcentaje: 'precio_neto',
      moneda: 'ARS',
      topeUnidades: '500',
      topeMonto: '1000000.00',
      acumulable: false,
      montoIncluyeIva: true,
      descripcion: 'Acuerdo con la marca',
    });
  });
});

describe('faltantes', () => {
  it('names what a campaign is missing before it is sent', () => {
    expect(faltantes(CAMPANA_VACIA)).toEqual(['nombre', 'fechas', 'monto por unidad', 'productos alcanzados']);
    expect(faltantes({ ...POR_UNIDAD, tipo: 'porcentaje' })).toEqual(['porcentaje']);
    expect(faltantes({ ...POR_UNIDAD, tcModo: 'fijo' })).toEqual(['tipo de cambio']);
    expect(faltantes({ ...POR_UNIDAD, topeUnidades: '1.5' })).toEqual(['tope de unidades entero']);
    expect(faltantes({ ...POR_UNIDAD, topeUnidades: '500' })).toEqual([]);
    expect(faltantes(POR_UNIDAD)).toEqual([]);
  });
});
