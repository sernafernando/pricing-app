import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Pagination from './Pagination';

function setup(props = {}) {
  const onOffsetChange = vi.fn();
  const onPageSizeChange = vi.fn();
  render(
    <Pagination
      total={1000}
      offset={0}
      pageSize={50}
      onOffsetChange={onOffsetChange}
      onPageSizeChange={onPageSizeChange}
      {...props}
    />,
  );
  return { onOffsetChange, onPageSizeChange };
}

describe('Pagination', () => {
  it('shows the range and total', () => {
    setup({ offset: 50 });
    expect(screen.getByText('mostrando 51-100 de 1000 ventas')).toBeInTheDocument();
  });

  it('marks the current page and jumps to a numbered page', async () => {
    const { onOffsetChange } = setup({ offset: 0 });
    expect(screen.getByRole('button', { name: 'Página 1' })).toHaveAttribute('aria-current', 'page');
    await userEvent.click(screen.getByRole('button', { name: 'Página 2' }));
    expect(onOffsetChange).toHaveBeenCalledWith(50);
  });

  it('jumps to the last page', async () => {
    const { onOffsetChange } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Página 20' }));
    expect(onOffsetChange).toHaveBeenCalledWith(950);
  });

  it('Anterior and Siguiente step one page and disable at the edges', async () => {
    const { onOffsetChange } = setup({ offset: 0 });
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
    expect(onOffsetChange).toHaveBeenCalledWith(50);
  });

  it('disables Siguiente on the last page', () => {
    setup({ offset: 950 });
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
  });

  it('changing rows per page reports the new size', async () => {
    const { onPageSizeChange } = setup();
    await userEvent.selectOptions(screen.getByLabelText('Filas por página'), '100');
    expect(onPageSizeChange).toHaveBeenCalledWith(100);
  });

  it('renders no numbered pages for an empty set', () => {
    setup({ total: 0 });
    expect(screen.getByText('mostrando 0-0 de 0 ventas')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
  });

  it('a caller can replace the range line with its own summary', () => {
    render(
      <Pagination
        total={471}
        offset={0}
        pageSize={50}
        onOffsetChange={() => {}}
        onPageSizeChange={() => {}}
        summary={<span>Mostrando 1–50 de 471 productos</span>}
      />,
    );
    expect(screen.getByText('Mostrando 1–50 de 471 productos')).toBeInTheDocument();
    expect(screen.queryByText(/ventas/)).not.toBeInTheDocument();
  });
});
