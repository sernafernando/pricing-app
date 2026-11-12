/**
 * AportesAdsML (ml-ads-brand-contribution S10): the page that shows the brand contributions loaded on Product Ads
 * campaigns, with each campaign's cost in the chosen range, and loads, edits and deletes them: the fixed-amount
 * settlement rule (S6), the manage permission (S7) and the backend's 422 message. Its layout follows the Stitch
 * redesign (ml-ads-contribution-redesign S3): KPI tiles, toolbar filters, APORTE/NETO columns and a Total row.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AportesAdsML from './AportesAdsML';
import api from '../services/api';
import { APORTES_VIEW } from './aportesFixtures';
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

const CONTRIBUTION = {
  id: 7,
  advertiser_id: 714700,
  campaign_id: 55,
  kind: 'fixed_amount',
  value: 150000,
  date_from: '2026-10-01',
  date_to: '2026-10-31',
  settlement: 'refund_difference',
  brand: 'TP-Link',
  note: 'Acuerdo trimestral',
  created_by_id: 1,
  updated_by_id: 1,
  created_at: '2026-10-01T10:00:00',
  updated_at: '2026-10-01T10:00:00',
};

const CAMPAIGNS = {
  campaigns: [
    {
      advertiser_id: 714700,
      advertiser_name: 'TPLINK',
      campaign_id: 55,
      name: 'Routers',
      status: 'active',
      cost: 98765.4,
      contribution: 50000,
      contributions: [CONTRIBUTION],
    },
    {
      advertiser_id: 25713,
      advertiser_name: 'GAUSS',
      campaign_id: 66,
      name: 'Notebooks',
      status: 'paused',
      cost: 1200,
      contribution: 0,
      contributions: [
        {
          ...CONTRIBUTION,
          id: 8,
          kind: 'percentage',
          value: 25,
          settlement: null,
          brand: null,
          note: null,
          date_from: '2025-01-01',
          date_to: '2025-01-31',
        },
      ],
    },
    { advertiser_id: 25713, advertiser_name: 'GAUSS', campaign_id: 77, name: null, status: null, cost: 800, contribution: 0, contributions: [] },
  ],
};

const rowOf = (text) => screen.getByText(text).closest('tr');

// The page opens on the current month; these tests pin October 2026, the range CONTRIBUTION covers.
async function renderOctober() {
  render(<AportesAdsML />);
  await screen.findByText('Routers');
  fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-10-01' } });
  fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-10-31' } });
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/ml-ads/campaigns', {
    params: { date_from: '2026-10-01', date_to: '2026-10-31' },
  }));
  await screen.findByText('Routers');
}

async function openCreate(user, campaign = 'Notebooks') {
  render(<AportesAdsML />);
  await screen.findByText(campaign);
  await user.click(within(rowOf(campaign)).getByRole('button', { name: /agregar aporte/i }));
}

// The form also asks `/ml-ads/contributions/preview`; a refresh is a new `/ml-ads/campaigns` request.
const campaignRequests = () => api.get.mock.calls.filter(([url]) => url === '/ml-ads/campaigns').length;

const valueInput = () => screen.getByLabelText(/^(Porcentaje|Monto)$/);

async function fillCommon(user, { value = '10', brand = 'TP-Link' } = {}) {
  await user.clear(valueInput());
  await user.type(valueInput(), value);
  await user.type(screen.getByLabelText('Desde', { selector: '#aporte-desde' }), '2026-10-01');
  await user.type(screen.getByLabelText('Hasta', { selector: '#aporte-hasta' }), '2026-10-15');
  if (brand) {
    await screen.findByRole('option', { name: brand });
    await user.selectOptions(screen.getByLabelText('Marca'), brand);
  }
}

// The brands an aporte may name: `GET /marcas`, the list Productos and Sell-in use (ml-ads-aportes-robust S1).
const MARCAS = { marcas: ['EPSON', 'Lenovo', 'TP-Link'] };
const answer = (url, preview) => {
  if (url === '/marcas') return MARCAS;
  if (url === '/ml-ads/contributions') return APORTES_VIEW;
  if (url === '/ml-ads/display') return DISPLAY_REPORT;
  return url.endsWith('/preview') ? preview : CAMPAIGNS;
};

beforeEach(() => {
  vi.clearAllMocks();
  permisosDenegados.clear();
  api.get.mockImplementation((url) =>
    Promise.resolve({ data: answer(url, { spend: 742300, counted: 500000, net: 242300, warnings: [], data_through: null }) }),
  );
  api.post.mockResolvedValue({ data: {} });
  api.put.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({ data: {} });
});

describe('campaign list', () => {
  it('lists each campaign with its cost, contribution, net and one-line contribution chips', async () => {
    render(<AportesAdsML />);
    expect(await screen.findByText('Routers')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-ads/campaigns', {
      params: expect.objectContaining({ date_from: expect.any(String), date_to: expect.any(String) }),
    });

    const routers = within(rowOf('Routers'));
    expect(routers.getByText('55')).toBeInTheDocument();
    expect(routers.getByText('TPLINK')).toBeInTheDocument();
    expect(routers.getByText('Activa')).toBeInTheDocument();
    expect(routers.getByText('$ 98.765,40')).toBeInTheDocument();
    expect(routers.getByText('$ 50.000,00')).toBeInTheDocument();
    expect(routers.getByText('$ 48.765,40')).toBeInTheDocument();
    expect(routers.getByText('$ 150.000,00')).toBeInTheDocument();
    const badge = routers.getByText('Diferencia');
    expect(badge).toHaveAttribute('title', 'Se devuelve la diferencia');
    expect(routers.getByText('01/10/26 → 31/10/26')).toBeInTheDocument();
    expect(badge.closest('li')).toHaveAttribute('title', 'TP-Link · Acuerdo trimestral');
    expect(badge.closest('li')).toHaveTextContent('TP-Link · Acuerdo trimestral');

    const notebooks = within(rowOf('Notebooks'));
    expect(notebooks.getByText('Pausada')).toBeInTheDocument();
    expect(notebooks.getByText('25%')).toBeInTheDocument();
    expect(notebooks.queryByText(/^(Todo|Diferencia)$/)).not.toBeInTheDocument();

    expect(within(rowOf('Campaña 77')).getByText('Sin aportes')).toBeInTheDocument();

    const total = within(rowOf('Total (3 de 3 campañas)'));
    expect(total.getByText('$ 100.765,40')).toBeInTheDocument();
    expect(total.getByText('$ 50.000,00')).toBeInTheDocument();
    expect(total.getByText('$ 50.765,40')).toBeInTheDocument();
  });

  it('sums the range in the KPI tiles', async () => {
    await renderOctober();
    const tiles = within(screen.getByRole('region', { name: 'Resumen de aportes' }));
    expect(tiles.getByText('Costo Ads del período').parentElement).toHaveTextContent('$ 100.765,40');
    expect(tiles.getByText('Aporte de marcas').parentElement).toHaveTextContent('$ 50.000,00');
    expect(tiles.getByText('Aporte de marcas').parentElement).toHaveTextContent('49,6 % del costo');
    expect(tiles.getByText('Costo neto').parentElement).toHaveTextContent('$ 50.765,40');
    // Only Routers has a contribution touching the range: Notebooks' is from January 2025.
    expect(tiles.getByText('Campañas con aporte').parentElement).toHaveTextContent('1 de 3');
  });

  it('shows the backend message when the list fails', async () => {
    api.get.mockRejectedValue({
      response: { status: 422, data: { error: { code: 'VALIDATION_ERROR', message: 'the range is at most 366 days' } } },
    });
    render(<AportesAdsML />);
    await waitFor(() => expect(screen.getByText('the range is at most 366 days')).toBeInTheDocument());
  });
});

describe('total row', () => {
  it('says "1 campaña" and greys a zero contribution like the rows do', async () => {
    api.get.mockResolvedValue({
      data: { campaigns: [{ advertiser_id: 1, campaign_id: 9, name: 'Sola', status: null, cost: 500, contribution: 0, contributions: [] }] },
    });
    render(<AportesAdsML />);
    const total = within(await screen.findByText('Total (1 de 1 campaña)').then((cell) => cell.closest('tr')));
    const rowZero = within(rowOf('Sola')).getByText('$ 0,00');
    expect(total.getByText('$ 0,00')).toHaveClass(rowZero.className);
  });
});

describe('quiet table', () => {
  it('prints a row aporte like its neto and puts the add button in its own column', async () => {
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    const routers = within(rowOf('Routers'));
    expect(routers.getByText('$ 50.000,00')).toHaveClass(routers.getByText('$ 48.765,40').className, { exact: true });
    const addCell = routers.getByRole('button', { name: 'Agregar aporte a Routers' }).closest('td');
    expect(addCell.querySelector('li')).toBeNull();
    expect(screen.getAllByRole('columnheader')).toHaveLength(7);
  });
});

describe('summary tiles', () => {
  it('shows a dash, not $ 0,00, while the range loads', async () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(<AportesAdsML />);
    const tiles = within(screen.getByRole('region', { name: 'Resumen de aportes' }));
    expect(tiles.queryByText('$ 0,00')).not.toBeInTheDocument();
    expect(tiles.queryByText(/campañas?$/)).not.toBeInTheDocument();
    expect(tiles.queryByText(/^de /)).not.toBeInTheDocument();
  });
});

describe('toolbar filters', () => {
  it('drops an advertiser filter the new range no longer offers', async () => {
    const user = userEvent.setup();
    await renderOctober();
    await user.selectOptions(screen.getByLabelText('Anunciante'), 'TPLINK');
    api.get.mockResolvedValueOnce({
      data: {
        campaigns: [{ advertiser_id: 25713, advertiser_name: 'GAUSS', campaign_id: 9, name: 'Solo Gauss', status: null, cost: 10, contribution: 0, contributions: [] }],
      },
    });
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-09-01' } });
    expect(await screen.findByText('Solo Gauss')).toBeInTheDocument();
    expect(screen.getByLabelText('Anunciante')).toHaveValue('');
  });

  it('says so when the filters leave no campaign, and counts one campaña in the singular', async () => {
    const user = userEvent.setup();
    await renderOctober();
    await user.type(screen.getByPlaceholderText('Buscar campaña…'), 'zzz');
    expect(screen.getByText('Ninguna campaña coincide con los filtros.')).toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText('Buscar campaña…'));
    await user.type(screen.getByPlaceholderText('Buscar campaña…'), 'Routers');
    expect(within(screen.getByRole('region', { name: 'Resumen de aportes' })).getByText('1 campaña')).toBeInTheDocument();
  });

  it('narrows the loaded rows by search, contribution and advertiser without asking again', async () => {
    const user = userEvent.setup();
    await renderOctober();
    const requests = api.get.mock.calls.length;

    await user.type(screen.getByPlaceholderText('Buscar campaña…'), 'note');
    expect(screen.queryByText('Routers')).not.toBeInTheDocument();
    expect(screen.getByText('Notebooks')).toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText('Buscar campaña…'));
    await user.type(screen.getByPlaceholderText('Buscar campaña…'), '77');
    expect(screen.getByText('Campaña 77')).toBeInTheDocument();
    expect(screen.queryByText('Notebooks')).not.toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText('Buscar campaña…'));

    await user.click(screen.getByRole('button', { name: 'Con aporte' }));
    expect(screen.getByText('Routers')).toBeInTheDocument();
    expect(screen.queryByText('Notebooks')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sin aporte' }));
    expect(screen.queryByText('Routers')).not.toBeInTheDocument();
    expect(screen.getByText('Campaña 77')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Todas' }));

    await user.selectOptions(screen.getByLabelText('Anunciante'), 'GAUSS');
    expect(screen.queryByText('Routers')).not.toBeInTheDocument();
    expect(screen.getByText('Total (2 de 3 campañas)')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(requests);
  });
});

describe('range changes', () => {
  it('keeps the newest range when an older response arrives last', async () => {
    let resolveOld;
    api.get
      .mockImplementationOnce(() => new Promise((resolve) => (resolveOld = resolve)))
      .mockResolvedValueOnce({
        data: { campaigns: [{ advertiser_id: 1, campaign_id: 9, name: 'Nuevo rango', status: null, cost: 0, contribution: 0, contributions: [] }] },
      });
    render(<AportesAdsML />);
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-09-01' } });
    expect(await screen.findByText('Nuevo rango')).toBeInTheDocument();

    resolveOld({ data: CAMPAIGNS });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText('Routers')).not.toBeInTheDocument();
    expect(screen.getByText('Nuevo rango')).toBeInTheDocument();
  });
});

describe('permissions', () => {
  it('without ml_metricas.ver_ganancia shows a notice and asks the API for nothing', () => {
    permisosDenegados.add('ml_metricas.ver_ganancia');
    render(<AportesAdsML />);
    expect(screen.getByText(/permiso para ver la ganancia/i)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});

describe('invalid range', () => {
  it('asks nothing while a date is empty or the range is inverted', async () => {
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    api.get.mockClear();
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2099-01-01' } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(api.get).not.toHaveBeenCalled();
  });
});

describe('manage contributions', () => {
  it('hides the manage actions without ml_metricas.gestionar_aportes_ads', async () => {
    permisosDenegados.add('ml_metricas.gestionar_aportes_ads');
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    expect(screen.queryByRole('button', { name: /agregar aporte/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /editar aporte/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /borrar aporte/i })).not.toBeInTheDocument();
  });

  it('requires a settlement choice for a fixed amount and sends it', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '50000' });
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(await screen.findByText(/elegí si se recibe todo o se devuelve la diferencia/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.click(screen.getByLabelText('Se recibe todo'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith('/ml-ads/contributions', {
      advertiser_id: 25713,
      campaign_id: 66,
      kind: 'fixed_amount',
      value: 50000,
      date_from: '2026-10-01',
      date_to: '2026-10-15',
      settlement: 'full',
      brand: 'TP-Link',
      note: null,
    });
  });

  it('sends no settlement for a percentage, then closes the form and refreshes the list', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    expect(screen.queryByLabelText('Se recibe todo')).not.toBeInTheDocument();
    await fillCommon(user, { value: '25' });
    await user.selectOptions(screen.getByLabelText('Marca'), 'Lenovo');
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const [, body] = api.post.mock.calls[0];
    expect(body).toMatchObject({ kind: 'percentage', value: 25, brand: 'Lenovo' });
    expect(body).not.toHaveProperty('settlement');
    await waitFor(() => expect(campaignRequests()).toBe(2));
    expect(screen.queryByRole('button', { name: 'Guardar aporte' })).not.toBeInTheDocument();
  });

  it('edits a contribution with PUT and refreshes the list', async () => {
    const user = userEvent.setup();
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(within(rowOf('Routers')).getByRole('button', { name: /editar aporte/i }));
    expect(screen.getByLabelText('Devuelve la diferencia')).toBeChecked();
    // An edit cannot move a contribution to another campaign (the API answers 422).
    expect(screen.getByLabelText('Campaña')).toBeDisabled();
    await user.clear(valueInput());
    await user.type(valueInput(), '200000');
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put).toHaveBeenCalledWith(
      '/ml-ads/contributions/7',
      expect.objectContaining({
        advertiser_id: 714700,
        campaign_id: 55,
        value: 200000,
        settlement: 'refund_difference',
        brand: 'TP-Link',
        note: 'Acuerdo trimestral',
      }),
    );
    await waitFor(() => expect(campaignRequests()).toBe(2));
  });

  it('keeps the delete modal open while the delete is in flight, so its error never leaks to another one', async () => {
    const user = userEvent.setup();
    api.delete.mockImplementation(() => new Promise(() => {}));
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(within(rowOf('Routers')).getByRole('button', { name: /borrar aporte/i }));
    await user.click(screen.getByRole('button', { name: 'Borrar aporte' }));
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeDisabled();
  });

  it('deletes a contribution after confirming and refreshes the list', async () => {
    const user = userEvent.setup();
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(within(rowOf('Routers')).getByRole('button', { name: /borrar aporte/i }));
    expect(api.delete).not.toHaveBeenCalled();
    const summary = within(screen.getByText('¿Borrar este aporte?').closest('.modal-tesla'));
    expect(summary.getAllByText('Routers').length).toBeGreaterThan(0);
    expect(summary.getByText('$ 150.000,00')).toBeInTheDocument();
    expect(summary.getByText('Diferencia')).toBeInTheDocument();
    expect(summary.getByText('01/10/2026 → 31/10/2026')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Borrar aporte' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/ml-ads/contributions/7'));
    await waitFor(() => expect(campaignRequests()).toBe(2));
  });

  it('keeps the confirmation open with the backend message when a delete fails', async () => {
    const user = userEvent.setup();
    api.delete.mockRejectedValue({ response: { status: 404, data: { error: { message: 'contribution 7 does not exist' } } } });
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(within(rowOf('Routers')).getByRole('button', { name: /borrar aporte/i }));
    await user.click(screen.getByRole('button', { name: 'Borrar aporte' }));
    expect(await screen.findByText('contribution 7 does not exist')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Borrar aporte' })).toBeInTheDocument();
  });

  it('loads a contribution from the header button, choosing its campaign', async () => {
    const user = userEvent.setup();
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(screen.getByRole('button', { name: 'Agregar aporte' }));
    await fillCommon(user, { value: '25' });
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(await screen.findByText('Elegí la campaña.')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Campaña'), '25713-66');
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/ml-ads/contributions',
        expect.objectContaining({ advertiser_id: 25713, campaign_id: 66, kind: 'percentage', value: 25 }),
      ),
    );
  });

  it('previews what the contribution would cover before saving', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '500000' });
    await user.click(screen.getByLabelText('Devuelve la diferencia'));
    const summary = within(await screen.findByLabelText('Lo que cubre el aporte'));
    expect(summary.getAllByRole('term').map((t) => t.textContent)).toEqual([
      'Costo de la campaña en el rango',
      'Aporte que cuenta',
      'Neto',
    ]);
    expect(summary.getAllByRole('definition').map((d) => d.textContent)).toEqual([
      '$ 742.300,00',
      '$ 500.000,00',
      '$ 242.300,00',
    ]);
    expect(api.get).toHaveBeenLastCalledWith('/ml-ads/contributions/preview', {
      params: {
        advertiser_id: 25713,
        campaign_id: 66,
        kind: 'fixed_amount',
        value: 500000,
        date_from: '2026-10-01',
        date_to: '2026-10-15',
        settlement: 'refund_difference',
        brand: 'TP-Link',
        note: null,
      },
    });
  });

  it("shows the backend's 422 message and keeps the form open", async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValue({
      response: {
        status: 422,
        data: { error: { code: 'VALIDATION_ERROR', message: 'the range overlaps contribution 7', field: 'date_from' } },
      },
    });
    await openCreate(user);
    await fillCommon(user);
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(await screen.findByText('the range overlaps contribution 7')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Guardar aporte' })).toBeInTheDocument();
  });

  it('shows the generic message, as an alert, when the 422 detail is a list of field errors', async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValue({
      response: { status: 422, data: { detail: [{ loc: ['body', 'value'], msg: 'too many digits', type: 'decimal' }] } },
    });
    await openCreate(user);
    await fillCommon(user);
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(await screen.findByText('No se pudo guardar el aporte')).toHaveAttribute('role', 'alert');
  });
});

describe('robust loading (ml-ads-aportes-robust)', () => {
  const previewWith = (preview) =>
    api.get.mockImplementation((url) => Promise.resolve({ data: answer(url, { warnings: [], data_through: null, ...preview }) }));

  it('picks the brand from the brand list and does not save without one', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    await fillCommon(user, { brand: null });
    expect(api.get).toHaveBeenCalledWith('/marcas');
    expect(within(screen.getByLabelText('Marca')).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Elegí una marca',
      'EPSON',
      'Lenovo',
      'TP-Link',
    ]);
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(await screen.findByText('Elegí la marca.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('sends a fixed amount typed with IVA marked, so it is stored without it', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '121000' });
    await user.click(screen.getByLabelText('Devuelve la diferencia'));
    await user.click(screen.getByLabelText('El monto incluye IVA'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toMatchObject({ value: 121000, iva_included: true });
  });

  it('a percentage offers no IVA choice and sends none', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    expect(screen.queryByLabelText('El monto incluye IVA')).not.toBeInTheDocument();
    await fillCommon(user);
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('iva_included');
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('confirm_over_spend');
  });

  it('asks to confirm a full amount above the range cost before saving it', async () => {
    previewWith({ spend: 1000, counted: 5000, net: -4000, over_spend: true });
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    const confirm = await screen.findByLabelText('Confirmo que el aporte supera el costo de la campaña en el rango');
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(await screen.findByText('Confirmá que el aporte supera el costo de la campaña en el rango.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    await user.click(confirm);
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toMatchObject({ settlement: 'full', confirm_over_spend: true });
  });

  const CONFIRM_LABEL = 'Confirmo que el aporte supera el costo de la campaña en el rango';
  it.each([
    ['amount', (user) => user.type(valueInput(), '0')],
    ['range', async (user) => {
      const hasta = screen.getByLabelText('Hasta', { selector: '#aporte-hasta' });
      await user.clear(hasta);
      await user.type(hasta, '2026-10-20');
    }],
    ['campaign', (user) => user.selectOptions(screen.getByLabelText('Campaña'), screen.getByRole('option', { name: /^Routers/ }))],
    ['IVA choice', (user) => user.click(screen.getByLabelText('El monto incluye IVA'))],
    ['kind', async (user) => {
      await user.click(screen.getByRole('button', { name: 'Porcentaje del costo' }));
      await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    }],
    ['settlement', async (user) => {
      await user.click(screen.getByLabelText('Devuelve la diferencia'));
      await user.click(screen.getByLabelText('Se recibe todo'));
    }],
    ['channel', async (user) => {
      await user.click(within(screen.getByRole('group', { name: 'Canal' })).getByRole('button', { name: 'Display' }));
      const select = await screen.findByLabelText('Campaña de Display');
      await within(select).findByRole('option', { name: 'XeroxB110 · 335306 · GAUSS' });
      await user.selectOptions(select, 'XeroxB110 · 335306 · GAUSS');
    }],
  ])('changing the %s after confirming clears the confirmation and asks again', async (_what, change) => {
    previewWith({ spend: 1000, counted: 5000, net: -4000, over_spend: true });
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    await user.click(await screen.findByLabelText(CONFIRM_LABEL));
    expect(screen.getByLabelText(CONFIRM_LABEL)).toBeChecked();
    await change(user);
    expect(await screen.findByLabelText(CONFIRM_LABEL)).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(await screen.findByText('Confirmá que el aporte supera el costo de la campaña en el rango.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('a backend rejection of the amount stops counting once the amount changes', async () => {
    api.get.mockImplementation((url) =>
      url.endsWith('/preview') ? Promise.reject(new Error('down')) : Promise.resolve({ data: answer(url, {}) }),
    );
    api.post
      .mockRejectedValueOnce({
        response: { status: 422, data: { error: { field: 'value', message: 'the amount is above the range spend of 0.00' } } },
      })
      .mockResolvedValueOnce({ data: {} });
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await screen.findByLabelText(CONFIRM_LABEL);
    await user.clear(valueInput());
    await user.type(valueInput(), '500');
    expect(screen.queryByLabelText(CONFIRM_LABEL)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(api.post.mock.calls[1][1]).not.toHaveProperty('confirm_over_spend');
  });

  it('switching the channel drops a backend rejection and a confirmation given on the old channel', async () => {
    api.get.mockImplementation((url) =>
      url.endsWith('/preview') ? Promise.reject(new Error('down')) : Promise.resolve({ data: answer(url, {}) }),
    );
    api.post.mockRejectedValueOnce({
      response: { status: 422, data: { error: { field: 'value', message: 'the amount is above the range spend of 0.00' } } },
    });
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await user.click(await screen.findByLabelText(CONFIRM_LABEL));
    await user.click(within(screen.getByRole('group', { name: 'Canal' })).getByRole('button', { name: 'Display' }));
    expect(screen.queryByLabelText(CONFIRM_LABEL)).not.toBeInTheDocument();
    await user.click(within(screen.getByRole('group', { name: 'Canal' })).getByRole('button', { name: 'Product Ads' }));
    expect(screen.queryByLabelText(CONFIRM_LABEL)).not.toBeInTheDocument();
  });

  it('asks to confirm when the backend says so, even on a range that spent nothing yet', async () => {
    previewWith({ spend: 0, counted: 0, net: 0, over_spend: true });
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    expect(await screen.findByLabelText('Confirmo que el aporte supera el costo de la campaña en el rango')).toBeInTheDocument();
  });

  it('asks nothing when the backend does not flag it', async () => {
    previewWith({ spend: 1000, counted: 5000, net: -4000, over_spend: false });
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    await screen.findByLabelText('Lo que cubre el aporte');
    expect(screen.queryByLabelText(/Confirmo que el aporte supera/)).not.toBeInTheDocument();
  });

  it('says when the range ends after the last day with Ads data', async () => {
    previewWith({ spend: 1000, counted: 100, net: 900, data_through: '2026-10-10' });
    const user = userEvent.setup();
    await openCreate(user);
    await fillCommon(user);
    expect(
      await screen.findByText('Hay datos de Ads hasta el 10/10/2026: lo que cae después todavía no se cargó y el aporte va a cambiar cuando llegue.'),
    ).toBeInTheDocument();
  });

  it('says nothing when the range ends on or before that day', async () => {
    previewWith({ spend: 1000, counted: 100, net: 900, data_through: '2026-10-15' });
    const user = userEvent.setup();
    await openCreate(user);
    await fillCommon(user);
    await screen.findByLabelText('Lo que cubre el aporte');
    expect(screen.queryByText(/Hay datos de Ads hasta/)).not.toBeInTheDocument();
  });

  it('puts the brand first, then the channel, then the campaign', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    const fields = [
      screen.getByLabelText('Marca'),
      screen.getByRole('group', { name: 'Canal' }),
      screen.getByLabelText('Campaña'),
      screen.getByRole('group', { name: 'Tipo de aporte' }),
    ];
    const after = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    fields.slice(1).forEach((field, i) => expect(after(fields[i], field)).toBe(true));
  });

  it('shows the amount with es-AR thousands separators and sends the number', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '1500000,5' });
    expect(valueInput()).toHaveValue('1.500.000,5');
    await user.click(screen.getByLabelText('Devuelve la diferencia'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toMatchObject({ value: 1500000.5 });
  });

  it('previews before a brand is picked', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    await fillCommon(user, { brand: null });
    expect(await screen.findByLabelText('Lo que cubre el aporte')).toBeInTheDocument();
  });

  it('says so when the brand list cannot load', async () => {
    api.get.mockImplementation((url) =>
      url === '/marcas' ? Promise.reject(new Error('down')) : Promise.resolve({ data: answer(url, {}) }),
    );
    const user = userEvent.setup();
    await openCreate(user);
    expect(
      await screen.findByText('No se pudo cargar la lista de marcas. Cerrá el formulario y volvé a abrirlo.'),
    ).toBeInTheDocument();
  });

  it('offers the confirmation when the backend rejects the amount even without a preview', async () => {
    api.get.mockImplementation((url) =>
      url.endsWith('/preview') ? Promise.reject(new Error('down')) : Promise.resolve({ data: answer(url, {}) }),
    );
    api.post
      .mockRejectedValueOnce({
        response: { status: 422, data: { error: { field: 'value', message: 'the amount is above the range spend of 0.00' } } },
      })
      .mockResolvedValueOnce({ data: {} });
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await user.click(await screen.findByLabelText('Confirmo que el aporte supera el costo de la campaña en el rango'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(api.post.mock.calls[1][1]).toMatchObject({ confirm_over_spend: true });
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('confirm_over_spend');
  });

  it.each([
    ['1500.50', 1500.5],
    ['1.500.000', 1500000],
    ['1.500', 1500],
    ['1500,5', 1500.5],
  ])('reads %s as %s, never multiplying a decimal point away', async (typed, sent) => {
    const user = userEvent.setup();
    await openCreate(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: typed });
    await user.click(screen.getByLabelText('Devuelve la diferencia'));
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toMatchObject({ value: sent });
  });

  it('reads a percentage typed with a decimal point', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    await fillCommon(user, { value: '12.5' });
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toMatchObject({ kind: 'percentage', value: 12.5 });
  });
});

describe('"Por aporte" view (Stitch 55853ac1)', () => {
  const porAporte = async (user) => {
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(screen.getByRole('button', { name: 'Por aporte' }));
    return screen.findByRole('table', { name: 'Aportes del período' });
  };

  it('switches from the campaigns to one row per aporte, for the same range', async () => {
    const user = userEvent.setup();
    const table = await porAporte(user);
    expect(await within(table).findByText('Lucía Fernández · 02/10')).toBeInTheDocument();
    expect(screen.queryByText('Routers')).not.toBeInTheDocument();
    expect(
      screen.getByText('Cada aporte cargado, qué marca lo paga y cuánto cubre en el período, en Product Ads y Display.'),
    ).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-ads/contributions', { params: expect.any(Object) });
    await user.click(screen.getByRole('button', { name: 'Por campaña' }));
    expect(await screen.findByText('Routers')).toBeInTheDocument();
  });

  it('edits a Product Ads aporte in the same form and lists it again after saving', async () => {
    const user = userEvent.setup();
    const table = await porAporte(user);
    await user.click(await within(table).findByRole('button', { name: 'Editar aporte de TP-Link' }));
    expect(screen.getByText('Editar aporte')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/ml-ads/contributions/1', expect.any(Object)));
    await waitFor(() =>
      expect(api.get.mock.calls.filter(([url]) => url === '/ml-ads/contributions')).toHaveLength(2),
    );
  });

  it('deletes an aporte after confirming, naming the whole Display account, and lists again', async () => {
    const user = userEvent.setup();
    const table = await porAporte(user);
    await user.click(await within(table).findByRole('button', { name: 'Borrar aporte de Xerox' }));
    const dialog = screen.getByText('¿Borrar este aporte?').closest('.modal-tesla');
    expect(dialog).toHaveTextContent('Toda la cuenta Display · GAUSS');
    await user.click(screen.getByRole('button', { name: 'Borrar aporte' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/ml-ads/contributions/3'));
    await waitFor(() =>
      expect(api.get.mock.calls.filter(([url]) => url === '/ml-ads/contributions')).toHaveLength(2),
    );
  });

  it('names a campaign without a catalog name the same way in the table and in the delete confirmation', async () => {
    const answerOthers = api.get.getMockImplementation();
    const unnamed = { ...APORTES_VIEW.contributions[0], campaign_name: null };
    api.get.mockImplementation((url, config) =>
      url === '/ml-ads/contributions'
        ? Promise.resolve({ data: { ...APORTES_VIEW, contributions: [unnamed] } })
        : answerOthers(url, config),
    );
    const user = userEvent.setup();
    const table = await porAporte(user);
    expect(await within(table).findByText('Campaña 351001')).toBeInTheDocument();
    await user.click(within(table).getByRole('button', { name: 'Borrar aporte de TP-Link' }));
    expect(screen.getByText('¿Borrar este aporte?').closest('.modal-tesla')).toHaveTextContent('Campaña 351001');
  });
});

describe('Display aportes (Stitch 7512c518)', () => {
  const DISPLAY_PREVIEW = { spend: 1200000, counted: 300000, net: 900000, warnings: [], data_through: null, over_spend: false };
  const modal = () => screen.getByRole('button', { name: 'Guardar aporte' }).closest('.modal-tesla');
  const channel = () => within(modal()).getByRole('group', { name: 'Canal' });
  const follows = (first, second) => Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
  const previewCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-ads/contributions/preview');

  async function openHeaderCreate(user) {
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(screen.getByRole('button', { name: 'Agregar aporte' }));
  }

  async function chooseWholeDisplayAccount(user) {
    await user.click(within(channel()).getByRole('button', { name: 'Display' }));
    const select = await screen.findByLabelText('Campaña de Display');
    await within(select).findByRole('option', { name: 'Toda la cuenta Display · GAUSS' });
    await user.selectOptions(select, 'Toda la cuenta Display · GAUSS');
  }

  it('asks the channel right after the brand and offers each advertiser\'s whole Display account', async () => {
    const user = userEvent.setup();
    await openHeaderCreate(user);
    expect(within(channel()).getByRole('button', { name: 'Product Ads' })).toHaveAttribute('aria-pressed', 'true');
    expect(follows(screen.getByLabelText('Marca'), channel())).toBe(true);
    expect(follows(channel(), screen.getByLabelText('Campaña'))).toBe(true);

    await chooseWholeDisplayAccount(user);
    expect(api.get).toHaveBeenCalledWith('/ml-ads/display', { params: expect.objectContaining({ date_from: expect.any(String) }) });
    const select = screen.getByLabelText('Campaña de Display');
    expect(within(select).getByRole('option', { name: 'XeroxB110 · 335306 · GAUSS' })).toBeInTheDocument();
    expect(follows(channel(), select)).toBe(true);
    expect(
      screen.getByText('Toda la cuenta: el aporte cubre todas las campañas de Display del anunciante en el rango.'),
    ).toBeInTheDocument();
  });

  it('a full amount above the whole Display account asks about the account, not a campaign', async () => {
    api.get.mockImplementation((url) =>
      Promise.resolve({
        data:
          url === '/ml-ads/contributions/preview'
            ? { ...DISPLAY_PREVIEW, counted: 5000000, net: -3800000, over_spend: true }
            : answer(url, {}),
      }),
    );
    const user = userEvent.setup();
    await openHeaderCreate(user);
    await chooseWholeDisplayAccount(user);
    await user.click(screen.getByRole('button', { name: 'Monto fijo' }));
    await fillCommon(user, { value: '5000000', brand: 'EPSON' });
    await user.click(screen.getByLabelText('Se recibe todo'));
    expect(
      await screen.findByLabelText('Confirmo que el aporte supera el costo de la cuenta de Display en el rango'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    expect(
      await screen.findByText('Confirmá que el aporte supera el costo de la cuenta de Display en el rango.'),
    ).toBeInTheDocument();
  });

  it('saves a whole-account Display aporte and previews it on the Display spend', async () => {
    api.get.mockImplementation((url, config) =>
      Promise.resolve({
        data:
          url === '/ml-ads/contributions/preview' && config.params.channel === 'display'
            ? DISPLAY_PREVIEW
            : answer(url, { spend: 742300, counted: 500000, net: 242300, warnings: [], data_through: null }),
      }),
    );
    const user = userEvent.setup();
    await openHeaderCreate(user);
    await chooseWholeDisplayAccount(user);
    await fillCommon(user, { value: '25', brand: 'EPSON' });

    const sentence = 'En el rango, Display gastó $ 1.200.000,00; este aporte cubre $ 300.000,00.';
    expect(await screen.findByText((_, el) => el?.tagName === 'P' && el.textContent === sentence)).toBeInTheDocument();
    expect(screen.queryByRole('definition')).not.toBeInTheDocument();
    const [, { params }] = previewCalls().at(-1);
    expect(params).toEqual(expect.objectContaining({ channel: 'display', advertiser_id: 25713 }));
    expect(params).not.toHaveProperty('campaign_id');

    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/ml-ads/contributions',
        expect.objectContaining({ channel: 'display', advertiser_id: 25713, campaign_id: null, kind: 'percentage', value: 25 }),
      ),
    );
  });

  it('saves one Display campaign by its id', async () => {
    const user = userEvent.setup();
    await openHeaderCreate(user);
    await user.click(within(channel()).getByRole('button', { name: 'Display' }));
    const select = await screen.findByLabelText('Campaña de Display');
    await within(select).findByRole('option', { name: 'XeroxB110 · 335306 · GAUSS' });
    await user.selectOptions(select, 'XeroxB110 · 335306 · GAUSS');
    expect(screen.queryByText(/^Toda la cuenta:/)).not.toBeInTheDocument();
    await fillCommon(user, { value: '25', brand: 'EPSON' });
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/ml-ads/contributions',
        expect.objectContaining({ channel: 'display', advertiser_id: 25713, campaign_id: 335306 }),
      ),
    );
  });

  it('goes back to the Product Ads campaigns, unchosen, when the channel goes back', async () => {
    const user = userEvent.setup();
    await openHeaderCreate(user);
    await chooseWholeDisplayAccount(user);
    await user.click(within(channel()).getByRole('button', { name: 'Product Ads' }));
    expect(screen.getByLabelText('Campaña')).toHaveValue('');
    expect(screen.queryByLabelText('Campaña de Display')).not.toBeInTheDocument();
  });

  it('drops a Product Ads preview when the channel switches to Display, never showing it as Display spend', async () => {
    const user = userEvent.setup();
    await openHeaderCreate(user);
    await user.selectOptions(screen.getByLabelText('Campaña'), 'Notebooks · 66 · GAUSS');
    await fillCommon(user, { value: '10', brand: 'EPSON' });
    expect(await screen.findByLabelText('Lo que cubre el aporte')).toBeInTheDocument();
    await user.click(within(channel()).getByRole('button', { name: 'Display' }));
    expect(screen.queryByLabelText('Lo que cubre el aporte')).not.toBeInTheDocument();
    expect(screen.queryByText(/Display gastó/)).not.toBeInTheDocument();
  });

  it('says why no Display campaign can be picked when the list fails to load, and retries it in place', async () => {
    const answerOthers = api.get.getMockImplementation();
    let fail = true;
    api.get.mockImplementation((url, config) =>
      url === '/ml-ads/display' && fail ? Promise.reject(new Error('boom')) : answerOthers(url, config),
    );
    const user = userEvent.setup();
    await openHeaderCreate(user);
    await user.click(within(channel()).getByRole('button', { name: 'Display' }));
    expect(await screen.findByText('No se pudo cargar la lista de campañas de Display.')).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));
    const select = screen.getByLabelText('Campaña de Display');
    expect(await within(select).findByRole('option', { name: 'Toda la cuenta Display · GAUSS' })).toBeInTheDocument();
    expect(screen.queryByText('No se pudo cargar la lista de campañas de Display.')).not.toBeInTheDocument();
  });

  it('edits a Display aporte from the Por aporte view, its channel and account locked', async () => {
    const user = userEvent.setup();
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(screen.getByRole('button', { name: 'Por aporte' }));
    await user.click(await screen.findByRole('button', { name: 'Editar aporte de Xerox' }));
    expect(screen.getByText('Editar aporte')).toBeInTheDocument();
    const display = within(channel()).getByRole('button', { name: 'Display' });
    expect(display).toHaveAttribute('aria-pressed', 'true');
    expect(display).toBeDisabled();
    const select = screen.getByLabelText('Campaña de Display');
    expect(select).toBeDisabled();
    expect(await within(select).findByRole('option', { name: 'Toda la cuenta Display · GAUSS', selected: true })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar aporte' }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        '/ml-ads/contributions/3',
        expect.objectContaining({ channel: 'display', advertiser_id: 25713, campaign_id: null, brand: 'Xerox', value: 25 }),
      ),
    );
  });
});
