/**
 * Tests for SalesToolbar (ventas-ml-rediseno PR14.T1/T3, SEARCH R25, R26,
 * R27).
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SalesToolbar from './SalesToolbar';

describe('SalesToolbar search input', () => {
  it('renders a searchbox with the current query as its value', () => {
    render(<SalesToolbar value="MLA123" onSearchChange={() => {}} />);
    expect(screen.getByRole('searchbox')).toHaveValue('MLA123');
  });

  it('debounces onSearchChange — does not fire on every keystroke', async () => {
    const user = userEvent.setup();
    const onSearchChange = vi.fn();
    render(<SalesToolbar value="" onSearchChange={onSearchChange} />);

    const input = screen.getByRole('searchbox');
    await user.type(input, 'juan');
    // Not yet — still inside the debounce window, even after every
    // keystroke dispatched synchronously.
    expect(onSearchChange).not.toHaveBeenCalled();

    await waitFor(() => expect(onSearchChange).toHaveBeenCalledWith('juan'), { timeout: 2000 });
    expect(onSearchChange).toHaveBeenCalledTimes(1);
  });

  it('calls onSearchChange with an empty string when cleared', async () => {
    const user = userEvent.setup();
    const onSearchChange = vi.fn();
    render(<SalesToolbar value="algo" onSearchChange={onSearchChange} />);

    await user.click(screen.getByRole('button', { name: /limpiar/i }));

    await waitFor(() => expect(onSearchChange).toHaveBeenCalledWith(''));
  });
});

describe('SalesToolbar empty-state (SEARCH R27)', () => {
  it('shows an explicit "sin resultados" message when noResults is true, not an error style', () => {
    render(<SalesToolbar value="algo-que-no-existe" onSearchChange={() => {}} noResults />);
    const message = screen.getByText(/sin resultados/i);
    expect(message).toBeInTheDocument();
    expect(message.className).not.toMatch(/error/i);
  });

  it('does not render the empty-state message when noResults is false', () => {
    render(<SalesToolbar value="algo" onSearchChange={() => {}} noResults={false} />);
    expect(screen.queryByText(/sin resultados/i)).not.toBeInTheDocument();
  });
});
