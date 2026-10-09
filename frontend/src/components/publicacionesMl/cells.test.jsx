/**
 * Cells of the Publicaciones ML table (publicaciones-ml-vista P11a.T4): every
 * nullable renders "—" (S4.1), never 0 or an empty cell.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PriceCell from './PriceCell';
import StockCell from './StockCell';
import LinkBadge from './LinkBadge';
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

describe('StockCell', () => {
  it('shows available, and Full / Propio when known', () => {
    render(<StockCell stock={ROUTER.stock} />);
    expect(screen.getByText('34')).toBeInTheDocument();
    expect(screen.getByText(/Full 20/)).toBeInTheDocument();
    expect(screen.getByText(/Propio 14/)).toBeInTheDocument();
  });

  it('keeps a real zero as 0 (not "—") and marks it as out of stock', () => {
    render(<StockCell stock={EPSON.stock} />);
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('Sin stock')).toBeInTheDocument();
    expect(screen.queryByText(/Full/)).not.toBeInTheDocument();
  });

  it('renders "—" when nothing is known', () => {
    render(<StockCell stock={EMPTY.stock} />);
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
