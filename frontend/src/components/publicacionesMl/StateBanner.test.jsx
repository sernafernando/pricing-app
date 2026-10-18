/**
 * StateBanner (publicaciones-ml-vista P11a.T5, S67.1-S67.3): says WHY a column
 * may read "—", from the `data_state` block of the list response.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import StateBanner from './StateBanner';
import { DATA_STATE_OK } from '../../test/visual/publicacionesMlFixtures';

const state = (overrides) => ({ ...DATA_STATE_OK, ...overrides });

describe('StateBanner', () => {
  it('renders nothing when the store is healthy', () => {
    const { container } = render(<StateBanner dataState={DATA_STATE_OK} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing before the first response', () => {
    const { container } = render(<StateBanner dataState={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('S67.1: an empty store says nothing has been synced yet', () => {
    render(<StateBanner dataState={state({ store_empty: true })} />);
    expect(screen.getByRole('status')).toHaveTextContent('Todavía no se sincronizó ninguna publicación');
  });

  it('S67.2: core-only names the resources that are not collected', () => {
    render(
      <StateBanner
        dataState={state({
          degraded: true,
          degradations: [
            { code: 'resource_not_collected', resource: 'sale_price', affects: ['price'] },
            { code: 'resource_not_collected', resource: 'stock', affects: ['stock.full', 'stock.own'] },
          ],
        })}
      />,
    );
    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent('Solo se sincronizan los datos básicos');
    expect(banner).toHaveTextContent('precio de oferta');
    expect(banner).toHaveTextContent('stock Full y Propio');
  });

  it('S67.3: a status that could not be read is neutral, not an error', () => {
    render(
      <StateBanner
        dataState={{
          available: false,
          reason: 'status_unavailable',
          degraded: true,
          degradations: [],
          sections_failed: [],
          store_empty: null,
          kill_switch: null,
          generated_at: null,
        }}
      />,
    );
    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent('No pudimos verificar el estado de la sincronización');
    expect(banner).toHaveAttribute('data-tone', 'neutral');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('names a disabled flag and what it affects', () => {
    render(
      <StateBanner
        dataState={state({
          degraded: true,
          degradations: [
            { code: 'flag_disabled', flag: 'events', affects: ['last_event', 'evento'] },
            { code: 'flag_disabled', flag: 'links', affects: ['link'] },
          ],
        })}
      />,
    );
    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent('Eventos desactivados');
    expect(banner).toHaveTextContent('Vínculos con productos desactivados');
  });

  it('mentions the kill switch and stale data', () => {
    render(
      <StateBanner
        dataState={state({
          kill_switch: true,
          degraded: true,
          degradations: [
            { code: 'kill_switch', affects: ['all'] },
            { code: 'stale_data', resource: 'items', p95_age_seconds: 3 * 86400 + 5, affects: ['all'] },
          ],
        })}
      />,
    );
    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent('La sincronización está pausada');
    expect(banner).toHaveTextContent('hace más de 3 días');
    expect(banner).not.toHaveTextContent('la mayoría');
  });

  it('states the real share of publications past the stale threshold', () => {
    render(
      <StateBanner
        dataState={state({
          degraded: true,
          degradations: [
            {
              code: 'stale_data',
              resource: 'items',
              p95_age_seconds: 7.4 * 86400,
              stale_days: 7,
              stale_rows: 1650,
              checked_rows: 25000,
              affects: ['all'],
            },
          ],
        })}
      />,
    );
    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent(
      'Parte de los datos está desactualizada: el 7% de las publicaciones se actualizó hace más de 7 días.',
    );
    expect(banner).not.toHaveTextContent('la mayoría');
  });

  it('falls back to the measured percentile when the share is not known', () => {
    render(
      <StateBanner
        dataState={state({
          degraded: true,
          degradations: [
            { code: 'stale_data', resource: 'items', p95_age_seconds: 7.4 * 86400, stale_days: 7, affects: ['all'] },
          ],
        })}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      'Parte de los datos está desactualizada: el 5% más antiguo se actualizó hace más de 7 días.',
    );
  });

  function renderStale(counts) {
    render(
      <StateBanner
        dataState={state({
          degraded: true,
          degradations: [
            {
              code: 'stale_data',
              resource: 'items',
              p95_age_seconds: 7.4 * 86400,
              stale_days: 7,
              affects: ['all'],
              ...counts,
            },
          ],
        })}
      />,
    );
    return screen.getByRole('status');
  }

  it('never rounds a non-zero stale share down to 0%', () => {
    expect(renderStale({ stale_rows: 1, checked_rows: 25000 })).toHaveTextContent(
      'Parte de los datos está desactualizada: el 1% de las publicaciones se actualizó hace más de 7 días.',
    );
  });

  it('falls back to the measured percentile when nothing was checked', () => {
    const banner = renderStale({ stale_rows: 0, checked_rows: 0 });
    expect(banner).toHaveTextContent('el 5% más antiguo se actualizó hace más de 7 días.');
    expect(banner).not.toHaveTextContent('NaN');
  });

  it.each([
    ['the checked count is missing', { stale_rows: 1650 }],
    ['the stale count is missing', { checked_rows: 25000 }],
    ['a count is null', { stale_rows: null, checked_rows: 25000 }],
  ])('falls back to the measured percentile when %s', (_label, counts) => {
    const banner = renderStale(counts);
    expect(banner).toHaveTextContent('el 5% más antiguo se actualizó hace más de 7 días.');
    expect(banner).not.toHaveTextContent('de las publicaciones');
  });

  it('mentions sections of the report that failed', () => {
    render(<StateBanner dataState={state({ degraded: true, sections_failed: ['queue'] })} />);
    expect(screen.getByRole('status')).toHaveTextContent('No se pudieron leer algunas secciones del estado');
  });

  it('does not invent a message for a degradation it does not know', () => {
    const { container } = render(
      <StateBanner dataState={state({ degraded: true, degradations: [{ code: 'something_new', affects: [] }] })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
