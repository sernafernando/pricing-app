/**
 * The panel's tab registry (publicaciones-ml-vista P13b): which tabs exist for
 * which data and permission, in which order.
 */
import { describe, it, expect } from 'vitest';
import { PANEL_TABS, visibleTabs } from './panelTabs';
import { readDetail } from './detailModel';
import { DETAIL_RESPONSE, makeDetail } from '../../../test/visual/publicacionesMlFixtures';

const keysFor = (raw, context = {}) => visibleTabs(PANEL_TABS, { detail: readDetail(raw), canSeeMargin: false, canManage: false, ...context }).map((tab) => tab.key);

describe('the registry', () => {
  it('opens on Resumen and lists the history tabs after the data ones', () => {
    const raw = makeDetail({ row: { ...DETAIL_RESPONSE.row, variations_count: 3, is_full: true } });
    expect(keysFor(raw)).toEqual(['resumen', 'variaciones', 'full', 'eventos', 'historial', 'producto']);
  });

  it('keeps Eventos, Historial and Producto vinculado for every publication, with or without margin', () => {
    const raw = makeDetail({ row: { ...DETAIL_RESPONSE.row, variations_count: 0, is_full: false }, replenishment: null });
    expect(keysFor(raw)).toEqual(['resumen', 'eventos', 'historial', 'producto']);
    expect(keysFor(raw, { canSeeMargin: true })).toEqual(['resumen', 'eventos', 'historial', 'producto']);
  });

  it('labels them in Spanish', () => {
    const labels = Object.fromEntries(PANEL_TABS.map((tab) => [tab.key, tab.label]));
    expect(labels).toMatchObject({ eventos: 'Eventos', historial: 'Historial', producto: 'Producto' });
  });
});

describe('Promociones', () => {
  const raw = makeDetail({ row: { ...DETAIL_RESPONSE.row, variations_count: 0, is_full: false }, replenishment: null });

  it('exists only for who can read promotions, between Full and Eventos', () => {
    expect(keysFor(raw, { canViewPromos: false })).not.toContain('promociones');
    expect(keysFor(raw, { canViewPromos: true })).toEqual(['resumen', 'promociones', 'eventos', 'historial', 'producto']);
  });

  it('is labelled "Promos" so the strip keeps its slack', () => {
    expect(PANEL_TABS.find((tab) => tab.key === 'promociones').label).toBe('Promos');
  });
});
