/**
 * Cells of the Publicaciones ML table (publicaciones-ml-vista P11a.T4): every
 * nullable renders "—" (S4.1), never 0 or an empty cell.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PriceCell from './PriceCell';
import ErpStockCell from './ErpStockCell';
import LinkBadge from './LinkBadge';
import SkuDivergenceCell from './SkuDivergenceCell';
import LastEventCell from './LastEventCell';
import PublicationStatusPill from './PublicationStatusPill';
import { eventLabel } from './eventLabels';
import { ITEMS, makeItem } from '../../test/visual/publicacionesMlFixtures';

const [ROUTER, EPSON, EMPTY, GONE] = ITEMS;

describe('PriceCell', () => {
  it('shows the amount, and the regular price struck through when there is a promotion', () => {
    render(<PriceCell price={ROUTER.price} />);
    expect(screen.getByText('98.500,50')).toBeInTheDocument();
    expect(screen.getByText('112.000,00')).toBeInTheDocument();
    expect(screen.getByText(/Hot Sale/)).toBeInTheDocument();
  });

  it('badges the Productos fallback as "precio de Productos"', () => {
    render(<PriceCell price={EPSON.price} />);
    expect(screen.getByText('18.900,00')).toBeInTheDocument();
    expect(screen.getByText('precio de Productos')).toBeInTheDocument();
  });

  it('has no badge for a price that comes from ML', () => {
    render(<PriceCell price={GONE.price} />);
    expect(screen.queryByText('precio de Productos')).not.toBeInTheDocument();
  });

  it('renders "—" when there is no amount', () => {
    render(<PriceCell price={EMPTY.price} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('ErpStockCell', () => {
  it('shows the ERP quantity of the linked product', () => {
    render(<ErpStockCell erpStock={{ quantity: 12 }} />);
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('keeps a real zero (or less) as the figure and marks it as out of ERP stock', () => {
    render(<ErpStockCell erpStock={{ quantity: 0 }} />);
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('Sin stock ERP')).toBeInTheDocument();
  });

  it('renders "—" without a linked product, and for a backend that does not send it yet', () => {
    const { unmount } = render(<ErpStockCell erpStock={{ quantity: null }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    unmount();
    render(<ErpStockCell erpStock={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('LinkBadge', () => {
  it.each([
    ['auto', 'Automático'],
    ['manual', 'Manual'],
    ['sin_producto', 'Sin producto'],
    ['conflicto', 'Conflicto'],
    ['no_evaluado', 'Sin evaluar'],
  ])('labels %s as %s', (state, label) => {
    render(<LinkBadge link={makeItem({ link: { state } }).link} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('names the linked product when there is one', () => {
    render(<LinkBadge link={ROUTER.link} />);
    expect(screen.getByText('ARCHER-AX55')).toBeInTheDocument();
  });

  it('renders "—" when the link is missing altogether', () => {
    render(<LinkBadge link={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('LastEventCell', () => {
  it('shows the event in Spanish and when it happened', () => {
    render(<LastEventCell event={ROUTER.last_event} now={new Date('2026-10-08T12:05:00Z')} />);
    expect(screen.getByText('Precio modificado')).toBeInTheDocument();
    expect(screen.getByText('hace 2 h')).toBeInTheDocument();
  });

  it('renders "—" when the publication has no event yet', () => {
    render(<LastEventCell event={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('falls back to a generic Spanish label for an event nobody labelled', () => {
    expect(eventLabel('something_new')).toBe('Evento');
  });
});

describe('PublicationStatusPill', () => {
  it.each([
    ['active', 'Activa'],
    ['paused', 'Pausada'],
    ['closed', 'Cerrada'],
    ['under_review', 'En revisión'],
    ['inactive', 'Inactiva'],
  ])('labels %s as %s', (status, label) => {
    render(<PublicationStatusPill status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('says "Eliminada" for a publication that vanished from ML, whatever its last status', () => {
    render(<PublicationStatusPill status="closed" gone />);
    expect(screen.getByText('Eliminada')).toBeInTheDocument();
  });

  it('keeps the sub-status as a tooltip', () => {
    render(<PublicationStatusPill status="paused" subStatus={['out_of_stock']} />);
    expect(screen.getByText('Pausada')).toHaveAttribute('title', 'out_of_stock');
  });

  it('survives a null sub-status', () => {
    render(<PublicationStatusPill status="paused" subStatus={null} />);
    expect(screen.getByText('Pausada')).not.toHaveAttribute('title');
  });

  it('renders "—" without a status', () => {
    render(<PublicationStatusPill status={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('SkuDivergenceCell', () => {
  const LINKED = { state: 'auto', producto_item_id: 70, codigo: 'MAP-70', descripcion: 'Router del mapa', marca: null };
  const divergent = (overrides) =>
    makeItem({
      seller_sku: 'SKU-71',
      link: LINKED,
      sku_divergence: { kind: 'otro_producto', producto_item_id: 71, codigo: 'SKU-71', descripcion: 'Switch del SKU' },
      ...overrides,
    });

  it('names the kind, the SKU in Mercado Libre, the product the SKU names and the linked product', () => {
    render(<SkuDivergenceCell item={divergent()} />);
    expect(screen.getByText('Otro producto')).toBeInTheDocument();
    expect(screen.getByLabelText('SKU en Mercado Libre: SKU-71')).toBeInTheDocument();
    expect(screen.getByLabelText('Producto por SKU: SKU-71 Switch del SKU')).toBeInTheDocument();
    expect(screen.getByLabelText('Producto vinculado: MAP-70 Router del mapa')).toBeInTheDocument();
  });

  it('a SKU that names no single product says so, and has no product by SKU', () => {
    render(
      <SkuDivergenceCell
        item={divergent({ sku_divergence: { kind: 'sin_coincidencia', producto_item_id: null, codigo: null, descripcion: null } })}
      />,
    );
    expect(screen.getByText('SKU sin coincidencia')).toBeInTheDocument();
    expect(screen.getByLabelText('Producto por SKU: ninguno')).toBeInTheDocument();
    expect(screen.getByLabelText('Producto vinculado: MAP-70 Router del mapa')).toBeInTheDocument();
  });

  it('a publication without a SKU in Mercado Libre reads "Sin SKU"', () => {
    render(
      <SkuDivergenceCell
        item={divergent({ seller_sku: null, sku_divergence: { kind: 'sin_coincidencia', producto_item_id: null, codigo: null, descripcion: null } })}
      />,
    );
    expect(screen.getByLabelText('SKU en Mercado Libre: Sin SKU')).toBeInTheDocument();
  });

  it('renders "—" when the SKU agrees with the linked product', () => {
    render(<SkuDivergenceCell item={divergent({ sku_divergence: null })} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
