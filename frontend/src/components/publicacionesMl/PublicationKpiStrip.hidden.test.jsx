import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PublicationKpiStrip from './PublicationKpiStrip';
import { publicationKpiOptions } from './publicationKpiOptions';
import { KPIS_RESPONSE, KPIS_RESPONSE_MARGIN } from '../../test/visual/publicacionesMlFixtures';

const state = (data) => ({ data, loading: false, error: null, reload: () => {} });
const labels = () => [...document.querySelectorAll('div[class*="label"] > span:first-child')].map((el) => el.textContent);
const strip = (data, isVisible) => render(<PublicationKpiStrip state={state(data)} periodo={30} onPeriodChange={() => {}} isVisible={isVisible} />);

describe('PublicationKpiStrip hideable cards', () => {
  it('renders every card with nothing hidden', () => {
    strip(KPIS_RESPONSE_MARGIN);
    expect(labels()).toEqual(publicationKpiOptions(KPIS_RESPONSE_MARGIN.kpis).map((o) => o.label));
    expect(labels()).toHaveLength(6);
  });

  it('lists Total Gauss and Markup only when the backend sent them (S2)', () => {
    expect(publicationKpiOptions(KPIS_RESPONSE.kpis).map((o) => o.id)).toEqual(['units', 'gross', 'rows_with_sales', 'ageing']);
    expect(publicationKpiOptions(KPIS_RESPONSE_MARGIN.kpis).map((o) => o.id)).toContain('markup');
  });

  it('drops a hidden card (S1, S5)', () => {
    strip(KPIS_RESPONSE_MARGIN, (id) => id !== 'markup');
    expect(labels()).not.toContain('Markup promedio');
    expect(labels()).toHaveLength(5);
  });

  it('keeps the Período control with every card hidden, and no card row (S5)', () => {
    strip(KPIS_RESPONSE_MARGIN, () => false);
    expect(labels()).toEqual([]);
    expect(document.querySelector('div[class*="cards"]')).toBeNull();
    expect(screen.getByRole('group', { name: 'Período' })).toBeInTheDocument();
  });

  it('says what each change compares to: the as many days right before', () => {
    render(<PublicationKpiStrip state={state(KPIS_RESPONSE_MARGIN)} periodo={15} onPeriodChange={() => {}} />);
    expect(screen.getAllByText('vs 15 días anteriores')).toHaveLength(4);
    for (const note of screen.getAllByText('vs 15 días anteriores')) {
      expect(note.parentElement.textContent).toMatch(/^[▲▼]?\s*[+−-]?[\d,]+ ?(%|pp) vs 15 días anteriores$/);
    }
  });
});
