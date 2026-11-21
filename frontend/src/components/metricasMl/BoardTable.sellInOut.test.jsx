import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';
import { formatSignedMoney } from '../../utils/ventasMlTone';

// Costo SI T3 D1: the payload `sell_in_out` keeps its key; it carries the sell out added to the profit ("c/ SO") over
// the frozen cost (costo SI), no sell in.
const SELL = {
  sell_out: 5,
  sell_out_pendientes: 0,
  sell_out_estimados: 0,
  costo: 100,
  total_gauss: 35,
  markup_pct: 35,
};

const row = (sellInOut) => ({
  key: '11',
  product_item_id: 11,
  title: 'Router AX55',
  sku: 'SKU-11',
  marca: 'TP-Link',
  publications_count: 1,
  units: 1,
  units_24h: 0,
  units_3d: 0,
  units_7d: 0,
  units_15d: 0,
  units_30d: 1,
  gross: 200,
  total_gauss: 30,
  markup_pct: 30,
  series_units_90d: [],
  series_markup_90d: [],
  alerts: [],
  sell_in_out: sellInOut,
});

function renderRow(sellInOut) {
  const columns = buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product' });
  render(
    <BoardTable
      rows={[row(sellInOut)]}
      columns={columns}
      groupBy="product"
      canSeeMargin
      expanded={new Set()}
      subRows={{}}
      onToggleExpand={() => {}}
      sort="gross"
      sortDesc
      onSort={() => {}}
      now={new Date('2026-09-30T18:00:00Z')}
    />,
  );
}

const cell = (id) => document.querySelector(`td[data-col-id="${id}"]`);

const headers = () => [...document.querySelectorAll('th')].map((th) => th.textContent);

describe('BoardTable: sell out c/ SO', () => {
  it('shows the cost, the sell out, and Total and markup c/ SO', () => {
    renderRow(SELL);

    expect(cell('costo')).toHaveTextContent(formatSignedMoney(100));
    expect(cell('sell_out')).toHaveTextContent(formatSignedMoney(5));
    expect(cell('total_gauss_sell')).toHaveTextContent(formatSignedMoney(35));
    expect(cell('markup_sell')).toHaveTextContent('35,0%');
    expect(screen.queryByText('Próximamente')).not.toBeInTheDocument();
  });

  it('has no sell in column nor cost with sell in, and labels the figures c/ SO', () => {
    renderRow(SELL);

    expect(cell('sell_in')).toBeNull();
    expect(cell('costo_sell_in')).toBeNull();
    const all = headers();
    expect(all).toEqual(expect.arrayContaining(['Costo', 'Sell out', 'Total c/ SO', 'Markup c/ SO']));
    expect(all.some((h) => /sell in/i.test(h))).toBe(false);
  });

  it('flags the sell out lines still without their rate, and the estimated ones', () => {
    renderRow({ ...SELL, sell_out_pendientes: 2, sell_out_estimados: 1 });
    const sellOut = cell('sell_out');

    expect(within(sellOut).getByTitle(/2 ventas con sell out en dólares sin tipo de cambio/)).toBeInTheDocument();
    expect(within(sellOut).getByTitle(/1 venta con tipo de cambio estimado/)).toBeInTheDocument();
  });

  // Owner: "en las filas que no aplica estaría bueno que directamente esté vacío así no hace ruido".
  it('a row where no sell out applies leaves those cells empty and keeps its cost', () => {
    renderRow({ ...SELL, sell_out: null, total_gauss: null, markup_pct: null });

    expect(cell('costo')).toHaveTextContent(formatSignedMoney(100));
    for (const id of ['sell_out', 'total_gauss_sell', 'markup_sell']) {
      expect(cell(id)).toHaveTextContent(/^$/);
    }
  });

  it('a row without the figures shows dashes, never a made-up zero', () => {
    renderRow(null);

    for (const id of ['costo', 'sell_out', 'total_gauss_sell', 'markup_sell']) {
      expect(cell(id)).toHaveTextContent(/^—$/);
    }
  });

  it('with "Costos TP" shows a dash for the cost and the markup c/ SO', () => {
    // What the board sends with "Costos TP" on: no Gauss cost basis, so no cost nor markup c/ SO.
    renderRow({ ...SELL, costo: null, markup_pct: null });

    expect(cell('costo')).toHaveTextContent(/^—$/);
    expect(cell('markup_sell')).toHaveTextContent(/^—$/);
    expect(cell('sell_out')).toHaveTextContent(formatSignedMoney(5));
    expect(cell('total_gauss_sell')).toHaveTextContent(formatSignedMoney(35));
  });
});
