import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SellInOutMarkupExtra from './SellInOutMarkupExtra';

describe('SellInOutMarkupExtra', () => {
  it('labels the promo markup "c/ SO" and names only the sell out in its tooltip (D1: no markup with sell in)', () => {
    render(<SellInOutMarkupExtra value={24.1} />);
    const extra = screen.getByText('c/ SO').parentElement;
    expect(extra).toHaveTextContent('c/ SO 24.1%');
    expect(extra).toHaveAttribute('title', 'Markup con el sell out de hoy del producto');
  });

  it('renders nothing without a value', () => {
    const { container } = render(<SellInOutMarkupExtra value={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
