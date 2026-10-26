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

async function fillCommon(user, { value = '10' } = {}) {
  await user.clear(valueInput());
  await user.type(valueInput(), value);
  await user.type(screen.getByLabelText('Desde', { selector: '#aporte-desde' }), '2026-10-01');
  await user.type(screen.getByLabelText('Hasta', { selector: '#aporte-hasta' }), '2026-10-15');
}

beforeEach(() => {
  vi.clearAllMocks();
  permisosDenegados.clear();
  api.get.mockImplementation((url) =>
    Promise.resolve({ data: url.endsWith('/preview') ? { spend: 742300, counted: 500000, net: 242300 } : CAMPAIGNS }),
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
      brand: null,
      note: null,
    });
  });

  it('sends no settlement for a percentage, then closes the form and refreshes the list', async () => {
    const user = userEvent.setup();
    await openCreate(user);
    expect(screen.queryByLabelText('Se recibe todo')).not.toBeInTheDocument();
    await fillCommon(user, { value: '25' });
    await user.type(screen.getByLabelText('Marca'), 'Lenovo');
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

  it('deletes a contribution after confirming and refreshes the list', async () => {
    const user = userEvent.setup();
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(within(rowOf('Routers')).getByRole('button', { name: /borrar aporte/i }));
    expect(api.delete).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Borrar' }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/ml-ads/contributions/7'));
    await waitFor(() => expect(campaignRequests()).toBe(2));
  });

  it('keeps the confirmation open with the backend message when a delete fails', async () => {
    const user = userEvent.setup();
    api.delete.mockRejectedValue({ response: { status: 404, data: { error: { message: 'contribution 7 does not exist' } } } });
    render(<AportesAdsML />);
    await screen.findByText('Routers');
    await user.click(within(rowOf('Routers')).getByRole('button', { name: /borrar aporte/i }));
    await user.click(screen.getByRole('button', { name: 'Borrar' }));
    expect(await screen.findByText('contribution 7 does not exist')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Borrar' })).toBeInTheDocument();
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
    expect(
      await screen.findByText('Costo de la campaña en el rango: $ 742.300,00 · Aporte que cuenta: $ 500.000,00 · Neto: $ 242.300,00'),
    ).toBeInTheDocument();
    expect(api.get).toHaveBeenLastCalledWith('/ml-ads/contributions/preview', {
      params: {
        advertiser_id: 25713,
        campaign_id: 66,
        kind: 'fixed_amount',
        value: 500000,
        date_from: '2026-10-01',
        date_to: '2026-10-15',
        settlement: 'refund_difference',
        brand: null,
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
