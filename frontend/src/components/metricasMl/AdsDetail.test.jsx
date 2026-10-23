import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import AdsKpiBlock from './AdsKpiBlock';
import AdsUnattributedPanel from './AdsUnattributedPanel';
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

  it('shows the brand contribution when there is one', () => {
    render(<AdsKpiBlock ads={{ ...ADS_KPIS, contribution: 250000.5 }} />);
    const block = within(screen.getByRole('region', { name: 'Publicidad (ML Ads)' }));
    expect(block.getByText('Aporte de marcas')).toBeInTheDocument();
    expect(block.getByText('$ 250.000,50')).toBeInTheDocument();
  });

  it('shows no brand contribution when it is zero', () => {
    render(<AdsKpiBlock ads={{ ...ADS_KPIS, contribution: 0 }} />);
    expect(screen.queryByText('Aporte de marcas')).not.toBeInTheDocument();
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

describe('AdsUnattributedPanel', () => {
  const unattributed = {
    sin_producto_cost: 412380,
    account_level: { display: { cost_api: 1512500, cost_net: 1250000, subtracted: true }, brand: { cost: 380500, subtracted: false } },
  };

  it('lists the spend no row owns and which of it was subtracted', () => {
    render(<AdsUnattributedPanel unattributed={unattributed} />);
    const rows = within(screen.getByRole('region', { name: 'Publicidad sin producto' })).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText('Display')).toBeInTheDocument();
    expect(within(rows[0]).getByText('$ 1.250.000,00')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Restado')).toBeInTheDocument();
    expect(within(rows[1]).getByText('No restado')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Ads sin producto')).toBeInTheDocument();
  });

  it('renders nothing when the view is filtered (the API sends no account-level block)', () => {
    const { container } = render(<AdsUnattributedPanel unattributed={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
