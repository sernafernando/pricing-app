import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ErpStockCell from './ErpStockCell';
import { TotalStockCell } from './MetricsCells';

describe('ErpStockCell', () => {
  it('groups thousands like the Full and total stock beside it', () => {
    render(
      <>
        <ErpStockCell erpStock={{ quantity: 12500 }} />
        <TotalStockCell total={12520} />
      </>,
    );
    expect(screen.getByText('12.500')).toBeInTheDocument();
    expect(screen.getByText('12.520')).toBeInTheDocument();
  });

  it('shows an unknown ERP stock as "—" and a zero as "Sin stock ERP"', () => {
    const { container } = render(<ErpStockCell erpStock={{ quantity: null }} />);
    expect(container).toHaveTextContent('—');
    render(<ErpStockCell erpStock={{ quantity: 0 }} />);
    expect(screen.getByTitle('Sin stock ERP')).toHaveTextContent('0');
  });
});
