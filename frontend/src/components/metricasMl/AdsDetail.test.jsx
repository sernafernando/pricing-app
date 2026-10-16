import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import AdsKpiBlock from './AdsKpiBlock';
import { ADS_KPIS } from './adsFixtures';

describe('AdsKpiBlock', () => {
  it('shows the investment, the ratios and the traffic of the period', () => {
    render(<AdsKpiBlock ads={ADS_KPIS} />);
    const block = within(screen.getByRole('region', { name: 'Publicidad (ML Ads)' }));
    expect(block.getByText('$ 17.516.239,51')).toBeInTheDocument();
    expect(block.getByText('11,0%')).toBeInTheDocument();
    expect(block.getByText('9,07')).toBeInTheDocument();
    expect(block.getByText('4,3%')).toBeInTheDocument();
    expect(block.getByText('$ 182,00')).toBeInTheDocument();
    expect(block.getByText('4.812.340')).toBeInTheDocument();
    expect(block.getByText('96.247')).toBeInTheDocument();
  });

  it('shows a dash for a ratio whose denominator was zero', () => {
    render(<AdsKpiBlock ads={{ ...ADS_KPIS, acos_pct: null, roas: null }} />);
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('renders nothing with the toggle off', () => {
    const { container } = render(<AdsKpiBlock ads={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('warns about missing days instead of reading them as zero spend', () => {
    const coverage = { available: true, data_through: '2026-10-13', missing_days: [{ day: '2026-10-14' }], mismatch_days: [] };
    render(<AdsKpiBlock ads={{ ...ADS_KPIS, coverage }} />);
    expect(screen.getByText('Datos de Ads hasta el 13/10 · falta 1 día')).toBeInTheDocument();
  });

  it('says there is no data when the ledger has no trusted day', () => {
    const coverage = { available: false, data_through: null, missing_days: [], mismatch_days: [] };
    render(<AdsKpiBlock ads={{ ...ADS_KPIS, coverage }} />);
    expect(screen.getByText('Sin datos de Ads para el período')).toBeInTheDocument();
  });
});
