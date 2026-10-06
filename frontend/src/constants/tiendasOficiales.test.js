import { describe, it, expect } from 'vitest';
import { STORE_NONE, buildStoreChips } from './tiendasOficiales';

const ACTIVAS = [
  { store_id: 57997, nombre: 'Gauss' },
  { store_id: 2645, nombre: 'TP-Link' },
];
const getLabel = (id) => ({ 57997: 'Gauss', 2645: 'TP-Link', 777: 'Inactiva' })[id] ?? `Tienda ${id}`;

describe('buildStoreChips', () => {
  it('lists the active stores in the given order, even at zero, then "Sin tienda"', () => {
    const { options, labels } = buildStoreChips({ activas: ACTIVAS, getLabel, counts: { 57997: 3 } });
    expect(options).toEqual(['57997', '2645', STORE_NONE]);
    expect(labels).toMatchObject({ 57997: 'Gauss', 2645: 'TP-Link', [STORE_NONE]: 'Sin tienda' });
  });

  it('adds a chip for any other store the facet reports, before "Sin tienda", ids ascending', () => {
    const { options, labels } = buildStoreChips({
      activas: ACTIVAS,
      getLabel,
      counts: { 57997: 3, 900001: 1, 31: 2, 777: 1, sin_tienda: 1 },
    });
    expect(options).toEqual(['57997', '2645', '31', '777', '900001', STORE_NONE]);
    expect(labels['900001']).toBe('Tienda 900001');
    expect(labels['31']).toBe('Tienda 31');
    // An inactive store with sales keeps its admin-defined name.
    expect(labels['777']).toBe('Inactiva');
  });

  it('keeps the selected store as a chip even when the facet no longer reports it', () => {
    const { options, labels } = buildStoreChips({ activas: ACTIVAS, getLabel, counts: {}, selected: '424242' });
    expect(options).toContain('424242');
    expect(labels['424242']).toBe('Tienda 424242');
  });

  it('without facet counts (Métricas ML) offers only the active stores', () => {
    const { options } = buildStoreChips({ activas: ACTIVAS, getLabel });
    expect(options).toEqual(['57997', '2645', STORE_NONE]);
  });
});
