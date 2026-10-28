import { describe, expect, it } from 'vitest';
import {
  EMPTY_PERIODICIDAD_FORM,
  formToPeriodicidadPayload,
  scopeSummary,
  subscriptionToForm,
} from './periodicidadForm';

describe('formToPeriodicidadPayload', () => {
  it('builds all scope', () => {
    const result = formToPeriodicidadPayload({
      ...EMPTY_PERIODICIDAD_FORM,
      scope_mode: 'all',
      mlas: ['MLA1'],
    });
    expect(result.ok).toBe(true);
    expect(result.payload.mlas).toEqual([]);
  });

  it('requires mlas for mlas mode', () => {
    const result = formToPeriodicidadPayload({
      ...EMPTY_PERIODICIDAD_FORM,
      scope_mode: 'mlas',
      mlas: [],
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
    expect(form.mlas).toEqual(['MLA1', 'MLA2']);
    expect(scopeSummary({ scope_mode: 'all' })).toBe('Todo el EAN');
  });

  it('summarizes catalog rows without subscription scope', () => {
    expect(scopeSummary({ suscripto: false, mla_count: 3 })).toBe('3 MLAs');
    expect(scopeSummary({ suscripto: true, mla_count: 1 })).toBe('1 MLA');
  });
});
