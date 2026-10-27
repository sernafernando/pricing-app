import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';
import { formatSignedMoney } from '../../utils/ventasMlTone';

const SELL = {
  sell_in: 10,
  sell_out: 5,
  sell_out_pendientes: 0,
  sell_out_estimados: 0,
  costo: 100,
  costo_sell_in: 90,
  total_gauss: 45,
  markup_pct: 50,
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

describe('BoardTable: sell in / sell out', () => {
  it('shows cost, cost with sell in, both amounts, and Total Gauss and markup with them', () => {
    renderRow(SELL);

    expect(cell('costo')).toHaveTextContent(formatSignedMoney(100));
    expect(cell('costo_sell_in')).toHaveTextContent(formatSignedMoney(90));
    expect(cell('sell_in')).toHaveTextContent(formatSignedMoney(10));
    expect(cell('sell_out')).toHaveTextContent(formatSignedMoney(5));
    expect(cell('total_gauss_sell')).toHaveTextContent(formatSignedMoney(45));
    expect(cell('markup_sell')).toHaveTextContent('50,0%');
    expect(screen.queryByText('Próximamente')).not.toBeInTheDocument();
  });

  it('flags the sell out lines still without their rate, and the estimated ones', () => {
    renderRow({ ...SELL, sell_out_pendientes: 2, sell_out_estimados: 1 });
    const sellOut = cell('sell_out');

    expect(within(sellOut).getByTitle(/2 ventas con sell out en dólares sin tipo de cambio/)).toBeInTheDocument();
    expect(within(sellOut).getByTitle(/1 venta con tipo de cambio estimado/)).toBeInTheDocument();
  });

  // Owner: "en las filas que no aplica estaría bueno que directamente esté vacío así no hace ruido".
  it('a row where sell in / sell out does not apply leaves those cells empty and keeps its cost', () => {
    renderRow({
      ...SELL,
      sell_in: null,
      sell_out: null,
      costo_sell_in: null,
      total_gauss: null,
      markup_pct: null,
    });

    expect(cell('costo')).toHaveTextContent(formatSignedMoney(100));
    for (const id of ['costo_sell_in', 'sell_in', 'sell_out', 'total_gauss_sell', 'markup_sell']) {
      expect(cell(id)).toHaveTextContent(/^$/);
    }
  });

  it('a row with sell out only leaves its sell in empty', () => {
    renderRow({ ...SELL, sell_in: null, costo_sell_in: null });

    expect(cell('sell_in')).toHaveTextContent(/^$/);
    expect(cell('costo_sell_in')).toHaveTextContent(/^$/);
    expect(cell('sell_out')).toHaveTextContent(formatSignedMoney(5));
  });

  it('a row without the figures shows dashes, never a made-up zero', () => {
    renderRow(null);

    for (const id of ['costo', 'costo_sell_in', 'sell_in', 'sell_out', 'total_gauss_sell', 'markup_sell']) {
      expect(cell(id)).toHaveTextContent(/^—$/);
    }
  });
});
