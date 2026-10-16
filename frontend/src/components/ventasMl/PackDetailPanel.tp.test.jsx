/** The pack detail of a `tplink.solo` user: TP figures, no Gauss wording. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import PackDetailPanel from './PackDetailPanel';
import api from '../../services/api';

const PACK_TP = {
  pack_id: 777,
  monto_operacion: 1000,
  item_lines: [],
  item_lines_reconcilia: true,
  item_lines_razon: null,
  member_order_ids: [1, 2],
  costo_tp: 500,
  total_tp: 300,
  markup_tp: 60,
  tp_incompleto: false,
};

beforeEach(() => {
  api.get.mockReset();
});

function mockPack(pack) {
  api.get.mockImplementation(() => Promise.resolve({ data: pack }));
}

describe('PackDetailPanel, TP figures', () => {
  it('shows Total TP and Markup TP', async () => {
    mockPack(PACK_TP);
    render(<PackDetailPanel packId={777} onClose={vi.fn()} onSelectOrder={vi.fn()} />);
    const section = await screen.findByRole('region', { name: 'Total TP del pack' });
    expect(section).toHaveTextContent('300,00');
    expect(section).toHaveTextContent('Markup TP');
    expect(section).toHaveTextContent('60,00%');
    expect(document.body).not.toHaveTextContent(/gauss/i);
  });

  it('shows a dash and "incompleto" when a member TP is unknown', async () => {
    mockPack({ ...PACK_TP, costo_tp: null, total_tp: null, markup_tp: null, tp_incompleto: true });
    render(<PackDetailPanel packId={777} onClose={vi.fn()} onSelectOrder={vi.fn()} />);
    const section = await screen.findByRole('region', { name: 'Total TP del pack' });
    expect(section).toHaveTextContent('—');
    expect(section).toHaveTextContent('incompleto');
    expect(section).not.toHaveTextContent('0,00');
  });
});
