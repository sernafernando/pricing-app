import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import PromoFilterBar from './PromoFilterBar';
import { usePromoFilterStore } from '../../store/promoFilterStore';

describe('PromoFilterBar', () => {
  beforeEach(() => {
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
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

  it('"Todas" is NOT pressed when only selectedNames is active', () => {
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: { DEAL: ['2x1'] } });
    render(<PromoFilterBar />);
    expect(screen.getByRole('button', { name: /todas/i })).toHaveAttribute('aria-pressed', 'false');
  });

  it('clicking "Todas" also clears selectedNames', () => {
    usePromoFilterStore.setState({ selectedTypes: ['SMART'], selectedNames: { DEAL: ['2x1'] } });
    render(<PromoFilterBar />);

    fireEvent.click(screen.getByRole('button', { name: /todas/i }));
    expect(usePromoFilterStore.getState().selectedTypes).toEqual([]);
    expect(usePromoFilterStore.getState().selectedNames).toEqual({});
  });

  it('renders a "Nombres" trigger that opens the name filter modal', () => {
    const promosCacheRef = {
      current: new Map([
        ['MLA1', { status: 'ok', data: { promotions: [{ promotion_type: 'DEAL', name: '2x1' }] } }],
      ]),
    };
    render(<PromoFilterBar promosCacheRef={promosCacheRef} />);

    expect(screen.queryByText('2x1')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /nombres/i }));
    expect(screen.getByText('2x1')).toBeInTheDocument();
  });

  it('shows a count badge on the "Nombres" trigger when selectedNames is non-empty', () => {
    usePromoFilterStore.setState({ selectedNames: { DEAL: ['2x1'] } });
    render(<PromoFilterBar />);
    expect(screen.getByRole('button', { name: /nombres \(1\)/i })).toBeInTheDocument();
  });

  it('the "Nombres" badge counts selected names, not selected types', () => {
    usePromoFilterStore.setState({ selectedNames: { DEAL: ['2x1', '3x2', '4x3'] } });
    render(<PromoFilterBar />);
    expect(screen.getByRole('button', { name: /nombres \(3\)/i })).toBeInTheDocument();
  });
});
