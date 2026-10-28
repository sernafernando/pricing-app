import { describe, expect, it } from 'vitest';
import {
  DISPOSITION_ACTIVE,
  DISPOSITION_EXCLUDED,
  SELLER_DISPOSITIONS,
  dispositionLabel,
  normalizeDisposition,
} from './sellerDispositions';

describe('sellerDispositions', () => {
  it('only exposes Activo and Excluido', () => {
    expect(SELLER_DISPOSITIONS.map((d) => d.value)).toEqual([
      DISPOSITION_ACTIVE,
      DISPOSITION_EXCLUDED,
    ]);
  });

  it('normalizes legacy labels to excluded', () => {
    expect(normalizeDisposition('ignore_participant')).toBe(DISPOSITION_EXCLUDED);
    expect(normalizeDisposition('hide')).toBe(DISPOSITION_EXCLUDED);
    expect(normalizeDisposition('exclude_from_top')).toBe(DISPOSITION_EXCLUDED);
    expect(dispositionLabel('hide')).toBe('Excluido');
  });
});
