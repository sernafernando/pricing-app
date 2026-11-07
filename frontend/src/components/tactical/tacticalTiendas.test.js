import { describe, expect, it } from 'vitest';
import { previewTope, seleccionDesdeDetalle, tiendasDelContrato } from './tacticalTiendas';

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
      { label: 'TP-Link', valor: '100' },
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
});
