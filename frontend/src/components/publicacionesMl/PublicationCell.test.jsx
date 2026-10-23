/**
 * The Publicación cell links each publication to the Mercado Libre seller
 * panel: two icon links; the MLA tells the row's click shortcuts.
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
  // The page opens ML on the whole row (PublicacionesML.test.jsx): a click on the MLA is one more row click.
  it.each([
    ['plain', {}],
    ['Ctrl', { ctrlKey: true }],
    ['Meta', { metaKey: true }],
    ['Alt', { altKey: true }],
    ['Shift', { shiftKey: true }],
  ])('a %s click on the MLA reaches the row, which handles it', (_label, modifiers) => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const onRowClick = renderCell();
    fireEvent.click(screen.getByText('MLA1173065146'), modifiers);
    expect(open).not.toHaveBeenCalled();
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });

  it('tells the shortcuts in the MLA tooltip', () => {
    renderCell();
    expect(screen.getByText('MLA1173065146')).toHaveAttribute(
      'title',
      expect.stringMatching(/Ctrl\+clic.*Alt\+clic.*Mayús\+clic/),
    );
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

describe('PublicationCell seller SKU', () => {
  it('shows the publication SKU, labeled like the detail panel', () => {
    render(<PublicationCell item={makeItem({ seller_sku: 'AX55-SKU' })} />);
    const sku = screen.getByLabelText('SKU del vendedor: AX55-SKU');
    expect(sku).toHaveTextContent('AX55-SKU');
    expect(sku).toHaveAttribute('title', 'SKU del vendedor: AX55-SKU');
  });

  it('shows nothing when the publication has no SKU', () => {
    render(<PublicationCell item={makeItem({ seller_sku: null })} />);
    expect(screen.queryByLabelText(/SKU del vendedor/)).not.toBeInTheDocument();
  });
});

describe('PublicationCell SKU divergence', () => {
  it('flags a publication whose SKU disagrees with its linked product', () => {
    render(
      <PublicationCell
        item={makeItem({ sku_divergence: { kind: 'otro_producto', producto_item_id: 71, codigo: 'SKU-71', descripcion: 'Switch' } })}
      />,
    );
    expect(screen.getByLabelText('SKU distinto del producto vinculado: Otro producto')).toBeInTheDocument();
  });

  it('flags nothing when the SKU agrees', () => {
    render(<PublicationCell item={makeItem({ sku_divergence: null })} />);
    expect(screen.queryByLabelText(/SKU distinto/)).not.toBeInTheDocument();
  });
});
