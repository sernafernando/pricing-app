/** A tactical row's actions menu moves with the arrow keys, as the WAI-ARIA menu pattern asks (tacticals F1). */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import TacticalAcciones from './TacticalAcciones';

const ACCIONES = [
  { label: 'Editar', onSelect: vi.fn() },
  { label: 'Renovar', onSelect: vi.fn() },
];

describe('TacticalAcciones', () => {
  it('moves through its items with the arrows, wrapping around, and Home / End', async () => {
    render(<TacticalAcciones nombre="Rebate" acciones={ACCIONES} />);
    await userEvent.click(screen.getByRole('button', { name: 'Acciones de Rebate' }));
    const [editar, renovar] = screen.getAllByRole('menuitem');

    expect(editar).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}');
    expect(renovar).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}');
    expect(editar).toHaveFocus();
    await userEvent.keyboard('{ArrowUp}');
    expect(renovar).toHaveFocus();
    await userEvent.keyboard('{Home}');
    expect(editar).toHaveFocus();
    await userEvent.keyboard('{End}');
    expect(renovar).toHaveFocus();
  });

  it('Tab closes the menu instead of leaving it open behind the focus', async () => {
    render(<TacticalAcciones nombre="Rebate" acciones={ACCIONES} />);
    await userEvent.click(screen.getByRole('button', { name: 'Acciones de Rebate' }));
    await userEvent.tab();

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
