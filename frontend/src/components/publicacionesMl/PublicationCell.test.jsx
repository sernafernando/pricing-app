/**
 * The Publicación cell links each publication to the Mercado Libre seller
 * panel: two icon links, plus Alt/Shift+click shortcuts on the MLA.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import PublicationCell from './PublicationCell';
import { makeItem } from '../../test/visual/publicacionesMlFixtures';

const LISTING = 'https://vendedores.mercadolibre.com.ar/publicaciones?page=1&sort=DEFAULT&search=1173065146';
const PROMOS = 'https://vendedores.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=1173065146';

const renderCell = (onRowClick = vi.fn()) => {
  render(
    <div onClick={onRowClick}>
      <PublicationCell item={makeItem({ item_id: 'MLA1173065146', title: 'Router' })} />
    </div>,
  );
  return onRowClick;
};

afterEach(() => vi.restoreAllMocks());

describe('PublicationCell seller panel links', () => {
  it.each([
    ['Ver en el panel de ML', LISTING],
    ['Ver promociones en ML', PROMOS],
  ])('"%s" opens %s in a new tab', (name, href) => {
    renderCell();
    const link = screen.getByRole('link', { name });
    expect(link).toHaveAttribute('href', href);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('title', name);
  });

  it('clicking a link does not also select the row', () => {
    const onRowClick = renderCell();
    fireEvent.click(screen.getByRole('link', { name: 'Ver en el panel de ML' }));
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it('renders no links when the publication has no usable id', () => {
    render(<PublicationCell item={makeItem({ item_id: '' })} />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});

describe('PublicationCell MLA modifier shortcuts', () => {
  it.each([
    ['Alt', { altKey: true }, LISTING],
    ['Shift', { shiftKey: true }, PROMOS],
  ])('%s+click on the MLA opens the seller panel URL and stops there', (_label, modifiers, url) => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const onRowClick = renderCell();
    const mla = screen.getByText('MLA1173065146');
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, ...modifiers });
    mla.dispatchEvent(event);
    expect(open).toHaveBeenCalledWith(url, '_blank', 'noopener,noreferrer');
    expect(event.defaultPrevented).toBe(true);
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it.each([
    ['plain', {}],
    ['Ctrl', { ctrlKey: true }],
    ['Meta', { metaKey: true }],
  ])('a %s click on the MLA keeps today\'s behavior: the row handles it', (_label, modifiers) => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const onRowClick = renderCell();
    fireEvent.click(screen.getByText('MLA1173065146'), modifiers);
    expect(open).not.toHaveBeenCalled();
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });

  it('tells the shortcuts in the MLA tooltip', () => {
    renderCell();
    expect(screen.getByText('MLA1173065146')).toHaveAttribute('title', expect.stringMatching(/Alt\+clic.*Mayús\+clic/));
  });
});
