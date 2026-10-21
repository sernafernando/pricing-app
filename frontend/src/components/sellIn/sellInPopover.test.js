import { describe, it, expect } from 'vitest';
import { posicion } from './sellInPopover';

const rect = (left, top) => ({ left, top, bottom: top + 40, right: left + 300 });

describe('posicion of the products card', () => {
  it('goes to the left of the option when it fits', () => {
    expect(posicion(rect(900, 200), 1366, 768)).toEqual({ top: 200, left: 532 });
  });

  it('falls under the option when the left side is too narrow, kept inside the viewport', () => {
    expect(posicion(rect(100, 200), 1366, 768)).toEqual({ top: 244, left: 100 });
    expect(posicion(rect(100, 700), 400, 768)).toEqual({ top: 440, left: 32 });
  });

  it('sits at the corner when the option was not measured', () => {
    expect(posicion(undefined)).toEqual({ top: 8, left: 8 });
  });
});
