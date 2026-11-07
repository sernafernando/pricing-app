import { describe, it, expect } from 'vitest';
import {
  contextosDeSeleccion,
  serializarContextos,
  paramDesdeSeleccion,
  seleccionDesdeParam,
} from './markupContextos';

const GRUPOS = [
  { value: '2645,471846', label: 'TP-Link', ids: ['2645', '471846'] },
  { value: '57997', label: 'Solo', ids: ['57997'] },
];

describe('contextosDeSeleccion', () => {
  it('Todas returns null (global)', () => {
    expect(contextosDeSeleccion(true, ['57997'], GRUPOS)).toBeNull();
  });

  it('expands clave groups and maps channels to resolver canales', () => {
    expect(contextosDeSeleccion(false, ['2645,471846', 'fuera', 'tienda_nube'], GRUPOS)).toEqual([
      ['ml', 2645],
      ['ml', 471846],
      ['fuera', null],
      ['tn', null],
    ]);
  });
});

describe('serializarContextos / paramDesdeSeleccion', () => {
  it('serializes for the listing query string', () => {
    expect(serializarContextos([['ml', 57997], ['fuera', null]])).toBe('ml:57997,fuera');
    expect(paramDesdeSeleccion(true, [], GRUPOS)).toBeNull();
    expect(paramDesdeSeleccion(false, ['57997', 'tienda_nube'], GRUPOS)).toBe('ml:57997,tn');
  });
});

describe('seleccionDesdeParam', () => {
  it('round-trips a group and a channel', () => {
    expect(seleccionDesdeParam('ml:2645,ml:471846,fuera', GRUPOS)).toEqual({
      todas: false,
      keys: ['fuera', '2645,471846'],
    });
  });
});
