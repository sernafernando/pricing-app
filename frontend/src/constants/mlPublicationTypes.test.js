import { describe, it, expect } from 'vitest';
import {
  ML_PUBLICATION_TYPE_LABELS,
  getPublicationTypeLabel,
  publicationListLabel,
} from './mlPublicationTypes';

describe('mlPublicationTypes', () => {
  it('maps known pricelist_id values to their labels', () => {
    expect(ML_PUBLICATION_TYPE_LABELS[4]).toBe('Clásica');
    expect(ML_PUBLICATION_TYPE_LABELS[17]).toBe('3 Cuotas');
    expect(ML_PUBLICATION_TYPE_LABELS[14]).toBe('6 Cuotas');
    expect(ML_PUBLICATION_TYPE_LABELS[13]).toBe('9 Cuotas');
    expect(ML_PUBLICATION_TYPE_LABELS[23]).toBe('12 Cuotas');
    expect(ML_PUBLICATION_TYPE_LABELS[12]).toBe('PVP');
  });

  it('getPublicationTypeLabel returns the label for a known id', () => {
    expect(getPublicationTypeLabel(4)).toBe('Clásica');
  });

  it('getPublicationTypeLabel falls back gracefully for an unknown id', () => {
    expect(getPublicationTypeLabel(999)).toBe('Desconocido');
  });

  it('publicationListLabel prefers lista_nombre over the id map', () => {
    expect(publicationListLabel({ lista_nombre: 'Clásica ERP', pricelist_id: 4 })).toBe('Clásica ERP');
    expect(publicationListLabel({ lista_nombre: null, pricelist_id: 17 })).toBe('3 Cuotas');
    expect(publicationListLabel({ lista_nombre: '  ', pricelist_id: 12 })).toBe('PVP');
    expect(publicationListLabel(null)).toBeNull();
  });
});
