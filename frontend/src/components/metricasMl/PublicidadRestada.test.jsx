import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PublicidadRestada from './PublicidadRestada';
import { waterfallLines } from '../../utils/metricasMlAds';
import { ADS_KPIS, ADS_WATERFALL_TODO } from './adsFixtures';

const renderCard = (ads) =>
  render(
    <MemoryRouter>
      <PublicidadRestada ads={ads} />
    </MemoryRouter>,
  );

const TODO = { ...ADS_KPIS, requested: 'todo', applied: 'todo', subtracted_total: 18294119.51, waterfall: ADS_WATERFALL_TODO };
// "Restar Ads" unfiltered: the account-level lines are shown but not added.
const MLA_ACCOUNT = {
  ...ADS_KPIS,
  waterfall: { ...ADS_WATERFALL_TODO, account_subtracted: false, total: 16663619.51 },
};

const rows = () =>
  within(screen.getByRole('region', { name: 'Publicidad restada' }))
    .getAllByRole('listitem')
    .map((li) => li.textContent);

describe('PublicidadRestada', () => {
  it('renders nothing while the toggle is off (no ads block)', () => {
    const { container } = renderCard(null);
    expect(container).toBeEmptyDOMElement();
  });

  it('breaks "Restar toda" into its lines, each with its chip, and the total', () => {
    renderCard(TODO);
    expect(rows()).toEqual([
      'Product Ads de publicaciones$ 17.516.239,51Restado',
      'Product Ads sin producto$ 412.380,00Restado',
      '− Aportes de marcas (Product Ads)- $ 1.265.000,00Aporte',
      '= Product Ads neto$ 16.663.619,51',
      '+ Display$ 1.550.000,00Restado',
      '− Aportes de marcas (Display)- $ 300.000,00Aporte',
      '+ Brand Ads$ 380.500,00Restado',
    ]);
    expect(screen.getByText('= Publicidad restada').parentElement.parentElement).toHaveTextContent(
      '= Publicidad restadaSe resta del Total Gauss y del markup$ 18.294.119,51',
    );
    expect(screen.getByRole('link', { name: /Ver aportes/ })).toHaveAttribute('href', '/ml-ads-aportes');
  });

  it('under "Restar toda" still explains what "Restar Ads" would leave out (Stitch 5736acfc)', () => {
    renderCard(TODO);
    expect(screen.getByText(/En "Restar Ads" solo se restan las líneas de Product Ads/)).toBeInTheDocument();
  });

  it('says how much Product Ads no aporte can cover (no campaign)', () => {
    renderCard(TODO);
    expect(screen.getByText(/son de anuncios sin campaña: ningún aporte puede cubrirlos/)).toHaveTextContent(
      'De Product Ads, $ 84.300,00 son de anuncios sin campaña',
    );
  });

  it('under "Restar Ads" shows Display and Brand Ads as not subtracted, outside the total', () => {
    renderCard(MLA_ACCOUNT);
    expect(rows().slice(4)).toEqual([
      '+ Display$ 1.550.000,00No restado',
      '− Aportes de marcas (Display)- $ 300.000,00No restado',
      '+ Brand Ads$ 380.500,00No restado',
    ]);
    expect(screen.getByText(/En "Restar Ads" solo se restan las líneas de Product Ads/)).toBeInTheDocument();
  });

  it('a filtered view has only its publications, no aporte line at zero and no notes', () => {
    renderCard(ADS_KPIS);
    expect(rows()).toEqual(['Product Ads de publicaciones$ 17.516.239,51Restado', '= Product Ads neto$ 17.516.239,51']);
    expect(screen.queryByText(/sin campaña/)).not.toBeInTheDocument();
    expect(screen.queryByText(/En "Restar Ads"/)).not.toBeInTheDocument();
  });

  it('says so when filters made "todo" apply as "mla", with the Aplicado chip', () => {
    renderCard({ ...ADS_KPIS, requested: 'todo', applied: 'mla' });
    expect(screen.getByRole('note')).toHaveTextContent('Con filtros solo se restan los Ads de publicaciones');
    expect(screen.getByText('Aplicado: Ads de publicaciones')).toBeInTheDocument();
  });

  it('keeps every line in the order the card reads', () => {
    expect(waterfallLines(ADS_WATERFALL_TODO).map((line) => line.key)).toEqual([
      'publications',
      'sin_producto',
      'pads_aporte',
      'pads_net',
      'display',
      'display_aporte',
      'brand',
    ]);
  });
});
