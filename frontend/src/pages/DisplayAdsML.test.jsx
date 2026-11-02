/**
 * DisplayAdsML (ml-ads-cupones-display S8): the Display tab of ML Ads. Every Display campaign with its catalog
 * and its figures over the chosen range (`GET /ml-ads/display`), period KPIs, the daily cost and a Total row.
 * Data: `src/test/fixtures/mlAdsDisplay.js`, built from the real captures.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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

const rowOf = (name) => screen.getByText(name).closest('tr');

describe('DisplayAdsML', () => {
  beforeEach(() => {
    permisosDenegados.clear();
    api.get.mockReset();
    api.get.mockResolvedValue({ data: DISPLAY_REPORT });
  });

  it('asks the Display report for the chosen range', async () => {
    render(<DisplayAdsML />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    const [path, { params }] = api.get.mock.calls[0];
    expect(path).toBe('/ml-ads/display');
    expect(params.date_from <= params.date_to).toBe(true);
  });

  it('shows each campaign with its catalog, figures and computed ratios', async () => {
    render(<DisplayAdsML />);
    const row = within(await waitFor(() => rowOf('XeroxB110')));
    expect(row.getByText('ID 335306')).toBeInTheDocument();
    expect(row.getByText('Conversión')).toBeInTheDocument();
    expect(row.getByText('Activa')).toBeInTheDocument();
    expect(row.getByText('07/09/2026')).toBeInTheDocument();
    expect(row.getByText('01/11/2026')).toBeInTheDocument();
    expect(row.getByText('$ 748.449,60')).toBeInTheDocument();
    expect(row.getByText('467.762')).toBeInTheDocument();
    expect(row.getByText('0,11 %')).toBeInTheDocument(); // 523 / 467.762, computed (ML sends 0)
    expect(row.getByText('$ 1.431,07')).toBeInTheDocument(); // CPC
    expect(row.getByText('$ 16.874.875,25')).toBeInTheDocument();
    expect(row.getByText('22,55')).toBeInTheDocument(); // ROAS
  });

  it('reads a ratio without its base as a dash, never as zero', async () => {
    render(<DisplayAdsML />);
    const row = within(await waitFor(() => rowOf('B110creativa')));
    expect(row.getByText('Pausada')).toBeInTheDocument();
    expect(row.getAllByText('—')).toHaveLength(4); // CTR, CPC, CPM, ROAS
    expect(row.queryByText('0,00 %')).not.toBeInTheDocument();
  });

  it('sums the period in the KPIs and the Total row, without summing reach across campaigns', async () => {
    render(<DisplayAdsML />);
    const kpis = within(await screen.findByRole('region', { name: 'Resumen de Display' }));
    expect(kpis.getByText('$ 4.456.152,77')).toBeInTheDocument();
    expect(kpis.getByText('2.940.354')).toBeInTheDocument();
    expect(kpis.getByText('3.755')).toBeInTheDocument();
    expect(kpis.getByText('$ 194.353.348,00')).toBeInTheDocument();
    expect(kpis.getByText('1.461 unid.')).toBeInTheDocument();
    expect(kpis.getByText('43,61')).toBeInTheDocument();
    const total = within(screen.getByText('Total').closest('tr'));
    expect(total.getByText('$ 4.456.152,77')).toBeInTheDocument();
    expect(total.queryByText('678.288')).not.toBeInTheDocument();
  });

  it('filters by search and by status without a new request', async () => {
    const user = userEvent.setup();
    render(<DisplayAdsML />);
    await screen.findByText('XeroxB110');
    await user.click(screen.getByRole('button', { name: /Pausadas/ }));
    expect(screen.queryByText('XeroxB110')).not.toBeInTheDocument();
    expect(screen.getByText('prueba')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Todas/ }));
    await user.type(screen.getByRole('searchbox', { name: 'Buscar campaña' }), 'tp-link');
    expect(screen.getByText('Tp-link-PVP')).toBeInTheDocument();
    expect(screen.queryByText('DisplayCatalogo')).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('draws the daily cost', async () => {
    render(<DisplayAdsML />);
    expect(await screen.findByRole('img', { name: /Costo diario/ })).toBeInTheDocument();
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
