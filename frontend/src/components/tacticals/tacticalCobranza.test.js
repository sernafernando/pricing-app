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
      fecha: '', medio: '', ncNumero: '', distribuidor: '', otroDetalle: '', observaciones: '',
    });  // prettier-ignore
    expect(valoresDeCobranza(COBRANZA_FONDO)).toEqual({
      fecha: '2026-11-09',
      medio: 'fondo_distribuidor',
      ncNumero: '',
      distribuidor: 'Grupo Núcleo',
      otroDetalle: '',
      observaciones: 'Acreditado en la cuenta corriente de noviembre',
    });
  });
});

describe('problemaDeCobranza', () => {
  it('only the date is required', () => {
    expect(problemaDeCobranza(valoresDeCobranza(null))).toBe('La fecha de cobro es obligatoria.');
    expect(problemaDeCobranza({ ...valoresDeCobranza(null), fecha: '2026-11-09' })).toBeNull();
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
    });
    expect(cuerpoDeCobranza({ ...base, medio: 'fondo_distribuidor' })).toMatchObject({ distribuidor: 'Grupo Núcleo', nc_numero: null, otro_detalle: null });
    expect(cuerpoDeCobranza({ ...base, medio: 'otro' })).toMatchObject({ otro_detalle: 'x', nc_numero: null, distribuidor: null });
  });

  it('without a medium sends none of the details', () => {
    expect(cuerpoDeCobranza(base)).toEqual({
      fecha_cobro: '2026-11-09', medio: null, nc_numero: null, distribuidor: null, otro_detalle: null, observaciones: null,
    });  // prettier-ignore
  });
});

describe('estadoDeCobranza', () => {
  it('reads Pendiente without a record and Cobrado with its date', () => {
    expect(estadoDeCobranza({ cobranza: null })).toEqual({ texto: 'Pendiente', tono: 'neutral' });
    expect(estadoDeCobranza({})).toEqual({ texto: 'Pendiente', tono: 'neutral' });
    expect(estadoDeCobranza({ cobranza: COBRANZA_FONDO })).toEqual({ texto: 'Cobrado 09/11/2026', tono: 'success' });
  });
});
