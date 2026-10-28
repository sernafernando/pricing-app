import { describe, expect, it } from 'vitest';
import {
  parseVista,
  VISTA_ADVISOR,
  VISTA_CRITERIOS,
  VISTA_PERIODICIDAD,
} from './paraGanarVistas';

describe('parseVista', () => {
  it('defaults to advisor', () => {
    expect(parseVista(null)).toBe(VISTA_ADVISOR);
    expect(parseVista(undefined)).toBe(VISTA_ADVISOR);
    expect(parseVista('')).toBe(VISTA_ADVISOR);
    expect(parseVista('nope')).toBe(VISTA_ADVISOR);
  });

  it('accepts criterios and periodicidad', () => {
    expect(parseVista(VISTA_CRITERIOS)).toBe(VISTA_CRITERIOS);
    expect(parseVista(VISTA_PERIODICIDAD)).toBe(VISTA_PERIODICIDAD);
  });
});
