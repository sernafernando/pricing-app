import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SwitchChip from './SwitchChip';

describe('SwitchChip', () => {
  it('is a switch named by its label that reports its state', () => {
    render(<SwitchChip label="Solo con ventas" checked onChange={() => {}} />);

    const toggle = screen.getByRole('switch', { name: 'Solo con ventas' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(toggle.querySelector('svg')).not.toBeNull();
  });

  it('off: unchecked, no check mark', () => {
    render(<SwitchChip label="Solo con ventas" checked={false} onChange={() => {}} />);

    const toggle = screen.getByRole('switch', { name: 'Solo con ventas' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(toggle.querySelector('svg')).toBeNull();
  });

  it('a click asks for the opposite state', async () => {
    const onChange = vi.fn();
    render(<SwitchChip label="Solo con ventas" checked onChange={onChange} title="ayuda" />);

    await userEvent.click(screen.getByRole('switch', { name: 'Solo con ventas' }));

    expect(onChange).toHaveBeenCalledWith(false);
    expect(screen.getByRole('switch')).toHaveAttribute('title', 'ayuda');
  });
});
