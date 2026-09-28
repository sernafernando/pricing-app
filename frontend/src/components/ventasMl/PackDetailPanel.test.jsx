/**
 * Tests for PackDetailPanel.jsx (ventas-ml-rediseno PR19, PANEL R23,
 * scenarios 5/9/10).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PackDetailPanel from './PackDetailPanel';
import api from '../../services/api';

function mockPack(packId, pack) {
  api.get.mockImplementation((url) => {
    if (url === `/ml-ventas-ops/packs/${packId}`) {
      return Promise.resolve({ data: pack });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.get.mockReset();
});

describe('Fetch and render on mount', () => {
  it('fetches GET /ml-ventas-ops/packs/{pack_id} and renders pack-scoped figures (PANEL R23 scenario 9)', async () => {
    mockPack(555, {
      pack_id: 555,
      monto_operacion: 1000,
      item_lines: [
        { item_id: 'MLA1', variation_id: null, title: 'Producto A', quantity: 1, monto: 600 },
        { item_id: 'MLA2', variation_id: null, title: 'Producto B', quantity: 1, monto: 400 },
      ],
      item_lines_reconcilia: true,
      item_lines_razon: null,
      total_gauss: 300,
      costo_mercaderia: 150,
      markup: 100,
      member_order_ids: [111, 222],
    });

    render(<PackDetailPanel packId={555} onClose={vi.fn()} onSelectOrder={vi.fn()} />);

    expect(await screen.findByText('Desglose del pack 555')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/packs/555');

    expect(screen.getByText('1.000,00')).toBeInTheDocument();
    expect(screen.getByText('Producto A')).toBeInTheDocument();
    expect(screen.getByText('Producto B')).toBeInTheDocument();
    expect(screen.getByText('300,00')).toBeInTheDocument();
    expect(screen.getByText('100,00%')).toBeInTheDocument();
    expect(screen.getByText('111')).toBeInTheDocument();
    expect(screen.getByText('222')).toBeInTheDocument();
  });

  it('renders markup as "—" (never 0 or fabricated) when the backend sent null (R37)', async () => {
    mockPack(556, {
      pack_id: 556,
      monto_operacion: 1000,
      item_lines: [],
      item_lines_reconcilia: true,
      item_lines_razon: null,
      total_gauss: null,
      costo_mercaderia: null,
      markup: null,
      member_order_ids: [333],
    });

    render(<PackDetailPanel packId={556} onClose={vi.fn()} onSelectOrder={vi.fn()} />);

    await screen.findByText('Desglose del pack 556');
    const totalGaussDashes = screen.getAllByText('—');
    expect(totalGaussDashes.length).toBeGreaterThanOrEqual(2); // Total Gauss + Markup
  });
});

describe('Member order navigation (PANEL R23 scenario 10)', () => {
  it('calls onSelectOrder with the clicked member order id', async () => {
    mockPack(555, {
      pack_id: 555,
      monto_operacion: 1000,
      item_lines: [],
      item_lines_reconcilia: true,
      item_lines_razon: null,
      total_gauss: 300,
      costo_mercaderia: 150,
      markup: 100,
      member_order_ids: [111, 222],
    });
    const onSelectOrder = vi.fn();
    const user = userEvent.setup();

    render(<PackDetailPanel packId={555} onClose={vi.fn()} onSelectOrder={onSelectOrder} />);
    await screen.findByText('Desglose del pack 555');

    const memberButton = screen.getByRole('button', { name: '111' });
    await user.click(memberButton);

    expect(onSelectOrder).toHaveBeenCalledWith(111);
  });
});

describe('Not-found pack (BREAKDOWN R39)', () => {
  it('shows a not-found message instead of an empty pack response', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/packs/999') {
        const error = new Error('Not Found');
        error.response = { status: 404 };
        return Promise.reject(error);
      }
      return Promise.resolve({ data: {} });
    });

    render(<PackDetailPanel packId={999} onClose={vi.fn()} onSelectOrder={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Pack no encontrado.')).toBeInTheDocument());
  });
});
