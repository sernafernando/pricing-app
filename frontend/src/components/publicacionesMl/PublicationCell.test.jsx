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

// The Tienda and Vínculo columns left the table: both now live in this cell, compact.
describe('PublicationCell store and link', () => {
  const cell = (overrides) => render(<PublicationCell item={makeItem({ item_id: 'MLA1', title: 'Router', ...overrides })} />);

  it('names the official store, or its id when it has no label, and nothing without one', () => {
    const { unmount } = cell({ store_label: 'TP-Link', official_store_id: 471846 });
    expect(screen.getByLabelText('Tienda: TP-Link')).toHaveTextContent('TP-Link');
    unmount();
    const second = cell({ store_label: null, official_store_id: 99 });
    expect(screen.getByLabelText('Tienda: Tienda 99')).toBeInTheDocument();
    second.unmount();
    cell({ store_label: null, official_store_id: null });
    expect(screen.queryByLabelText(/^Tienda:/)).not.toBeInTheDocument();
  });

  it.each([
    ['auto', 'Automático', 'success'],
    ['manual', 'Manual', 'info'],
    ['sin_producto', 'Sin producto', 'warning'],
    ['conflicto', 'Conflicto', 'danger'],
    ['no_evaluado', 'Sin evaluar', 'neutral'],
  ])('shows the link state %s as a toned icon named "Vínculo: %s"', (state, label, tone) => {
    cell({ link: { state, producto_item_id: null, codigo: null, descripcion: null, marca: null } });
    expect(screen.getByLabelText(`Vínculo: ${label}`)).toHaveAttribute('data-tone', tone);
  });

  it('a linked publication shows its product code, the description in the tooltip', () => {
    cell({ link: { state: 'manual', producto_item_id: 4102, codigo: 'EP-544-BK', descripcion: 'Tinta Epson 544', marca: 'EPSON' } });
    const link = screen.getByLabelText('Vínculo: Manual');
    expect(link).toHaveTextContent('EP-544-BK');
    expect(link).toHaveAttribute('title', 'Vínculo: Manual · EP-544-BK Tinta Epson 544');
  });
});
