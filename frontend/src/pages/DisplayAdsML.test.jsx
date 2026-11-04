/**
 * DisplayAdsML (ml-ads-cupones-display S8, redesigned after Stitch 56a8ea4c): the Display tab of ML Ads. Every
 * Display campaign with its catalog and its figures over the chosen range (`GET /ml-ads/display`), period KPIs with
 * the change against the previous period, the daily cost stacked by campaign, an expandable row with each campaign's
 * daily trend, and a Total row.
 * Data: `src/test/fixtures/mlAdsDisplay.js`, built from the real captures.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DisplayAdsML from './DisplayAdsML';
import api from '../services/api';
import { DISPLAY_REPORT } from '../test/fixtures/mlAdsDisplay';

const permisosDenegados = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => !permisosDenegados.has(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

// Campaign names also appear in the chart legend: rows are found inside the table.
const inTable = () => within(screen.getByRole('table'));
const rowOf = (name) => inTable().getByText(name).closest('tr');
const loaded = (name) => waitFor(() => inTable().getByText(name));
// Each range asks twice: itself and the previous period of the same length, which ends the day before it starts.
const currentCalls = () => {
  const first = api.get.mock.calls[0][1].params.date_from;
  return api.get.mock.calls.filter(([, config]) => config.params.date_from === first);
};
const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const setRange = (from, to) => {
  fireEvent.change(screen.getByLabelText('Desde'), { target: { value: from } });
  fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: to } });
};
// The previous period answers with its own report: same campaigns, half the attributed sales.
const withPrevious = (previous) =>
  api.get.mockImplementation((url, { params }) =>
    Promise.resolve({ data: params.date_from === '2026-08-08' ? previous : DISPLAY_REPORT }),
  );

describe('DisplayAdsML', () => {
  beforeEach(() => {
    permisosDenegados.clear();
    api.get.mockReset();
    api.get.mockResolvedValue({ data: DISPLAY_REPORT });
  });

  it('asks the Display report from the first of the month to today', async () => {
    const today = new Date();
    render(<DisplayAdsML />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get).toHaveBeenCalledWith('/ml-ads/display', {
      params: { date_from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), date_to: iso(today) },
    });
  });

  it('an inverted range asks for nothing and hides the last report', async () => {
    render(<DisplayAdsML />);
    await loaded('XeroxB110');
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2099-01-01' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Elegí un rango válido');
    expect(screen.queryByRole('cell', { name: /XeroxB110/ })).not.toBeInTheDocument();
    expect(currentCalls()).toHaveLength(1);
  });

  it('warns when Display days of the range are missing', async () => {
    const missing = [
      { source: 'display', advertiser_id: 25713, day: '2026-10-05', status: null },
      { source: 'display', advertiser_id: 714700, day: '2026-10-05', status: null },
    ];
    api.get.mockResolvedValue({ data: { ...DISPLAY_REPORT, coverage: { ...DISPLAY_REPORT.coverage, missing_days: missing } } });
    render(<DisplayAdsML />);
    expect(await screen.findByText(/Faltan 1 día de Display/)).toBeInTheDocument();
  });

  it('shows each campaign with its catalog, figures and computed ratios', async () => {
    render(<DisplayAdsML />);
    const row = within(await waitFor(() => rowOf('XeroxB110')));
    expect(row.getByText('ID 335306')).toBeInTheDocument();
    expect(row.getByText('Conversión')).toBeInTheDocument();
    expect(row.getByText('Activa')).toBeInTheDocument();
    expect(row.getByText('07/09/2026 – 01/11/2026')).toBeInTheDocument();
    expect(row.getByText('$ 748.449,60')).toBeInTheDocument();
    expect(row.getByText('467.762')).toBeInTheDocument();
    expect(row.getByText('0,11 %')).toBeInTheDocument(); // 523 / 467.762, computed (ML sends 0)
    expect(row.getByText('$ 1.431,07')).toBeInTheDocument(); // CPC
    expect(row.getByText('$ 16.874.875,25')).toBeInTheDocument();
    expect(row.getByText('22,5x')).toBeInTheDocument(); // ROAS
  });

  it('reads a ratio without its base as a dash, never as zero', async () => {
    render(<DisplayAdsML />);
    const row = within(await waitFor(() => rowOf('B110creativa')));
    expect(row.getByText('Pausada')).toBeInTheDocument();
    expect(row.getAllByText('—')).toHaveLength(4); // CTR, CPC, CPM, ROAS
    expect(row.queryByText('0,00 %')).not.toBeInTheDocument();
  });

  it('sums the period in the KPIs and the Total row, reach included as the sum of each day', async () => {
    render(<DisplayAdsML />);
    const kpis = within(await screen.findByRole('region', { name: 'Resumen de Display' }));
    expect(kpis.getByText('$ 4.456.152,77')).toBeInTheDocument();
    expect(kpis.getByText('2.940.354')).toBeInTheDocument();
    expect(kpis.getByText('3.755 clics · CTR 0,13 % · 678.288 alcance')).toBeInTheDocument();
    expect(kpis.getByText(/CPM \$ 1\.515,52/)).toBeInTheDocument();
    expect(kpis.getByText('$ 194.353.348,00')).toBeInTheDocument();
    expect(kpis.getByText('1.461 unidades vendidas')).toBeInTheDocument();
    expect(kpis.getByText('43,6x')).toBeInTheDocument();
    const total = within(screen.getByText('Total').closest('tr'));
    expect(total.getByText('$ 4.456.152,77')).toBeInTheDocument();
    expect(total.getByText('678.288')).toBeInTheDocument();
    expect(total.getByText('7 camp.')).toBeInTheDocument();
    expect(total.getByText('4 act. · 3 paus.')).toBeInTheDocument();
    expect(
      screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === 'Mostrando 7 de 7 campañas registradas'),
    ).toBeInTheDocument();
  });

  it('a paused campaign without activity keeps its real zeros', async () => {
    render(<DisplayAdsML />);
    const row = within(await waitFor(() => rowOf('prueba')));
    expect(row.getAllByText('$ 0,00')).toHaveLength(2); // cost and attributed sales
    expect(row.getAllByText('0').length).toBeGreaterThanOrEqual(3); // prints, reach, clicks
  });

  it('compares the attributed sales with the previous period of the same length', async () => {
    withPrevious({ ...DISPLAY_REPORT, totals: { ...DISPLAY_REPORT.totals, attributed_amount: 97176674 } });
    render(<DisplayAdsML />);
    setRange('2026-09-07', '2026-10-06');
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/ml-ads/display', {
        params: { date_from: '2026-08-08', date_to: '2026-09-06' },
      }),
    );
    const kpis = within(await screen.findByRole('region', { name: 'Resumen de Display' }));
    expect(await kpis.findByText('+100,0 % vs per. ant.')).toBeInTheDocument();
    expect(kpis.getAllByText('30 días').length).toBeGreaterThanOrEqual(1);
  });

  it('does not compare when the previous period has Display days missing, and says why', async () => {
    const missing = [{ source: 'display', advertiser_id: 25713, day: '2026-08-20', status: null }];
    withPrevious({ ...DISPLAY_REPORT, coverage: { ...DISPLAY_REPORT.coverage, missing_days: missing } });
    render(<DisplayAdsML />);
    setRange('2026-09-07', '2026-10-06');
    expect(await screen.findByText('Sin comparación: faltan 1 día del período anterior')).toBeInTheDocument();
    expect(screen.queryByText(/vs per\. ant\./)).not.toBeInTheDocument();
  });

  it('does not compare when the period itself has Display days missing, and says so', async () => {
    const missing = [{ source: 'display', advertiser_id: 25713, day: '2026-09-20', status: null }];
    const current = { ...DISPLAY_REPORT, coverage: { ...DISPLAY_REPORT.coverage, missing_days: missing } };
    api.get.mockImplementation((url, { params }) =>
      Promise.resolve({ data: params.date_from === '2026-08-08' ? DISPLAY_REPORT : current }),
    );
    render(<DisplayAdsML />);
    setRange('2026-09-07', '2026-10-06');
    expect(await screen.findByText('Sin comparación: faltan 1 día del período')).toBeInTheDocument();
  });

  it('without the current figures the active count is cleared, so the tab never shows a stale one', async () => {
    const onActiveCount = vi.fn();
    render(<DisplayAdsML onActiveCount={onActiveCount} />);
    await waitFor(() => expect(onActiveCount).toHaveBeenLastCalledWith(4));
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2099-01-01' } });
    await waitFor(() => expect(onActiveCount).toHaveBeenLastCalledWith(null));
  });

  it('Actualizar asks the range again', async () => {
    const user = userEvent.setup();
    render(<DisplayAdsML />);
    await loaded('XeroxB110');
    await user.click(screen.getByRole('button', { name: 'Actualizar' }));
    await waitFor(() => expect(currentCalls()).toHaveLength(2));
  });

  it('reports how many campaigns are active', async () => {
    const onActiveCount = vi.fn();
    render(<DisplayAdsML onActiveCount={onActiveCount} />);
    await waitFor(() => expect(onActiveCount).toHaveBeenLastCalledWith(4));
  });

  it('a row opens its daily trend: average daily spend over the covered days and the peak daily ROAS', async () => {
    const user = userEvent.setup();
    render(<DisplayAdsML />);
    await loaded('XeroxB110');
    const toggle = screen.getByRole('button', { name: 'Ver tendencia diaria de XeroxB110' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const trend = within(screen.getByRole('region', { name: 'Tendencia diaria de XeroxB110' }));
    expect(trend.getByText('Desglose de tendencia diaria: XeroxB110')).toBeInTheDocument();
    // One captured day (05/10): 27.226,79 spent, 1.658.026,88 attributed.
    expect(trend.getByText('$ 27.226,79/día')).toBeInTheDocument();
    expect(trend.getByText('60,9x (05/10)')).toBeInTheDocument();
    expect(trend.getByRole('img', { name: /Costo diario de XeroxB110/ })).toBeInTheDocument();
  });

  it('a campaign without days says so in its trend', async () => {
    const user = userEvent.setup();
    render(<DisplayAdsML />);
    await loaded('prueba');
    await user.click(screen.getByRole('button', { name: 'Ver tendencia diaria de prueba' }));
    const trend = within(screen.getByRole('region', { name: 'Tendencia diaria de prueba' }));
    expect(trend.getByText('Sin actividad en el período.')).toBeInTheDocument();
  });

  it('stacks the daily cost by campaign, with each campaign that spent in the legend', async () => {
    render(<DisplayAdsML />);
    setRange('2026-09-07', '2026-10-06');
    const chart = within(await screen.findByRole('region', { name: 'Costo diario por campaña' }));
    expect(chart.getByText('DisplayCatalogo')).toBeInTheDocument();
    expect(chart.getByText('($ 1,42M)')).toBeInTheDocument();
    expect(chart.getByText('($ 748K)')).toBeInTheDocument();
    expect(chart.queryByText('prueba')).not.toBeInTheDocument(); // no cost in the range
    expect(chart.getByRole('img', { name: /Costo diario por campaña/ })).toBeInTheDocument();
  });

  it('filters by search and by status without a new request', async () => {
    const user = userEvent.setup();
    render(<DisplayAdsML />);
    await loaded('XeroxB110');
    await user.click(screen.getByRole('button', { name: /Pausadas/ }));
    expect(screen.queryByRole('cell', { name: /XeroxB110/ })).not.toBeInTheDocument();
    expect(inTable().getByText('prueba')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Todas/ }));
    await user.type(screen.getByRole('searchbox', { name: 'Buscar campaña' }), 'tp-link');
    expect(inTable().getByText('Tp-link-PVP')).toBeInTheDocument();
    expect(inTable().queryByText('DisplayCatalogo')).not.toBeInTheDocument();
    expect(currentCalls()).toHaveLength(1);
  });

  it('says when no Display campaign was stored yet', async () => {
    api.get.mockResolvedValue({ data: { ...DISPLAY_REPORT, campaigns: [], daily: [] } });
    render(<DisplayAdsML />);
    expect(await screen.findByText('Todavía no hay campañas de Display sincronizadas.')).toBeInTheDocument();
  });

  it('shows the API error', async () => {
    api.get.mockRejectedValue({ response: { data: { detail: 'Rango inválido' } } });
    render(<DisplayAdsML />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Rango inválido');
  });

  it('without ver_ganancia it asks for the permission and requests nothing', () => {
    permisosDenegados.add('ml_metricas.ver_ganancia');
    render(<DisplayAdsML />);
    expect(screen.getByRole('alert')).toHaveTextContent('permiso');
    expect(api.get).not.toHaveBeenCalled();
  });
});
