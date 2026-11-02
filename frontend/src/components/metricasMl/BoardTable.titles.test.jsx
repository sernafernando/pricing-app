/**
 * "Filas finas" (vistas-tipo-publicacion S5) cuts the Producto cell's meta to one line: whatever it says must be
 * readable in a tooltip, for product, group and publication rows.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';

const base = {
  units: 1, units_24h: 0, units_3d: 0, units_7d: 0, units_15d: 0, units_30d: 1, gross: 200, total_gauss: 30,
  markup_pct: 30, series_units_90d: [], series_markup_90d: [], alerts: [],
};

function renderRows(groupBy, rows) {
  render(
    <BoardTable
      rows={rows}
      columns={buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy })}
      groupBy={groupBy}
      canSeeMargin
      expanded={new Set()}
      subRows={{}}
      onToggleExpand={() => {}}
      sort="gross"
      sortDesc
      onSort={() => {}}
      now={new Date('2026-09-30T18:00:00Z')}
      dense
    />,
  );
}

describe('BoardTable meta tooltips', () => {
  it('a group row says its counts in the tooltip', () => {
    renderRows('group', [
      { ...base, key: 'epson', title: 'Epson', level: 'marca', child_level: 'categoria', products_count: 12, publications_count: 31 },
    ]);
    expect(screen.getByText('12 productos · 31 publicaciones').closest('[title]')).toHaveAttribute('title', '12 productos · 31 publicaciones');
  });

  it('a publication row says its descriptor and title in the tooltip', () => {
    renderRows('publication', [
      { ...base, key: 'MLA1', mla: 'MLA1', title: 'Router AX55', listing_type: 'gold_special', is_full: true, status: 'active' },
    ]);
    const descriptor = screen.getByText(/Full · Activa/);
    expect(descriptor.closest('[title]').getAttribute('title')).toMatch(/Full · Activa · Router AX55$/);
  });
});
