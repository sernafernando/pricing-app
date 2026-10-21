import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SellInNuevoPanel from './SellInNuevoPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { operaciones: vi.fn().mockResolvedValue({ data: { items: [] } }) },
  sellInBonosAPI: { crear: vi.fn() },
}));

beforeEach(() => vi.clearAllMocks());

const renderPanel = () =>
  render(<SellInNuevoPanel marcas={['TP-LINK']} onCreated={vi.fn()} onBonoCreado={vi.fn()} onClose={vi.fn()} />);

describe('SellInNuevoPanel', () => {
  it('opens on "Por compra" with the "Por compra | Bono de marca" switch', () => {
    renderPanel();
    const modo = screen.getByRole('group', { name: 'Tipo de sell in' });
    expect(within(modo).getByRole('button', { name: 'Por compra' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { name: 'Nuevo sell in · Por compra' })).toBeInTheDocument();
  });

  it('"Bono de marca" swaps the form in the same panel', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Bono de marca' }));
    expect(screen.getByRole('heading', { name: 'Nuevo sell in · Bono de marca' })).toBeInTheDocument();
    expect(screen.getByLabelText('Monto por unidad')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Tipo de sell in' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Por compra' }));
    expect(screen.getByRole('heading', { name: 'Nuevo sell in · Por compra' })).toBeInTheDocument();
  });
});
