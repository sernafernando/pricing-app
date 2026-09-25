import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import RecalculatingBadge from './RecalculatingBadge';

// ventas-ml-rediseno PR14.T9/T10 (SM R3/R9, FE side): a row whose
// `metrics_state === 'recalculating'` must never present a stale number as
// current. `failed` is explicitly NOT `recalculating` -- nothing retries a
// failed row, so a permanent "calculando..." would be a lie that never
// resolves. `pending` means no stored row exists yet (never seen a
// calculation), a third distinct state.
describe('RecalculatingBadge', () => {
  it('renders the recalculating state for metrics_state="recalculating"', () => {
    render(<RecalculatingBadge state="recalculating" />);
    expect(screen.getByText(/recalculando/i)).toBeInTheDocument();
  });

  it('renders a distinct failed state for metrics_state="failed" (never "recalculando")', () => {
    render(<RecalculatingBadge state="failed" />);
    expect(screen.queryByText(/recalculando/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no se pudo calcular/i)).toBeInTheDocument();
  });

  it('renders a distinct pending state for metrics_state="pending" (never "recalculando")', () => {
    render(<RecalculatingBadge state="pending" />);
    expect(screen.queryByText(/recalculando/i)).not.toBeInTheDocument();
    expect(screen.getByText(/sin calcular/i)).toBeInTheDocument();
  });

  it('renders nothing for metrics_state="ok" or an unknown state — the caller shows the real number instead', () => {
    const { container: okContainer } = render(<RecalculatingBadge state="ok" />);
    expect(okContainer).toBeEmptyDOMElement();
    const { container: unknownContainer } = render(<RecalculatingBadge state="something_new" />);
    expect(unknownContainer).toBeEmptyDOMElement();
  });
});
