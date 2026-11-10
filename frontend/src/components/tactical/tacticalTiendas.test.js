import { describe, expect, it } from 'vitest';
import { contadoresDelTope, previewTope, seleccionDesdeDetalle, tiendasDelContrato } from './tacticalTiendas';

const GRUPOS = [
  { value: '57997', ids: ['57997'], label: 'GaussOnline' },
  { value: '2645,471846', ids: ['2645', '471846'], label: 'TP-Link' },
];

describe('tiendasDelContrato', () => {
  it('expands a clave group and keeps channels when not todas', () => {
    expect(tiendasDelContrato(false, ['2645,471846', 'fuera'], GRUPOS)).toEqual([
      { tipo: 'oficial', store_id: 2645 },
      { tipo: 'oficial', store_id: 471846 },
      { tipo: 'fuera', store_id: null },
    ]);
  });

  it('with todas only keeps synthetic channels', () => {
    expect(tiendasDelContrato(true, ['57997', 'tienda_nube'], GRUPOS)).toEqual([
      { tipo: 'tienda_nube', store_id: null },
    ]);
  });
});

describe('previewTope', () => {
  it('shows one row per target when caps are per store', () => {
    const preview = previewTope({
      todasTiendas: false,
      seleccionKeys: ['57997', '2645,471846'],
      grupos: GRUPOS,
      topeCompartido: false,
      ejemploTope: 100,
    });
    expect(preview.filas).toEqual([
      { label: 'GaussOnline', valor: '100' },
      { label: 'TP-Link (2 tiendas)', valor: '100 cada una' },
    ]);
  });

  it('with every store and per-store caps, says each store and the no-store sales get their own cap', () => {
    const preview = previewTope({
      todasTiendas: true,
      seleccionKeys: ['tienda_nube'],
      grupos: GRUPOS,
      topeCompartido: false,
      ejemploTope: 100,
    });
    expect(preview.filas).toEqual([
      { label: 'Cada tienda oficial (3)', valor: '100 cada una' },
      { label: 'Ventas sin tienda oficial', valor: '100' },
      { label: 'Tienda Nube', valor: '100' },
    ]);
  });

  it('shows a shared pool when the toggle is on', () => {
    const preview = previewTope({
      todasTiendas: false,
      seleccionKeys: ['57997', 'fuera'],
      grupos: GRUPOS,
      topeCompartido: true,
      ejemploTope: 100,
    });
    expect(preview.filas).toEqual([{ label: 'GaussOnline + Por fuera', valor: '100 compartidos' }]);
  });
});

describe('contadoresDelTope', () => {
  const base = { grupos: GRUPOS, alcancePorTienda: true };

  it('counts one cap per official store and channel, as the engines split it', () => {
    expect(contadoresDelTope({ ...base, todasTiendas: false, seleccionKeys: ['2645,471846', 'fuera'], topeCompartido: false })).toBe(3);
    expect(contadoresDelTope({ ...base, todasTiendas: true, seleccionKeys: ['fuera'], topeCompartido: false })).toBe(5);
  });

  it('with every store counts only the active ones, as the engines do', () => {
    expect(contadoresDelTope({ ...base, tiendasActivas: 2, todasTiendas: true, seleccionKeys: ['fuera'], topeCompartido: false })).toBe(4);
    const preview = previewTope({ grupos: GRUPOS, tiendasActivas: 2, todasTiendas: true, seleccionKeys: [], topeCompartido: false, ejemploTope: 10 });
    expect(preview.filas[0]).toEqual({ label: 'Cada tienda oficial (2)', valor: '10 cada una' });
  });

  it('is one with a shared cap, or while the store scope is off', () => {
    expect(contadoresDelTope({ ...base, todasTiendas: true, seleccionKeys: [], topeCompartido: true })).toBe(1);
    expect(contadoresDelTope({ ...base, alcancePorTienda: false, todasTiendas: true, seleccionKeys: [], topeCompartido: false })).toBe(1);
  });
});

describe('seleccionDesdeDetalle', () => {
  it('maps official store ids back to clave groups and channels', () => {
    expect(
      seleccionDesdeDetalle(
        {
          tiendas: [
            { tipo: 'oficial', store_id: 2645 },
            { tipo: 'oficial', store_id: 471846 },
            { tipo: 'fuera', store_id: null },
          ],
        },
        GRUPOS,
      ),
    ).toEqual(['2645,471846', 'fuera']);
  });

  it('keeps a saved store its group no longer covers, on its own, instead of dropping it', () => {
    const tactical = { tiendas: [{ tipo: 'oficial', store_id: 2645 }, { tipo: 'oficial', store_id: 999 }] };

    expect(seleccionDesdeDetalle(tactical, GRUPOS)).toEqual(['2645', '999']);
    expect(tiendasDelContrato(false, seleccionDesdeDetalle(tactical, GRUPOS), GRUPOS)).toEqual([
      { tipo: 'oficial', store_id: 2645 },
      { tipo: 'oficial', store_id: 999 },
    ]);
  });

  it('keeps every saved store when the store list failed to load', () => {
    const tactical = { tiendas: [{ tipo: 'oficial', store_id: 57997 }, { tipo: 'tienda_nube', store_id: null }] };

    expect(seleccionDesdeDetalle(tactical, [])).toEqual(['57997', 'tienda_nube']);
  });

  it('does not pick a group with no stores', () => {
    const tactical = { tiendas: [{ tipo: 'oficial', store_id: 57997 }] };

    expect(seleccionDesdeDetalle(tactical, [{ value: 'vacio', ids: [], label: 'Vacío' }, ...GRUPOS])).toEqual(['57997']);
  });
});
