import { describe, it, expect } from 'vitest';
import { buildBoardColumns } from './metricasMlColumns';

const ids = (options) =>
  buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', dimension: 'marca', ...options }).map(
    (column) => column.id,
  );

describe('buildBoardColumns: ads column', () => {
  it('has no ads column with the toggle off', () => {
    expect(ids({ adsOn: false })).not.toContain('ads_cost');
    expect(ids({})).not.toContain('ads_cost');
  });

  it('adds the ads cost column, in its own group after the financial result, once ads are subtracted', () => {
    const columns = buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', adsOn: true });
    const column = columns.find((col) => col.id === 'ads_cost');
    expect(column).toMatchObject({ group: 'publicidad', header: 'Publicidad (inversión)' });
    expect(columns.findIndex((col) => col.id === 'ads_cost')).toBeGreaterThan(columns.findIndex((col) => col.id === 'total_gauss'));
  });

  it('never shows it without the margin permission', () => {
    expect(ids({ canSeeMargin: false, adsOn: true })).not.toContain('ads_cost');
  });
});

describe('buildBoardColumns: Costos TP', () => {
  it('has no Total TP column with the toggle off', () => {
    expect(ids({})).not.toContain('total_tp');
  });

  it('puts Total TP right after Total Gauss, in the financial result, ahead of the ads column', () => {
    const order = ids({ tpOn: true, adsOn: true });
    expect(order.indexOf('total_tp')).toBe(order.indexOf('total_gauss') + 1);
    const columns = buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', tpOn: true });
    expect(columns.find((col) => col.id === 'total_tp')).toMatchObject({ group: 'resultado', header: 'Total TP' });
  });

  it('says the markup uses the TP cost while the toggle is on', () => {
    const markup = (tpOn) =>
      buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', tpOn }).find((col) => col.id === 'markup');
    expect(markup(true).title).toBe('Usa el costo TP en las operaciones de la tienda TP-Link');
    expect(markup(false).title).toBeUndefined();
  });

  it('never shows it without the margin permission', () => {
    expect(ids({ canSeeMargin: false, tpOn: true })).not.toContain('total_tp');
  });
});

describe('buildBoardColumns for a tplink.solo user', () => {
  const tpSolo = (options) =>
    buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', tpOn: true, tpSolo: true, ...options });

  it('has Total TP and no Total Gauss column at all', () => {
    const order = tpSolo().map((col) => col.id);
    expect(order).not.toContain('total_gauss');
    expect(order.indexOf('total_tp')).toBe(order.indexOf('gross') + 1);
  });

  it('shows Total TP even before the first answer says TP is on', () => {
    expect(tpSolo({ tpOn: false }).map((col) => col.id)).toContain('total_tp');
  });

  it('labels the markup as Markup TP', () => {
    expect(tpSolo().find((col) => col.id === 'markup')).toMatchObject({
      header: 'Markup TP',
      title: 'Usa el costo TP en las operaciones de la tienda TP-Link',
    });
  });
});
