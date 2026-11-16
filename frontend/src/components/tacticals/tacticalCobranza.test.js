/**
 * Collection check of a tactical (handoffs/tactical-cobranza-tarea.md S3), owner 2026-11-10: "pida, fecha de cuando se
 * cobro, si es Nota de crédito (ahí número) o si es fondo en distribuidor (ahí un panel para aclarar el distri) u otro
 * y un panel para rellenar el otro. además un panel de observaciones libre, que obligatorio sea la fecha no más."
 */
import { describe, expect, it } from 'vitest';
import { cuerpoDeCobranza, estadoDeCobranza, problemaDeCobranza, valoresDeCobranza } from './tacticalCobranza';
import { COBRANZA_FONDO } from './tacticalsFixtures';

describe('valoresDeCobranza', () => {
  it('starts empty without a record and prefilled with one', () => {
    expect(valoresDeCobranza(null)).toEqual({
      fecha: '', medio: '', ncNumero: '', distribuidor: '', otroDetalle: '', observaciones: '', tipoCambio: '',
    });  // prettier-ignore
    expect(valoresDeCobranza(COBRANZA_FONDO)).toEqual({
      fecha: '2026-11-09',
      medio: 'fondo_distribuidor',
      ncNumero: '',
      distribuidor: 'Grupo Núcleo',
      otroDetalle: '',
      observaciones: 'Acreditado en la cuenta corriente de noviembre',
      tipoCambio: '',
    });
    expect(valoresDeCobranza({ ...COBRANZA_FONDO, tipo_cambio: '1350.500000' }).tipoCambio).toBe('1350,5');
  });
});

describe('problemaDeCobranza', () => {
  it('only the date is required', () => {
    expect(problemaDeCobranza(valoresDeCobranza(null))).toBe('La fecha de cobro es obligatoria.');
    expect(problemaDeCobranza({ ...valoresDeCobranza(null), fecha: '2026-11-09' })).toBeNull();
  });

  // Tactical sell in USD, owner: "Ponelo donde se carga el cobro": a USD al cobro sell in asks the rate it was paid at.
  it('asks for a valid collection rate only when the tactical takes one', () => {
    const fechada = { ...valoresDeCobranza(null), fecha: '2026-11-09' };
    const falta = 'Falta el tipo de cambio del cobro (pesos por dólar).';
    expect(problemaDeCobranza(fechada, true)).toBe(falta);
    expect(problemaDeCobranza({ ...fechada, tipoCambio: '1.350,5x' }, true)).toBe(falta);
    expect(problemaDeCobranza({ ...fechada, tipoCambio: '0' }, true)).toBe(falta);
    expect(problemaDeCobranza({ ...fechada, tipoCambio: '1.350,50' }, true)).toBeNull();
    expect(problemaDeCobranza(fechada, false)).toBeNull();
  });
});

describe('cuerpoDeCobranza', () => {
  const base = { fecha: '2026-11-09', medio: '', ncNumero: 'NC 1', distribuidor: 'Grupo Núcleo', otroDetalle: 'x', observaciones: '' };

  it('sends only the detail of the chosen medium, trimmed, and empty texts as null', () => {
    expect(cuerpoDeCobranza({ ...base, medio: 'nota_credito', ncNumero: ' 0003-00012345 ', observaciones: ' ok ' })).toEqual({
      fecha_cobro: '2026-11-09',
      medio: 'nota_credito',
      nc_numero: '0003-00012345',
      distribuidor: null,
      otro_detalle: null,
      observaciones: 'ok',
      tipo_cambio: null,
    });
    expect(cuerpoDeCobranza({ ...base, medio: 'fondo_distribuidor' })).toMatchObject({ distribuidor: 'Grupo Núcleo', nc_numero: null, otro_detalle: null });
    expect(cuerpoDeCobranza({ ...base, medio: 'otro' })).toMatchObject({ otro_detalle: 'x', nc_numero: null, distribuidor: null });
  });

  it('without a medium sends none of the details', () => {
    expect(cuerpoDeCobranza(base)).toEqual({
      fecha_cobro: '2026-11-09', medio: null, nc_numero: null, distribuidor: null, otro_detalle: null, observaciones: null,
      tipo_cambio: null,
    });  // prettier-ignore
  });

  it('sends the collection rate as a number only when the tactical takes one', () => {
    expect(cuerpoDeCobranza({ ...base, tipoCambio: '1.350,5' }, true).tipo_cambio).toBe(1350.5);
    expect(cuerpoDeCobranza({ ...base, tipoCambio: '1.350,5' }, false).tipo_cambio).toBeNull();
  });
});

describe('estadoDeCobranza', () => {
  it('reads Pendiente without a record and Cobrado with its date', () => {
    expect(estadoDeCobranza({ cobranza: null })).toEqual({ texto: 'Pendiente', tono: 'neutral' });
    expect(estadoDeCobranza({})).toEqual({ texto: 'Pendiente', tono: 'neutral' });
    expect(estadoDeCobranza({ cobranza: COBRANZA_FONDO })).toEqual({ texto: 'Cobrado 09/11/2026', tono: 'success' });
  });
});
