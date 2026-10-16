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
