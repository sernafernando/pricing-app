import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import AdsAppliedBanner from './AdsAppliedBanner';
import { ADS_KPIS } from './adsFixtures';

describe('AdsAppliedBanner', () => {
  it('renders nothing while the toggle is off (no ads block)', () => {
    const { container } = render(<AdsAppliedBanner ads={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('announces what was subtracted, with the formula', () => {
    render(<AdsAppliedBanner ads={ADS_KPIS} />);
    expect(screen.getByRole('status')).toHaveTextContent('Publicidad restada: $ 17.516.239,51 (Ads de publicaciones)');
    expect(screen.getByText(/Markup = \(margen - publicidad\) \/ costo/)).toBeInTheDocument();
    expect(screen.queryByText('Con filtros solo se restan los Ads de publicaciones')).not.toBeInTheDocument();
  });

  it('names the account-level spend when "todo" was applied', () => {
    render(<AdsAppliedBanner ads={{ ...ADS_KPIS, requested: 'todo', applied: 'todo', subtracted_total: 19559119.51 }} />);
    expect(screen.getByRole('status')).toHaveTextContent(
      'Publicidad restada: $ 19.559.119,51 (Ads de publicaciones, sin producto y cuenta)',
    );
  });

  it('says so when filters made "todo" apply as "mla", with the Aplicado chip', () => {
    render(<AdsAppliedBanner ads={{ ...ADS_KPIS, requested: 'todo', applied: 'mla', subtracted_total: 2192372.86 }} />);
    expect(screen.getByText('Con filtros solo se restan los Ads de publicaciones')).toBeInTheDocument();
    expect(screen.getByText('Aplicado: Ads de publicaciones')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Publicidad restada: $ 2.192.372,86 (Ads de publicaciones)');
  });
});
