/**
 * A publication's checkbox checks that publication (seleccion-por-publicacion S1); a product row's checkbox checks
 * the product. A product row with no product cannot be checked and says why.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RowCheckbox } from './ProductCheckbox';
import { withProductSelection } from './productSelection';
import { buildColumns } from './columns';

describe('RowCheckbox', () => {
  it('toggles the row it names; with Shift it asks for a range (S12d)', async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    render(<RowCheckbox rowKey="i:MLA1" checked={false} onToggle={onToggle} label="MLA1" />);
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la publicación MLA1' }));
    expect(onToggle).toHaveBeenLastCalledWith('i:MLA1', false);
    await user.keyboard('{Shift>}');
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la publicación MLA1' }));
    await user.keyboard('{/Shift}');
    expect(onToggle).toHaveBeenLastCalledWith('i:MLA1', true);
  });

  it('a product row names the product', () => {
    render(<RowCheckbox rowKey="p:4101" product checked={false} onToggle={() => {}} label="Router" />);
    expect(screen.getByRole('checkbox', { name: 'Seleccionar el producto Router' })).toBeEnabled();
  });

  it('is disabled, with the reason, when the row has no key (a product row with no product)', () => {
    render(<RowCheckbox rowKey={null} product checked={false} onToggle={() => {}} label="Sin producto" />);
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

  it("puts the publication's own checkbox in the title cell and leaves the other columns alone", async () => {
    const onToggle = vi.fn();
    const wrapped = withProductSelection(columns, { checked: new Map([['i:MLA2', {}]]), onToggle });
    expect(wrapped[1]).toBe(columns[1]);
    const { rerender } = render(wrapped[0].render({ item_id: 'MLA1', title: 'Router', link: { producto_item_id: 4101 } }));
    expect(screen.getByText('Router')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('checkbox'));
    expect(onToggle).toHaveBeenCalledWith('i:MLA1', false);
    rerender(wrapped[0].render({ item_id: 'MLA2', title: 'Tinta', link: { producto_item_id: 4102 } }));
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  // The variation toggle leads the pinned cell at the row's depth; the checkbox follows it, so the variations'
  // state row (indented one level past the depth) lines up under the toggle.
  it('puts the checkbox after the variations toggle of a publication with variations', () => {
    const [titulo] = buildColumns({ expandedIds: new Set(), onToggleVariations: () => {} });
    const [wrapped] = withProductSelection([titulo], { checked: new Map(), onToggle: () => {} });
    render(wrapped.render({ item_id: 'MLA5', title: 'Router', variations_count: 2, link: { producto_item_id: 4101 } }));
    const toggle = screen.getByRole('button', { name: /variaciones de MLA5/ });
    const box = screen.getByRole('checkbox');
    expect(toggle.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
