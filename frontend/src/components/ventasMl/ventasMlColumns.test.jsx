import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { COLUMNS } from './ventasMlColumns';
import { COLUMN_VISIBILITY_STORAGE_KEY, loadColumnVisibility } from '../../pages/ventasMlTableHelpers';

const importe = COLUMNS.find((c) => c.id === 'importe');

function renderCell(ctx) {
  const view = render(<div data-testid="cell">{importe.cell(ctx)}</div>);
  const cell = screen.getByTestId('cell');
  return Object.assign(cell, { unmount: view.unmount });
}

const order = (over = {}) => ({ order_id: 1, total_amount: 1000, currency_id: 'ARS', ...over });

describe('Importe cell: ML coupon sub-line', () => {
  it('shows "cupón ML $X" under the amount when the order carries a coupon', () => {
    const o = order({ coupon_amount: 150 });
    const cell = renderCell({ kind: 'group', group: { total_amount: 1000, currency_id: 'ARS' }, orders: [o] });
    expect(cell).toHaveTextContent('1.000,00');
    expect(cell).toHaveTextContent('cupón ML $ 150,00');
  });

  it('sums the coupons of every order in a pack', () => {
    const orders = [order({ order_id: 1, coupon_amount: 100 }), order({ order_id: 2, coupon_amount: 50.5 })];
    const cell = renderCell({ kind: 'group', group: { total_amount: 2000, currency_id: 'ARS' }, orders });
    expect(cell).toHaveTextContent('cupón ML $ 150,50');
  });

  it('shows no sub-line when the coupon is zero, null or absent', () => {
    for (const coupon_amount of [0, null, undefined]) {
      const cell = renderCell({
        kind: 'group',
        group: { total_amount: 1000, currency_id: 'ARS' },
        orders: [order({ coupon_amount })],
      });
      expect(cell).not.toHaveTextContent('cupón');
      cell.unmount();
    }
  });

  it('a pack-member row shows its own coupon', () => {
    const cell = renderCell({ kind: 'member', order: order({ coupon_amount: 75 }) });
    expect(cell).toHaveTextContent('cupón ML $ 75,00');
  });
});

describe('Sell in / out cell (Métricas audit A7)', () => {
  const sell = COLUMNS.find((c) => c.id === 'sell_in_out');
  const renderSell = (ctx) => {
    const view = render(<div data-testid="sell">{sell.cell(ctx)}</div>);
    return Object.assign(screen.getByTestId('sell'), { unmount: view.unmount, tooltip: sell.cellProps(ctx).title });
  };

  it('shows the sell in with the sell out on the sub-line, and names both in the tooltip', () => {
    const cell = renderSell({ kind: 'member', order: order({ sell_in_ars: 1200.5, sell_out_ars: 300, sell_out_estimado: false }) });
    expect(cell).toHaveTextContent('1.200,50');
    expect(cell).toHaveTextContent('out $ 300,00');
    expect(cell.tooltip).toBe('Sell in: $ 1.200,50 · Sell out: $ 300,00');
  });

  it('a pack row reads the pack sums', () => {
    const cell = renderSell({ kind: 'group', group: { sell_in_ars: 10, sell_out_ars: null, sell_out_estimado: null }, orders: [] });
    expect(cell).toHaveTextContent('10,00');
    expect(cell).not.toHaveTextContent('out');
    expect(cell.tooltip).toBe('Sell in: $ 10,00');
  });

  it('an estimated sell out is marked, an unknown one says it is not defined yet', () => {
    let cell = renderSell({ kind: 'member', order: order({ sell_out_ars: 50, sell_out_estimado: true }) });
    expect(cell).toHaveTextContent('out ≈ $ 50,00');
    expect(cell.tooltip).toBe('Sell out: $ 50,00 (estimado: tipo de cambio a definir)');
    cell.unmount();
    cell = renderSell({ kind: 'member', order: order({ sell_out_ars: null, sell_out_estimado: true }) });
    expect(cell).toHaveTextContent('out a definir');
    expect(cell.tooltip).toBe('Sell out en USD sin tipo de cambio');
  });

  it('a sale with nothing applied shows a dash and no tooltip', () => {
    const cell = renderSell({ kind: 'member', order: order() });
    expect(cell).toHaveTextContent('—');
    expect(cell).not.toHaveTextContent('out');
    expect(cell.tooltip).toBeUndefined();
  });

  it('can be hidden from Columnas, and a stored choice to hide it is kept', () => {
    localStorage.setItem(COLUMN_VISIBILITY_STORAGE_KEY, JSON.stringify({ sell_in_out: false, total_gauss: false }));
    try {
      expect(loadColumnVisibility(COLUMNS)).toEqual({ sell_in_out: false });
    } finally {
      localStorage.removeItem(COLUMN_VISIBILITY_STORAGE_KEY);
    }
  });
});

describe('Total Gauss cell: cost sub-line (Métricas audit B9)', () => {
  const totalGauss = COLUMNS.find((c) => c.id === 'total_gauss');
  const renderTg = (ctx) => {
    const view = render(<div data-testid="tg">{totalGauss.cell(ctx)}</div>);
    return Object.assign(screen.getByTestId('tg'), { unmount: view.unmount });
  };

  it('shows the stored merchandise cost of a sale and of a pack under Total Gauss', () => {
    let cell = renderTg({ kind: 'member', order: order({ total_gauss: 100, costo_mercaderia: 2012.5, metrics_state: 'ok' }) });
    expect(cell).toHaveTextContent('costo $ 2.012,50');
    cell.unmount();
    cell = renderTg({ kind: 'group', group: { total_gauss: 50, costo_mercaderia: 150.5 }, metricsState: 'ok', orders: [] });
    expect(cell).toHaveTextContent('costo $ 150,50');
  });

  it('an unknown cost shows no sub-line, never a zero', () => {
    const cell = renderTg({ kind: 'member', order: order({ total_gauss: null, costo_mercaderia: null, metrics_state: 'ok' }) });
    expect(cell).not.toHaveTextContent('costo');
  });

  it('while the metrics recompute it shows no stale cost', () => {
    const cell = renderTg({ kind: 'member', order: order({ total_gauss: 1, costo_mercaderia: 10, metrics_state: 'pending' }) });
    expect(cell).not.toHaveTextContent('costo');
  });
});
