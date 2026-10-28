/** SinMlaCard: Productos' "Sin MLA" card of the Producto view, a switch that shows how many products have no MLA. */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SinMlaCard from './SinMlaCard';

describe('SinMlaCard', () => {
  it('shows the count, and a dash while it is unknown (a publication filter is on)', () => {
    const { rerender } = render(<SinMlaCard count={1234} active={false} onChange={() => {}} />);
    expect(screen.getByRole('button', { name: /Sin MLA/ })).toHaveTextContent('1.234');
    rerender(<SinMlaCard count={null} active={false} onChange={() => {}} />);
    expect(screen.getByRole('button', { name: /Sin MLA/ })).toHaveTextContent('Sin MLA–');
  });

  it('asks for the opposite of its state on click', async () => {
    const onChange = vi.fn();
    render(<SinMlaCard count={3} active onChange={onChange} />);
    const card = screen.getByRole('button', { name: /Sin MLA/ });
    expect(card).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(card);
    expect(onChange).toHaveBeenCalledWith(false);
  });
});
