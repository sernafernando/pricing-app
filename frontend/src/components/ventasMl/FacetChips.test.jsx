import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FacetChips from './FacetChips';

// ventas-ml-rediseno PR14.T7/T8 (LISTING R30): live counts that stay
// consistent with the active filter set. The counts come straight from the
// `facets` the backend already returns for THIS axis under the OTHER
// axis's active filter -- this component never recounts client-side. That
// consistency bug was already found and fixed server-side once; the
// contract here is that this component is a pure renderer of whatever
// counts it receives, so it cannot reintroduce a client-side recount.
describe('FacetChips', () => {
  const OPTIONS = ['paid', 'cancelled'];
  const LABELS = { paid: 'Pagada', cancelled: 'Cancelada' };
  const counts = { paid: 3, cancelled: 1 };

  it('renders an "all" chip with the total plus one chip per option with its live count', () => {
    render(
      <FacetChips
        label="Operación"
        options={OPTIONS}
        labels={LABELS}
        counts={counts}
        total={4}
        activeValue=""
        onChange={() => {}}
      />
    );
    expect(screen.getByRole('button', { name: /Todas · 4/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Pagada · 3/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancelada · 1/ })).toBeInTheDocument();
  });

  it('renders a count of 0 verbatim instead of hiding the chip or omitting the number', () => {
    render(
      <FacetChips
        label="Operación"
        options={OPTIONS}
        labels={LABELS}
        counts={{ paid: 0, cancelled: 1 }}
        total={1}
        activeValue=""
        onChange={() => {}}
      />
    );
    expect(screen.getByRole('button', { name: /Pagada · 0/ })).toBeInTheDocument();
  });

  it('marks the active chip pressed and calls onChange with the toggled value on click', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <FacetChips
        label="Operación"
        options={OPTIONS}
        labels={LABELS}
        counts={counts}
        total={4}
        activeValue="paid"
        onChange={onChange}
      />
    );
    const activeChip = screen.getByRole('button', { name: /Pagada · 3/ });
    expect(activeChip).toHaveAttribute('aria-pressed', 'true');

    await user.click(activeChip);
    // clicking the already-active chip clears the filter (toggle behavior)
    expect(onChange).toHaveBeenCalledWith('');

    await user.click(screen.getByRole('button', { name: /Cancelada · 1/ }));
    expect(onChange).toHaveBeenCalledWith('cancelled');
  });

  it('never derives its counts from `options.length` or any client-side sum of `counts`', () => {
    // A facet whose backend count disagrees with counting the option list
    // itself is the exact bug this component must not reintroduce.
    render(
      <FacetChips
        label="Operación"
        options={OPTIONS}
        labels={LABELS}
        counts={{ paid: 7, cancelled: 2 }}
        total={999}
        activeValue=""
        onChange={() => {}}
      />
    );
    // total is whatever the backend sent, not sum(counts) (=9)
    expect(screen.getByRole('button', { name: /Todas · 999/ })).toBeInTheDocument();
  });
});
