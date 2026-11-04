/**
 * MlAds (ml-ads-cupones-display S8): one "ML Ads" page with the Aportes and Display tabs. The old URL keeps
 * opening Aportes; the active tab lives in `?tab=` so a link opens it directly.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import MlAds from './MlAds';

vi.mock('./AportesAdsML', () => ({ default: () => <p>contenido aportes</p> }));
vi.mock('./DisplayAdsML', async () => {
  const { useEffect } = await import('react');
  return {
    default: function DisplayStub({ onActiveCount }) {
      useEffect(() => onActiveCount?.(4), [onActiveCount]);
      return <p>contenido display</p>;
    },
  };
});

function Where() {
  return <span data-testid="where">{useLocation().search}</span>;
}

const renderAt = (url) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/ml-ads-aportes"
          element={
            <>
              <MlAds />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );

describe('MlAds', () => {
  beforeEach(() => vi.clearAllMocks());

  it('is the ML Ads page and the old URL opens Aportes', () => {
    renderAt('/ml-ads-aportes');
    expect(screen.getByRole('heading', { level: 1, name: 'ML Ads' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Aportes' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('contenido aportes')).toBeInTheDocument();
  });

  it('switching to Display shows it and keeps the tab in the URL', async () => {
    const user = userEvent.setup();
    renderAt('/ml-ads-aportes');
    await user.click(screen.getByRole('tab', { name: 'Display' }));
    expect(screen.getByText('contenido display')).toBeInTheDocument();
    expect(screen.queryByText('contenido aportes')).not.toBeInTheDocument();
    expect(screen.getByTestId('where')).toHaveTextContent('?tab=display');
  });

  it('a link with ?tab=display opens Display', () => {
    renderAt('/ml-ads-aportes?tab=display');
    expect(screen.getByRole('tab', { name: 'Display' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('contenido display');
  });

  it('an unknown tab opens Aportes', () => {
    renderAt('/ml-ads-aportes?tab=cupones');
    expect(screen.getByText('contenido aportes')).toBeInTheDocument();
  });

  it('the arrow keys move between tabs', async () => {
    const user = userEvent.setup();
    renderAt('/ml-ads-aportes');
    screen.getByRole('tab', { name: 'Aportes' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Display' })).toHaveFocus();
    expect(screen.getByText('contenido display')).toBeInTheDocument();
  });

  it('the Display tab shows how many campaigns are active once Display reported them', () => {
    renderAt('/ml-ads-aportes?tab=display');
    const tab = screen.getByRole('tab', { name: 'Display' });
    expect(tab).toHaveTextContent('4 Activas');
  });

  it('before Display reported, the tab has no count', () => {
    renderAt('/ml-ads-aportes');
    expect(screen.getByRole('tab', { name: 'Display' })).not.toHaveTextContent('Activas');
  });
});
