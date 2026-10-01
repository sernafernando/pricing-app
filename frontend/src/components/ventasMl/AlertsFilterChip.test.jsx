import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AlertsFilterChip from './AlertsFilterChip';

describe('AlertsFilterChip', () => {
  it('shows the backend count and reflects the pressed state', () => {
    const { rerender } = render(<AlertsFilterChip active={false} count={12} onChange={vi.fn()} />);
    const chip = screen.getByRole('button', { name: /solo con alertas/i });
    expect(chip).toHaveTextContent('Solo con alertas · 12');
    expect(chip).toHaveAttribute('aria-pressed', 'false');
    rerender(<AlertsFilterChip active count={12} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /solo con alertas/i })).toHaveAttribute('aria-pressed', 'true');
  });

  it('toggles through onChange', async () => {
    const onChange = vi.fn();
    render(<AlertsFilterChip active={false} count={3} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /solo con alertas/i }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('counts zero when the backend has not answered yet', () => {
    render(<AlertsFilterChip active={false} count={undefined} onChange={vi.fn()} />);
    expect(screen.getByRole('button')).toHaveTextContent('· 0');
  });
});
