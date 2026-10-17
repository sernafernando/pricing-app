/**
 * Checking a publication checks its linked PRODUCT (pricing is per product); a publication with no product cannot
 * be checked for a pricing action and says why.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProductCheckbox } from './ProductCheckbox';
import { withProductSelection } from './productSelection';
import { buildColumns } from './columns';

describe('ProductCheckbox', () => {
  it('toggles the product it names', async () => {
    const onToggle = vi.fn();
    render(<ProductCheckbox productId={4101} checked={false} onToggle={onToggle} label="MLA1" />);
    await userEvent.setup().click(screen.getByRole('checkbox', { name: /seleccionar el producto de MLA1/i }));
    expect(onToggle).toHaveBeenCalledWith(4101);
  });

  it('is disabled, with the reason, when there is no product', () => {
    render(<ProductCheckbox productId={null} checked={false} onToggle={() => {}} label="MLA4" />);
    const box = screen.getByRole('checkbox');
    expect(box).toBeDisabled();
    expect(box).toHaveAttribute('title', expect.stringMatching(/sin producto/i));
  });
});

describe('withProductSelection', () => {
  const columns = [
    // The title render places `after` (the checkbox) after its own leading controls.
    { key: 'titulo', header: 'Publicación', render: (item, after) => <span>{after}{item.title}</span> },
    { key: 'precio', header: 'Precio', render: () => '$1' },
  ];

  it("puts the publication's product checkbox in the title cell and leaves the other columns alone", async () => {
    const onToggle = vi.fn();
    const wrapped = withProductSelection(columns, { checked: new Set([4102]), onToggle });
    expect(wrapped[1]).toBe(columns[1]);
    const { rerender } = render(wrapped[0].render({ item_id: 'MLA1', title: 'Router', link: { producto_item_id: 4101 } }));
    expect(screen.getByText('Router')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('checkbox'));
    expect(onToggle).toHaveBeenCalledWith(4101);
    rerender(wrapped[0].render({ item_id: 'MLA2', title: 'Tinta', link: { producto_item_id: 4102 } }));
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  // The variation toggle leads the pinned cell at the row's depth; the checkbox follows it, so the variations'
  // state row (indented one level past the depth) lines up under the toggle.
  it('puts the checkbox after the variations toggle of a publication with variations', () => {
    const [titulo] = buildColumns({ expandedIds: new Set(), onToggleVariations: () => {} });
    const [wrapped] = withProductSelection([titulo], { checked: new Set(), onToggle: () => {} });
    render(wrapped.render({ item_id: 'MLA5', title: 'Router', variations_count: 2, link: { producto_item_id: 4101 } }));
    const toggle = screen.getByRole('button', { name: /variaciones de MLA5/ });
    const box = screen.getByRole('checkbox');
    expect(toggle.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
