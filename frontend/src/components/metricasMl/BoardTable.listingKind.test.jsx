/**
 * The listing type badge on Métricas ML (owner, 2026-11-02): "abrilo en productos, pero las publis adentro del
 * producto también tienen que estar ordenadas y tener el badge". A publication row and every publication of an
 * expanded product show their type; the sub-rows keep the board's order (Clásica, then 3, 6, 9, 12 cuotas).
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';
import { nodeId } from '../../utils/metricasMlLevels';

const base = {
  units: 1,
  units_24h: 0,
  units_3d: 0,
  units_7d: 0,
  units_15d: 0,
  units_30d: 1,
  gross: 100,
  total_gauss: 10,
  markup_pct: 10,
  series_units_90d: [],
  series_markup_90d: [],
  alerts: [],
};
const pub = (mla, listing_kind) => ({
  ...base,
  key: mla,
  mla,
  product_item_id: 11,
  title: `Publicación ${mla}`,
  status: 'active',
  listing_type: 'premium',
  listing_kind,
});
const product = { ...base, key: '11', product_item_id: 11, title: 'Router AX55', sku: 'SKU-11', publications_count: 3 };

function renderBoard({ rows, groupBy, expanded = new Set(), subRows = {} }) {
  render(
    <BoardTable
      rows={rows}
      columns={buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy })}
      groupBy={groupBy}
      canSeeMargin
      expanded={expanded}
      subRows={subRows}
      onToggleExpand={() => {}}
      sort="gross"
      sortDesc
      onSort={() => {}}
      now={new Date('2026-09-30T18:00:00Z')}
    />,
  );
}

describe('BoardTable: listing type badge', () => {
  it('shows the type of a publication row', () => {
    renderBoard({ rows: [pub('MLA1', 'cuotas_6')], groupBy: 'publication' });
    expect(screen.getByText('6 cuotas')).toBeInTheDocument();
  });

  it("shows the type of every publication of an expanded product, in the board's order", () => {
    const sub = [pub('MLA2', 'clasica'), pub('MLA3', 'cuotas_3'), pub('MLA1', 'cuotas_12')];
    renderBoard({
      rows: [product],
      groupBy: 'product',
      expanded: new Set([nodeId(['11'])]),
      subRows: { [nodeId(['11'])]: { loading: false, rows: sub } },
    });
    const mlas = screen.getAllByText(/^MLA\d$/).map((node) => node.textContent);
    expect(mlas).toEqual(['MLA2', 'MLA3', 'MLA1']);
    for (const [mla, label] of [
      ['MLA2', 'Clásica'],
      ['MLA3', '3 cuotas'],
      ['MLA1', '12 cuotas'],
    ]) {
      expect(within(screen.getByText(mla).closest('tr')).getByText(label)).toBeInTheDocument();
    }
  });

  it('a row without the field (an older backend) shows no badge and keeps its type in the descriptor', () => {
    renderBoard({ rows: [pub('MLA1', undefined)], groupBy: 'publication' });
    expect(screen.getByText(/Premium · Activa/)).toBeInTheDocument();
  });
});
