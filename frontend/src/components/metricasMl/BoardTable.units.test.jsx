import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';

const row = {
  key: '11',
  product_item_id: 11,
  title: 'Router AX55',
  sku: 'SKU-11',
  marca: 'TP-Link',
  publications_count: 1,
  units: 1234,
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
};

function renderTable(onSort = () => {}) {
  render(
    <BoardTable
      rows={[row]}
      columns={buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product' })}
      groupBy="product"
      canSeeMargin
      expanded={new Set()}
      subRows={{}}
      onToggleExpand={() => {}}
      sort="gross"
      sortDesc
      onSort={onSort}
      now={new Date('2026-09-30T18:00:00Z')}
    />,
  );
}

describe('BoardTable: units of the period', () => {
  it('shows the units sold in the chosen period', () => {
    renderTable();

    expect(document.querySelector('td[data-col-id="units"]')).toHaveTextContent('1.234');
  });

  it('sorts by them', async () => {
    const onSort = vi.fn();
    renderTable(onSort);

    await userEvent.click(screen.getByRole('columnheader', { name: /Unidades mes/ }).querySelector('button') ?? screen.getByText('Unidades mes'));

    expect(onSort).toHaveBeenCalledWith('units');
  });
});
