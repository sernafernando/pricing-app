import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import CatalogStatusBadge from './CatalogStatusBadge';
import { CATALOG_STATES } from './catalogStatus';

/** Publicaciones ML's catalog-competition badge, mirroring Productos' row badge: mark, tone and price tooltip per status. */
describe('CatalogStatusBadge', () => {
  it('renders nothing for a product with no catalog or no status, or no product at all', () => {
    for (const product of [null, undefined, { has_catalog: false, catalog_status: 'winning' }, { has_catalog: true, catalog_status: null }]) {
      const { container, unmount } = render(<CatalogStatusBadge product={product} />);
      expect(container.firstChild).toBeNull();
      unmount();
    }
  });

  it('winning: a trophy with the price it wins at, the state in words', () => {
    render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'winning', catalog_winner_price: 12345.5 }} />);
    const badge = screen.getByRole('img', { name: 'Catálogo: ganando (Ganando a $12345.50)' });
    expect(badge).toHaveAttribute('title', 'Ganando a $12345.50');
    expect(badge).toHaveAttribute('data-status', 'winning');
    expect(badge.querySelector('svg')).toBeInTheDocument();
  });

  it('sharing first place: a handshake with the price it ties at', () => {
    render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'sharing_first_place', catalog_winner_price: 900 }} />);
    expect(screen.getByRole('img', { name: 'Catálogo: compartiendo el primer lugar (Empatando a $900.00)' })).toHaveAttribute('title', 'Empatando a $900.00');
  });

  it('competing: an alert with the price to win', () => {
    render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'competing', catalog_price_to_win: 870.1 }} />);
    expect(screen.getByRole('img', { name: 'Catálogo: compitiendo (Precio para ganar: $870.10)' })).toHaveAttribute('title', 'Precio para ganar: $870.10');
  });

  it('a price that is not a number has no tooltip and never breaks the row; a numeric string still reads', () => {
    const { container, unmount } = render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'winning', catalog_winner_price: 'n/a' }} />);
    expect(container.firstChild).not.toHaveAttribute('title');
    expect(container.firstChild).toHaveAttribute('aria-label', 'Catálogo: ganando');
    unmount();
    render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'competing', catalog_price_to_win: '870.1' }} />);
    expect(screen.getByRole('img')).toHaveAttribute('title', 'Precio para ganar: $870.10');
  });

  it.each(Object.entries(CATALOG_STATES))('every state has its icon and its words: %s', (status, { label }) => {
    render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: status }} />);
    expect(screen.getByRole('img', { name: `Catálogo: ${label}` }).querySelector('svg')).toBeInTheDocument();
  });

  it('a status named like an object member is still just an unknown status: a neutral badge', () => {
    for (const status of ['constructor', 'toString']) {
      const { container, unmount } = render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: status }} />);
      expect(container.firstChild.querySelector('svg')).toBeNull();
      expect(container.firstChild).toHaveTextContent('');
      expect(container.firstChild).toHaveAttribute('aria-label', `Catálogo: ${status}`);
      unmount();
    }
  });

  it("each state's tone comes from the shared table; an unknown status has none (the neutral tone)", () => {
    const { container, unmount } = render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'winning' }} />);
    expect(container.firstChild.style.getPropertyValue('--catalog-tone')).toBe(CATALOG_STATES.winning.tone);
    unmount();
    const other = render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'listed' }} />);
    expect(other.container.firstChild.style.getPropertyValue('--catalog-tone')).toBe('');
  });

  it('a price of 0 is no price, as in Productos: no tooltip', () => {
    const { container } = render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'winning', catalog_winner_price: 0 }} />);
    expect(container.firstChild).not.toHaveAttribute('title');
    expect(container.firstChild).toHaveAttribute('aria-label', 'Catálogo: ganando');
  });

  it('a status without its price has no tooltip; any other status is an empty neutral badge, as Productos', () => {
    const { container, unmount } = render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'competing' }} />);
    expect(container.firstChild).not.toHaveAttribute('title');
    expect(container.firstChild).toHaveAttribute('aria-label', 'Catálogo: compitiendo');
    unmount();
    const other = render(<CatalogStatusBadge product={{ has_catalog: true, catalog_status: 'listed' }} />);
    expect(other.container.firstChild.querySelector('svg')).toBeNull();
    expect(other.container.firstChild).toHaveAttribute('data-status', 'listed');
    expect(other.container.firstChild).toHaveAttribute('aria-label', 'Catálogo: listed');
  });
});
