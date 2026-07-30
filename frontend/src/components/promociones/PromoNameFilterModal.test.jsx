import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import PromoNameFilterModal from './PromoNameFilterModal';
import { usePromoFilterStore } from '../../store/promoFilterStore';

const promosByType = {
  DEAL: ['2x1', '3x2'],
  SMART: ['Promo Smart'],
};

describe('PromoNameFilterModal', () => {
  beforeEach(() => {
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
  });

  it('renders nothing when closed', () => {
    render(<PromoNameFilterModal open={false} onClose={() => {}} promosByType={promosByType} />);
    expect(screen.queryByText('2x1')).not.toBeInTheDocument();
  });

  it('renders one group per type present in promosByType, with a checkbox per name', () => {
    render(<PromoNameFilterModal open onClose={() => {}} promosByType={promosByType} />);

    expect(screen.getByText('Deal')).toBeInTheDocument();
    expect(screen.getByText('Smart')).toBeInTheDocument();
    expect(screen.getByLabelText('2x1')).toBeInTheDocument();
    expect(screen.getByLabelText('3x2')).toBeInTheDocument();
    expect(screen.getByLabelText('Promo Smart')).toBeInTheDocument();
  });

  it('omits a type with zero visible names', () => {
    render(<PromoNameFilterModal open onClose={() => {}} promosByType={{ DEAL: [] }} />);
    expect(screen.getByText(/no hay promociones cargadas/i)).toBeInTheDocument();
  });

  it('checking a name toggles it in the store', () => {
    render(<PromoNameFilterModal open onClose={() => {}} promosByType={promosByType} />);

    fireEvent.click(screen.getByLabelText('2x1'));
    expect(usePromoFilterStore.getState().selectedNames).toEqual({ DEAL: ['2x1'] });

    fireEvent.click(screen.getByLabelText('2x1'));
    expect(usePromoFilterStore.getState().selectedNames).toEqual({});
  });

  it('a null-named promo renders as "(sin nombre)" and is selectable', () => {
    render(<PromoNameFilterModal open onClose={() => {}} promosByType={{ DOD: [null] }} />);

    const checkbox = screen.getByLabelText('(sin nombre)');
    fireEvent.click(checkbox);
    expect(usePromoFilterStore.getState().selectedNames).toEqual({ DOD: [null] });
  });

  it('a per-group reset clears only that type\'s names', () => {
    usePromoFilterStore.setState({ selectedNames: { DEAL: ['2x1'], SMART: ['Promo Smart'] } });
    render(<PromoNameFilterModal open onClose={() => {}} promosByType={promosByType} />);

    fireEvent.click(screen.getAllByRole('button', { name: /todas/i })[0]);
    expect(usePromoFilterStore.getState().selectedNames).toEqual({ SMART: ['Promo Smart'] });
  });

  it('pressing Escape closes the modal', () => {
    let closed = false;
    render(<PromoNameFilterModal open onClose={() => (closed = true)} promosByType={promosByType} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closed).toBe(true);
  });
});
