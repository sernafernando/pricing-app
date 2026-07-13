import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ExpandableRow from './ExpandableRow';

function renderRow(props = {}) {
  return render(
    <table>
      <tbody>
        <ExpandableRow
          isOpen={false}
          onToggle={() => {}}
          colSpan={5}
          header={<td>Header content</td>}
          {...props}
        >
          <div>Detail content</div>
        </ExpandableRow>
      </tbody>
    </table>,
  );
}

describe('ExpandableRow', () => {
  it('always renders the header row', () => {
    renderRow();
    expect(screen.getByText('Header content')).toBeInTheDocument();
  });

  it('does not render the detail row when closed', () => {
    renderRow({ isOpen: false });
    expect(screen.queryByText('Detail content')).not.toBeInTheDocument();
  });

  it('renders the detail row with colSpan when open', () => {
    renderRow({ isOpen: true, colSpan: 7 });
    const detail = screen.getByText('Detail content');
    expect(detail).toBeInTheDocument();
    const td = detail.closest('td');
    expect(td).toHaveAttribute('colSpan', '7');
  });

  it('toggle click calls onToggle and does not bubble to tbody', async () => {
    const onToggle = vi.fn();
    const onTbodyClick = vi.fn();
    render(
      <table>
        <tbody onClick={onTbodyClick}>
          <ExpandableRow
            isOpen={false}
            onToggle={onToggle}
            colSpan={5}
            header={<td>Header content</td>}
          >
            <div>Detail content</div>
          </ExpandableRow>
        </tbody>
      </table>,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir/i }));

    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onTbodyClick).not.toHaveBeenCalled();
  });
});
