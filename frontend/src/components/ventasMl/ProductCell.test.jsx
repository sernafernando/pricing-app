import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProductCell from './ProductCell';

// ventas-ml-rediseno PR14.T5/T6 (LISTING R28, design D13): `items` is the
// FULL list of items backing this cell — never a flat title/SKU pair. An
// order (or a pack) can carry more than one item, and silently rendering
// only the first would be a lie the operator cannot detect from the row.
describe('ProductCell', () => {
  // LONE-SALE case: the majority of rows. Exactly one item, no "+N" badge.
  it('renders title, SKU, MLA and quantity for a single-item lone sale', () => {
    render(
      <ProductCell
        items={[
          { item_id: 'MLA2060835678', seller_sku: 'EPS-L3250', title: 'Impresora Epson EcoTank L3250', quantity: 1 },
        ]}
        category="IMPRESORAS"
      />
    );
    expect(screen.getByText('Impresora Epson EcoTank L3250')).toBeInTheDocument();
    expect(screen.getByText(/SKU EPS-L3250/)).toBeInTheDocument();
    expect(screen.getByText(/MLA2060835678/)).toBeInTheDocument();
    expect(screen.getByText(/x1/)).toBeInTheDocument();
    // discriminates from the multi-item case below: no "+N productos" badge
    expect(screen.queryByText(/\+\d+ producto/)).not.toBeInTheDocument();
  });

  // MULTI-ITEM case: a pack (or a multi-line order) must never silently
  // drop the rest of the items — this is the exact bug class the task
  // description calls out.
  it('renders the first item plus an explicit "+N productos" badge for a multi-item pack', () => {
    render(
      <ProductCell
        items={[
          { item_id: 'MLA1429582101', seller_sku: 'LEN-82YU000PAR', title: 'Lenovo V15 G4', quantity: 1 },
          { item_id: 'MLA1198421099', seller_sku: 'SAM-LS24C310', title: 'Monitor Samsung 24"', quantity: 1 },
          { item_id: 'MLA1384910283', seller_sku: 'SAM-UN50CU7000', title: 'Samsung Smart TV 50"', quantity: 1 },
        ]}
      />
    );
    expect(screen.getByText('Lenovo V15 G4')).toBeInTheDocument();
    expect(screen.getByText('+2 productos')).toBeInTheDocument();
    // the other two items' titles are NOT silently duplicated inline —
    // they are represented only by the count badge at this collapsed level
    expect(screen.queryByText('Monitor Samsung 24"')).not.toBeInTheDocument();
  });

  it('uses singular "producto" for exactly one extra item', () => {
    render(
      <ProductCell
        items={[
          { item_id: 'MLA1', seller_sku: 'A', title: 'Item uno', quantity: 1 },
          { item_id: 'MLA2', seller_sku: 'B', title: 'Item dos', quantity: 1 },
        ]}
      />
    );
    expect(screen.getByText('+1 producto')).toBeInTheDocument();
  });

  it('shows a placeholder instead of a blank title when title is missing', () => {
    render(<ProductCell items={[{ item_id: 'MLA9', seller_sku: 'X', title: null, quantity: 2 }]} />);
    expect(screen.getByText('(sin título)')).toBeInTheDocument();
  });

  it('omits the SKU segment (never "SKU undefined") when seller_sku is missing, keeping MLA and quantity', () => {
    render(<ProductCell items={[{ item_id: 'MLA7', seller_sku: null, title: 'Producto sin código propio', quantity: 3 }]} />);
    expect(screen.queryByText(/SKU/)).not.toBeInTheDocument();
    expect(screen.getByText(/MLA7/)).toBeInTheDocument();
    expect(screen.getByText(/x3/)).toBeInTheDocument();
  });

  it('renders a neutral empty state, not a crash, for an order with no items', () => {
    const { container } = render(<ProductCell items={[]} />);
    expect(screen.getByText('Sin datos de producto')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="product-cell-empty"]')).toBeInTheDocument();
  });

  it('carries the full title as a hoverable tooltip for truncation-proof access', () => {
    const longTitle = 'Impresora Multifunción Epson EcoTank L3250 con Sistema Continuo de Tinta Original';
    render(<ProductCell items={[{ item_id: 'MLA1', seller_sku: 'EPS', title: longTitle, quantity: 1 }]} />);
    expect(screen.getByTitle(longTitle)).toBeInTheDocument();
  });
  it('announces the category to assistive tech, and stays silent when there is none', () => {
    // Regression: the icon once carried `aria-hidden` AND `role="img"
    // aria-label` at the same time. `aria-hidden` removes the node from the
    // accessibility tree, so the label was never announced -- the separate
    // Categoria column it replaced HAD been accessible.
    const { rerender } = render(
      <ProductCell items={[{ item_id: 'MLA1', title: 'Impresora', quantity: 1 }]} category="IMPRESORAS" />,
    );
    expect(screen.getByRole('img', { name: 'IMPRESORAS' })).toBeInTheDocument();

    rerender(<ProductCell items={[{ item_id: 'MLA1', title: 'Impresora', quantity: 1 }]} />);
    expect(screen.queryByRole('img')).toBeNull();
  });
});
