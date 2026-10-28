import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProductSection } from './SaleContextSections';

describe('ProductSection SKU', () => {
  it('keeps the current SKU as the main value and adds the old one as "ex" when it changed', () => {
    render(<ProductSection items={[{ item_id: 'MLA1', seller_sku: '1215', seller_sku_anterior: '1214' }]} />);
    expect(screen.getByText('1215')).toBeInTheDocument();
    expect(screen.getByText('ex 1214')).toBeInTheDocument();
  });

  it('shows no "ex" when the SKU did not change', () => {
    render(<ProductSection items={[{ item_id: 'MLA1', seller_sku: '1215', seller_sku_anterior: null }]} />);
    expect(screen.getByText('1215')).toBeInTheDocument();
    expect(screen.queryByText(/^ex /)).not.toBeInTheDocument();
  });
});

describe('ProductSection photo', () => {
  it("shows the MLA's stored photo, and the placeholder for an item without one", () => {
    const { container } = render(
      <ProductSection
        items={[
          { item_id: 'MLA1', title: 'Con foto', thumbnail_url: 'https://http2.mlstatic.com/1.jpg' },
          { item_id: 'MLA2', title: 'Sin foto', thumbnail_url: null },
        ]}
      />,
    );
    const imgs = container.querySelectorAll('img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0]).toHaveAttribute('src', 'https://http2.mlstatic.com/1.jpg');
    expect(container.querySelectorAll('[data-sale-item-placeholder]')).toHaveLength(1);
  });
});
