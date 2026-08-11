/**
 * `src/test/setup.js` mockea `services/api` para toda la suite. Acá hace falta
 * el módulo REAL: lo que se está probando es la forma exacta del query string,
 * y un stub no probaría nada.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('./api', async (importOriginal) => await importOriginal());

const { serializeRepeatedParams } = await import('./api');

describe('serializeRepeatedParams', () => {
  it('emite un parámetro REPETIDO por cada elemento del array', () => {
    expect(serializeRepeatedParams({ empleado_ids: [1, 2] })).toBe('empleado_ids=1&empleado_ids=2');
  });

  it('no usa la notación con corchetes ni junta con comas', () => {
    const qs = serializeRepeatedParams({ empleado_ids: [1, 2, 3] });
    expect(qs).not.toContain('[]');
    expect(qs).not.toContain(',');
  });

  it('mezcla escalares y arrays conservando el orden de las claves', () => {
    expect(
      serializeRepeatedParams({
        fecha_desde: '2026-08-01',
        fecha_hasta: '2026-08-31',
        empleado_ids: [7, 9],
      })
    ).toBe('fecha_desde=2026-08-01&fecha_hasta=2026-08-31&empleado_ids=7&empleado_ids=9');
  });

  it('omite null y undefined en vez de mandarlos como texto', () => {
    expect(
      serializeRepeatedParams({ a: 1, b: null, c: undefined, d: [1, null, 2] })
    ).toBe('a=1&d=1&d=2');
  });

  it('un array vacío no aporta ningún parámetro', () => {
    expect(serializeRepeatedParams({ empleado_ids: [], f: '2026-01-01' })).toBe('f=2026-01-01');
  });

  it('tolera params vacío', () => {
    expect(serializeRepeatedParams()).toBe('');
    expect(serializeRepeatedParams({})).toBe('');
  });
});
