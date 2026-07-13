import { describe, it, expect } from 'vitest';
import { ML_PUBLICATION_TYPE_LABELS, getPublicationTypeLabel } from './mlPublicationTypes';

describe('mlPublicationTypes', () => {
  it('maps known pricelist_id values to their labels', () => {
    expect(ML_PUBLICATION_TYPE_LABELS[4]).toBe('Clásica');
    expect(ML_PUBLICATION_TYPE_LABELS[17]).toBe('3 Cuotas');
    expect(ML_PUBLICATION_TYPE_LABELS[14]).toBe('6 Cuotas');
    expect(ML_PUBLICATION_TYPE_LABELS[13]).toBe('9 Cuotas');
    expect(ML_PUBLICATION_TYPE_LABELS[23]).toBe('12 Cuotas');
  });

  it('getPublicationTypeLabel returns the label for a known id', () => {
    expect(getPublicationTypeLabel(4)).toBe('Clásica');
  });

  it('getPublicationTypeLabel falls back gracefully for an unknown id', () => {
    expect(getPublicationTypeLabel(999)).toBe('Desconocido');
  });
});
