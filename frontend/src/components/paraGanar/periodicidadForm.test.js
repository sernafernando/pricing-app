import { describe, expect, it } from 'vitest';
import {
  EMPTY_PERIODICIDAD_FORM,
  formToPeriodicidadPayload,
  parseMlasText,
  scopeSummary,
  subscriptionToForm,
} from './periodicidadForm';

describe('parseMlasText', () => {
  it('splits and uppercases unique MLAs', () => {
    expect(parseMlasText('mla1, MLA2; mla1')).toEqual(['MLA1', 'MLA2']);
  });
});

describe('formToPeriodicidadPayload', () => {
  it('builds all scope', () => {
    const result = formToPeriodicidadPayload({
      ...EMPTY_PERIODICIDAD_FORM,
      scope_mode: 'all',
      mlasText: 'MLA1',
    });
    expect(result.ok).toBe(true);
    expect(result.payload.mlas).toEqual([]);
  });

  it('requires mlas for mlas mode', () => {
    const result = formToPeriodicidadPayload({
      ...EMPTY_PERIODICIDAD_FORM,
      scope_mode: 'mlas',
      mlasText: '  ',
    });
    expect(result.ok).toBe(false);
  });

  it('builds rules payload', () => {
    const result = formToPeriodicidadPayload({
      ...EMPTY_PERIODICIDAD_FORM,
      scope_mode: 'rules',
      tipos_publicacion: ['6'],
      pricelist_ids: [14],
      tienda_oficial_ids: [1],
    });
    expect(result.ok).toBe(true);
    expect(result.payload.tipos_publicacion).toEqual(['6']);
  });
});

describe('subscriptionToForm / scopeSummary', () => {
  it('round-trips list fields', () => {
    const form = subscriptionToForm({
      enabled: true,
      scope_mode: 'mlas',
      mlas: ['MLA1', 'MLA2'],
      tipos_publicacion: [],
      pricelist_ids: [],
      tienda_oficial_ids: [],
    });
    expect(form.mlasText).toBe('MLA1, MLA2');
    expect(scopeSummary({ scope_mode: 'all' })).toBe('Todo el EAN');
  });
});
