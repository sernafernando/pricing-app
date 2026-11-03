/**
 * The listing type badge of Publicaciones ML and Métricas ML (owner, 2026-11-02: "que haga un badge y a simple
 * vista se vea que tipo de publicación es"): one label per kind the backend sends as `listing_kind`.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ListingKindBadge from './ListingKindBadge';

describe('ListingKindBadge', () => {
  it.each([
    ['clasica', 'Clásica'],
    ['cuotas_3', '3 cuotas'],
    ['cuotas_6', '6 cuotas'],
    ['cuotas_9', '9 cuotas'],
    ['cuotas_12', '12 cuotas'],
  ])('shows %s as "%s"', (kind, label) => {
    render(<ListingKindBadge kind={kind} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('shows a co-funded Clásica as Clásica, with a hint that ML co-funds its installments', () => {
    render(<ListingKindBadge kind="clasica_cofinanciada" />);
    expect(screen.getByText('Clásica')).toHaveAttribute('title', 'Clásica: cuotas cofinanciadas por ML');
  });

  it('names another ML listing type, and shows an unknown one as ML sends it', () => {
    render(<ListingKindBadge kind="free" />);
    expect(screen.getByText('Gratuita')).toBeInTheDocument();
    render(<ListingKindBadge kind="gold_premium_full" />);
    expect(screen.getByText('gold_premium_full')).toBeInTheDocument();
  });

  it('renders nothing when the row carries no kind (a backend without the field, a group row)', () => {
    const { container } = render(<ListingKindBadge kind={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('gives each installments kind its own tone, so they tell apart at a glance', () => {
    const kinds = ['clasica', 'cuotas_3', 'cuotas_6', 'cuotas_9', 'cuotas_12'];
    const classes = kinds.map((kind) => {
      const { container, unmount } = render(<ListingKindBadge kind={kind} />);
      const name = container.firstChild.className;
      unmount();
      return name;
    });
    expect(new Set(classes).size).toBe(kinds.length);
  });
});
