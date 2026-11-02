/**
 * "Filas finas" (vistas-tipo-publicacion S5) cuts the Producto cell's meta to one line: whatever it says must be
 * readable in a tooltip, for product, group and publication rows.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';
import { nodeId } from '../../utils/metricasMlLevels';

const base = {
  units: 1, units_24h: 0, units_3d: 0, units_7d: 0, units_15d: 0, units_30d: 1, gross: 200, total_gauss: 30,
  markup_pct: 30, series_units_90d: [], series_markup_90d: [], alerts: [],
};

function renderRows(groupBy, rows, { expanded = new Set(), subRows = {} } = {}) {
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

  it('a publication row without a title says only its descriptor', () => {
    renderRows('publication', [
      { ...base, key: 'MLA2', mla: 'MLA2', title: null, listing_type: 'gold_special', is_full: true, status: 'active' },
    ]);
    const descriptor = screen.getByText(/Full · Activa/);
    expect(descriptor.closest('[title]').getAttribute('title')).toMatch(/Full · Activa$/);
  });

  it('a product row says its SKU, brand and publication count in the tooltip', () => {
    renderRows('product', [{ ...base, key: '11', product_item_id: 11, title: 'Router AX55', sku: 'SKU-11', marca: 'TP-Link', publications_count: 3 }]);
    expect(screen.getByText('SKU-11').closest('[title]')).toHaveAttribute('title', 'SKU-11 · TP-Link · 3 publicaciones');
  });

  it("an expanded product's publication says its MLA, type, best mark and descriptor in the tooltip", () => {
    const product = { ...base, key: '11', product_item_id: 11, title: 'Router AX55', sku: 'SKU-11', publications_count: 1 };
    const pub = { ...base, key: 'MLA1', mla: 'MLA1', product_item_id: 11, title: 'Router AX55 Full', listing_type: 'gold_pro', listing_kind: 'cuotas_12', is_best: true, is_full: true, status: 'active' };
    renderRows('product', [product], {
      expanded: new Set([nodeId(['11'])]),
      subRows: { [nodeId(['11'])]: { loading: false, rows: [pub] } },
    });
    expect(screen.getByText('MLA1').closest('[title]')).toHaveAttribute('title', 'MLA1 · 12 cuotas · Mejor · Full · Activa');
  });

  it("an Agrupado product's SKU line says its SKU and brand in the tooltip", () => {
    renderRows('group', [{ ...base, key: 'p1', product_item_id: 11, title: 'Router AX55', sku: 'SKU-11', marca: 'TP-Link' }]);
    expect(screen.getByText('SKU-11').closest('[title]')).toHaveAttribute('title', 'SKU-11 · TP-Link');
  });
});
