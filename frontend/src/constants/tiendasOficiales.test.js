import { describe, it, expect } from 'vitest';
import { STORE_NONE, buildStoreChips, groupStores, labelsForIds, groupValueForSelection } from './tiendasOficiales';

const T = (store_id, nombre, orden, activa = true, clave = null) => ({ store_id, nombre, orden, activa, clave });
const TIENDAS = [T(57997, 'Gauss', 0), T(2645, 'TP-Link viejo', 1, false, 'tplink'), T(471846, 'TP-Link', 2, true, 'tplink')];
const getLabel = (id) => TIENDAS.find((t) => String(t.store_id) === String(id))?.nombre ?? `Tienda ${id}`;

describe('groupStores', () => {
  it('collapses stores sharing a clave into ONE option with every id (inactive too)', () => {
    expect(groupStores(TIENDAS)).toEqual([
      { value: '57997', ids: ['57997'], label: 'Gauss' },
      { value: '2645,471846', ids: ['2645', '471846'], label: 'TP-Link' },
    ]);
  });

  it('labels the group with the first ACTIVE row by orden, falling back to any row', () => {
    const grupos = groupStores([T(1, 'B', 5, true, 'x'), T(2, 'A', 9, true, 'x'), T(3, 'Solo inactiva', 0, false, 'y')]);
    expect(grupos).toEqual([{ value: '1,2', ids: ['1', '2'], label: 'B' }]);
    // An all-inactive clave is not offered as an option.
    expect(groupStores([T(3, 'Solo inactiva', 0, false, 'y')])).toEqual([]);
  });

  it('keeps stores without clave one option per id, inactive ones out', () => {
    expect(groupStores([T(1, 'A', 0), T(2, 'B', 1, false)]).map((g) => g.value)).toEqual(['1']);
  });
});

describe('buildStoreChips', () => {
  it('lists the groups in order, then "Sin tienda"; a group count is the sum of its ids', () => {
    const { options, labels, counts } = buildStoreChips({
      tiendas: TIENDAS,
      getLabel,
      counts: { 57997: 3, 2645: 4, 471846: 6, sin_tienda: 2 },
    });
    expect(options).toEqual(['57997', '2645,471846', STORE_NONE]);
    expect(labels['2645,471846']).toBe('TP-Link');
    expect(counts['2645,471846']).toBe(10);
    expect(counts['57997']).toBe(3);
    expect(counts[STORE_NONE]).toBe(2);
  });

  it('adds a chip for any other store the facet reports, before "Sin tienda", ids ascending', () => {
    const { options, labels } = buildStoreChips({ tiendas: TIENDAS, getLabel, counts: { 900001: 1, 31: 2 } });
    expect(options).toEqual(['57997', '2645,471846', '31', '900001', STORE_NONE]);
    expect(labels['31']).toBe('Tienda 31');
  });

  it('keeps an unknown selected store as a chip even when the facet drops it', () => {
    const { options, activeValue } = buildStoreChips({ tiendas: TIENDAS, getLabel, selected: '424242' });
    expect(options).toContain('424242');
    expect(activeValue).toBe('424242');
  });

  it('a group chip is active when ALL its ids are selected (any order)', () => {
    expect(buildStoreChips({ tiendas: TIENDAS, getLabel, selected: '471846,2645' }).activeValue).toBe('2645,471846');
    expect(buildStoreChips({ tiendas: TIENDAS, getLabel, selected: '57997' }).activeValue).toBe('57997');
    // A broader selection (hand-edited) is not any one chip: it stays visible as its own.
    const broad = buildStoreChips({ tiendas: TIENDAS, getLabel, selected: '57997,2645,471846' });
    expect(broad.activeValue).toBe('57997,2645,471846');
    expect(broad.options).toContain('57997,2645,471846');
    expect(buildStoreChips({ tiendas: TIENDAS, getLabel, selected: '' }).activeValue).toBe('');
    expect(buildStoreChips({ tiendas: TIENDAS, getLabel, selected: STORE_NONE }).activeValue).toBe(STORE_NONE);
  });

  it('without facet counts (Métricas ML) offers only the groups', () => {
    expect(buildStoreChips({ tiendas: TIENDAS, getLabel }).options).toEqual(['57997', '2645,471846', STORE_NONE]);
  });
});

describe('labelsForIds', () => {
  it('returns one label per group/store, so a name with a comma stays one entry', () => {
    const tiendas = [T(1, 'Forza, Verbatim', 0, true, 'fv'), T(2, 'Forza, Verbatim', 1, true, 'fv'), T(3, 'Gauss', 2)];
    const label = (id) => tiendas.find((t) => String(t.store_id) === id)?.nombre ?? `Tienda ${id}`;
    expect(labelsForIds(tiendas, label, '1,2,3')).toEqual(['Forza, Verbatim', 'Gauss']);
    expect(labelsForIds(tiendas, label, '')).toEqual([]);
  });
});

describe('groupValueForSelection', () => {
  it('maps a non-empty subset of one clave group (legacy single-id URL) to the group option', () => {
    expect(groupValueForSelection(TIENDAS, '2645')).toBe('2645,471846');
    expect(groupValueForSelection(TIENDAS, '471846,2645')).toBe('2645,471846');
  });

  it('keeps an exact option, and leaves anything else untouched', () => {
    expect(groupValueForSelection(TIENDAS, '57997')).toBe('57997');
    expect(groupValueForSelection(TIENDAS, '2645,57997')).toBe('2645,57997');
    expect(groupValueForSelection(TIENDAS, '999')).toBe('999');
    expect(groupValueForSelection(TIENDAS, '')).toBe('');
  });
});
