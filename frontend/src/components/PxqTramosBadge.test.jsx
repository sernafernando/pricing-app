import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PxqTramosBadge from './PxqTramosBadge';

describe('PxqTramosBadge — wholesale (PxQ) tiers quick view', () => {
  it('renders nothing when the product has no tiers', () => {
    const { container } = render(<PxqTramosBadge tramos={null} precioDesde={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when tramos is zero', () => {
    const { container } = render(<PxqTramosBadge tramos={0} precioDesde={100} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the tier count and the cheapest price', () => {
    render(<PxqTramosBadge tramos={3} precioDesde={37800} />);
    expect(screen.getByText(/3 tramos/)).toBeTruthy();
    expect(screen.getByText(/desde \$37\.800/)).toBeTruthy();
  });

  it('singularises a lone tier', () => {
    render(<PxqTramosBadge tramos={1} precioDesde={1000} />);
    expect(screen.getByText(/1 tramo(?!s)/)).toBeTruthy();
  });

  it('shows the count alone when the price could not be computed — never invents one', () => {
    render(<PxqTramosBadge tramos={2} precioDesde={null} />);
    expect(screen.getByText(/2 tramos/)).toBeTruthy();
    expect(screen.queryByText(/desde/)).toBeNull();
  });
});
