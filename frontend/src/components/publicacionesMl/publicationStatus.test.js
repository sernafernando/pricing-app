import { describe, it, expect } from 'vitest';
import { publicationStatusInfo, subStatusTitle } from './publicationStatus';

// `ml_items.status` (the ML publications store) is the source of truth for a
// publication's status everywhere; these labels are the single Spanish map
// every status chip (Publicaciones ML, promotions tree, product info modal) uses.
describe('publicationStatusInfo', () => {
  it.each([
    ['active', 'Activa', 'success'],
    ['paused', 'Pausada', 'warning'],
    ['closed', 'Cerrada', 'danger'],
    ['under_review', 'En revisión', 'info'],
    ['inactive', 'Inactiva', 'neutral'],
    ['gone', 'Eliminada', 'danger'],
    ['never_existed', 'No existe en ML', 'danger'],
    ['no_ml_data', 'Sin datos de ML', 'neutral'],
  ])('maps %s to "%s"', (status, label, tone) => {
    expect(publicationStatusInfo(status)).toEqual({ label, tone });
  });

  it('shows an unknown ML status verbatim instead of hiding it', () => {
    expect(publicationStatusInfo('payment_required')).toEqual({ label: 'payment_required', tone: 'neutral' });
  });

  it('returns null when there is no status at all', () => {
    expect(publicationStatusInfo(null)).toBeNull();
    expect(publicationStatusInfo(undefined)).toBeNull();
  });
});

describe('subStatusTitle', () => {
  it('joins ML sub_status reasons', () => {
    expect(subStatusTitle(['paused_by_seller', 'out_of_stock'])).toBe('paused_by_seller, out_of_stock');
  });

  it('is undefined for an empty or missing list', () => {
    expect(subStatusTitle([])).toBeUndefined();
    expect(subStatusTitle(null)).toBeUndefined();
  });
});
