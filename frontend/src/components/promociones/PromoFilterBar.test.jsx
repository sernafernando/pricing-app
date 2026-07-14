import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import PromoFilterBar from './PromoFilterBar';
import { usePromoFilterStore } from '../../store/promoFilterStore';

describe('PromoFilterBar', () => {
  beforeEach(() => {
    usePromoFilterStore.setState({ selectedTypes: [] });
  });

  it('renders a chip per known promo type plus "Todas"', () => {
    render(<PromoFilterBar />);

    expect(screen.getByRole('button', { name: /todas/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^campaña$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^deal$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^smart$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^pre-negociada$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^descuento$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^dod$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^lightning$/i })).toBeInTheDocument();
  });

  it('"Todas" is aria-pressed when selectedTypes is empty', () => {
    render(<PromoFilterBar />);
    expect(screen.getByRole('button', { name: /todas/i })).toHaveAttribute('aria-pressed', 'true');
  });

  it('clicking a chip toggles the type in the store and updates aria-pressed', () => {
    render(<PromoFilterBar />);
    const smartChip = screen.getByRole('button', { name: /^smart$/i });

    expect(smartChip).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(smartChip);
    expect(usePromoFilterStore.getState().selectedTypes).toEqual(['SMART']);
    expect(smartChip).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(smartChip);
    expect(usePromoFilterStore.getState().selectedTypes).toEqual([]);
    expect(smartChip).toHaveAttribute('aria-pressed', 'false');
  });

  it('clicking "Todas" clears the filter', () => {
    usePromoFilterStore.setState({ selectedTypes: ['SMART', 'DEAL'] });
    render(<PromoFilterBar />);

    fireEvent.click(screen.getByRole('button', { name: /todas/i }));
    expect(usePromoFilterStore.getState().selectedTypes).toEqual([]);
  });
});
