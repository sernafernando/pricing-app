import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MejoresCandidatasBlock from './MejoresCandidatasBlock';
// Real LIGHTNING rows (owner capture 2026-11-06), shared with PromoApplyControl.lightning.test.jsx.
import lightningCapture from '../../promociones/fixtures/lightning_item_promotions_20261106.json';

vi.mock('../../../services/api', () => ({
  promocionesAPI: {
    getMarkupParaPrecio: vi.fn(),
    getPromocionesItem: vi.fn(),
    descartarHayMejores: vi.fn(),
    postPromocionItem: vi.fn(),
  },
}));

vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

import { promocionesAPI } from '../../../services/api';

describe('MejoresCandidatasBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 0.35 } });
  });

  it('does not claim there are better candidatas when SMART/DEAL/Premium slots are empty', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            status: 'candidate',
            promotion_type: 'SMART',
            promotion_id: 'P-MLA1',
            price: 219001.75,
            nuestro_markup: 1.2,
            name: 'Potencia tus ventas',
          },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA1" baselinePrice={218299} />);
    expect(await screen.findByText(/No hay candidatas aplicables/)).toBeInTheDocument();
    expect(screen.queryByText(/Hay candidatas mejores que el precio vigente/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Descartar sugerencia/ })).toBeInTheDocument();
  });

  it('leads with hay candidatas only when a slot qualifies', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            status: 'candidate',
            promotion_type: 'SMART',
            promotion_id: 'P-MLA2',
            price: 200000,
            nuestro_markup: 1.5,
            name: 'Oferta ok',
          },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA2" baselinePrice={218299} />);
    await waitFor(() => {
      expect(screen.getByText(/Hay candidatas mejores que el precio vigente/)).toBeInTheDocument();
    });
    const card = screen.getByRole('group', { name: 'Promo sugerida SMART' });
    expect(within(card).getByText('Oferta ok')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Aplicar sugerencia' })).toBeInTheDocument();
  });

  // promos-markup-sell-in-out S2: the box shows the markup with sell in / sell out next to each markup.
  it('shows the markup with sell in / sell out on the card and on the Markup vigente line', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 0.35, markup_sell_in_out: 3.2 } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            status: 'candidate',
            promotion_type: 'SMART',
            promotion_id: 'P-MLA2',
            price: 200000,
            nuestro_markup: 1.5,
            markup_sell_in_out: 4.25,
            name: 'Oferta ok',
          },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA2" baselinePrice={218299} />);

    const card = await screen.findByRole('group', { name: 'Promo sugerida SMART' });
    expect(within(card).getByText((_, el) => el?.textContent === 'c/ sell in/out 4,25%')).toBeInTheDocument();
    expect(screen.getByText(/Markup vigente ~/).textContent).toBe(
      'Hay candidatas mejores que el precio vigente en MeLi. Markup vigente ~ 0,35% · c/ sell in/out 3,20%.',
    );
  });

  it('shows no sell in / sell out figure when the backend sends null', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 0.35, markup_sell_in_out: null } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            status: 'candidate',
            promotion_type: 'SMART',
            promotion_id: 'P-MLA2',
            price: 200000,
            nuestro_markup: 1.5,
            markup_sell_in_out: null,
            name: 'Oferta ok',
          },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA2" baselinePrice={218299} />);

    await screen.findByRole('group', { name: 'Promo sugerida SMART' });
    expect(screen.queryByText('c/ sell in/out')).not.toBeInTheDocument();
    expect(screen.getByText(/Markup vigente ~/).textContent).toBe(
      'Hay candidatas mejores que el precio vigente en MeLi. Markup vigente ~ 0,35%.',
    );
  });

  // S5: the status quo and the candidates are compared by their markups with sell in / sell out.
  it('suggests nothing when only the plain markup beats the status quo', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 0.35, markup_sell_in_out: 3.2 } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            status: 'candidate',
            promotion_type: 'SMART',
            promotion_id: 'P-MLA2',
            price: 200000,
            nuestro_markup: 1.5,
            markup_sell_in_out: 2,
            name: 'Oferta ok',
          },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA2" baselinePrice={218299} />);

    expect(await screen.findByText(/No hay candidatas aplicables/)).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Promo sugerida SMART' })).not.toBeInTheDocument();
  });

  it('compares a candidate without sell in / sell out plain against the plain vigente markup', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 0.35, markup_sell_in_out: 3.2 } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            status: 'candidate',
            promotion_type: 'SMART',
            promotion_id: 'P-MLA2',
            price: 200000,
            nuestro_markup: 1.5,
            markup_sell_in_out: null,
            name: 'Oferta ok',
          },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA2" baselinePrice={218299} />);

    // 1,5% >= 0,35% (never 1,5% against the 3,20% with sell in / sell out).
    expect(await screen.findByRole('group', { name: 'Promo sugerida SMART' })).toBeInTheDocument();
  });

  it('shows the load error instead of claiming there are no candidatas', async () => {
    const onUnavailable = vi.fn();
    promocionesAPI.getPromocionesItem.mockRejectedValue(new Error('boom'));
    render(<MejoresCandidatasBlock itemId="MLA-err" baselinePrice={1000} onUnavailable={onUnavailable} />);
    expect(await screen.findByText(/No se pudieron cargar las candidatas/i)).toBeInTheDocument();
    expect(screen.queryByText(/No hay candidatas aplicables/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Descartar sugerencia/ })).toBeInTheDocument();
    // Load failures stay mounted — onUnavailable would let MODO hide the error.
    expect(onUnavailable).not.toHaveBeenCalled();
  });

  it('suggests one card per writable MeLi type, each with its own c/ sell in/out', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          { status: 'candidate', promotion_type: 'SMART', promotion_id: 'S-1', price: 90000, nuestro_markup: 3, markup_sell_in_out: 5, name: 'Smart' },
          { status: 'candidate', promotion_type: 'PRE_NEGOTIATED', promotion_id: 'PN-1', price: 90000, nuestro_markup: 4, markup_sell_in_out: 6.5, name: 'Pre negociada' },
          { status: 'candidate', promotion_type: 'PRICE_MATCHING', promotion_id: 'PM-1', price: 90000, nuestro_markup: 2, markup_sell_in_out: null, name: 'Price matching' },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA-T" baselinePrice={100000} />);
    const preNegotiated = await screen.findByRole('group', { name: 'Promo sugerida PRE_NEGOTIATED' });
    expect(within(preNegotiated).getByText('PRE_NEGOTIATED')).toBeInTheDocument();
    expect(within(preNegotiated).getByText((_, el) => el?.textContent === 'c/ sell in/out 6,50%')).toBeInTheDocument();
    const priceMatching = screen.getByRole('group', { name: 'Promo sugerida PRICE_MATCHING' });
    expect(within(priceMatching).queryByText(/sell in\/out/)).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Promo sugerida SMART' })).toBeInTheDocument();
  });

  it('applies LIGHTNING through the irreversible-offer card, with ML\'s minimum stock prefilled', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted', precio_difiere: false } });
    const lightning = {
      ...lightningCapture.rows.find((row) => row.mla === 'MLA1506729443' && row.status === 'candidate'),
      nuestro_markup: 2,
    };
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [lightning] } });
    render(<MejoresCandidatasBlock itemId="MLA1506729443" baselinePrice={80000} />);
    const card = await screen.findByRole('group', { name: 'Promo sugerida LIGHTNING' });
    await user.click(within(card).getByRole('button', { name: 'Aplicar sugerencia' }));
    expect(screen.getByText(/una vez que empieza no se puede quitar/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Stock a reservar')).toHaveValue(5);
    expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
    await waitFor(() => {
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith(
        'MLA1506729443',
        expect.objectContaining({ promotion_id: 'LGH-MLA1000', promotion_type: 'LIGHTNING', stock: 5 }),
      );
    });
  });

  it('uses cofunded started markup as vigente and does not call getMarkupParaPrecio', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            status: 'started',
            promotion_type: 'PRICE_MATCHING',
            promotion_id: 'P-LIVE',
            price: 555867.8,
            nuestro_markup: 1.4,
            name: 'Gánale',
          },
          {
            status: 'candidate',
            promotion_type: 'SMART',
            promotion_id: 'P-SMART',
            price: 526957,
            nuestro_markup: -5.06,
            name: 'Potencia',
          },
        ],
      },
    });
    render(<MejoresCandidatasBlock itemId="MLA3" baselinePrice={555867.83} />);
    expect(await screen.findByText(/No hay candidatas aplicables/)).toBeInTheDocument();
    expect(screen.getByText(/markup vigente ~ 1,40%/i)).toBeInTheDocument();
    expect(promocionesAPI.getMarkupParaPrecio).not.toHaveBeenCalled();
  });

  describe('when the candidates are unavailable', () => {
    it('keeps a notice with Descartar sugerencia when the candidates fail to load', async () => {
      const user = userEvent.setup();
      const onUnavailable = vi.fn();
      const onDismissed = vi.fn();
      const onWritten = vi.fn();
      promocionesAPI.getPromocionesItem.mockRejectedValue(new Error('boom'));
      promocionesAPI.descartarHayMejores.mockResolvedValue({ data: {} });
      render(
        <MejoresCandidatasBlock
          itemId="MLA5"
          baselinePrice={1000}
          onUnavailable={onUnavailable}
          onDismissed={onDismissed}
          onWritten={onWritten}
        />,
      );
      const region = await screen.findByRole('region', { name: 'Candidatas mejores' });
      expect(await within(region).findByText('Hay candidatas mejores que el precio vigente en MeLi.')).toBeInTheDocument();
      expect(within(region).getByText('No se pudieron cargar las candidatas.')).toBeInTheDocument();
      expect(onUnavailable).not.toHaveBeenCalled();
      await user.click(within(region).getByRole('button', { name: 'Descartar sugerencia' }));
      expect(promocionesAPI.descartarHayMejores).toHaveBeenCalledWith('MLA5');
      await waitFor(() => expect(onDismissed).toHaveBeenCalledTimes(1));
      expect(onWritten).toHaveBeenCalled();
    });

    it('keeps the notice with Descartar sugerencia when the baseline markup is missing', async () => {
      const onUnavailable = vi.fn();
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
      promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: null } });
      render(<MejoresCandidatasBlock itemId="MLA6" baselinePrice={1000} onUnavailable={onUnavailable} />);
      expect(await screen.findByText('Hay candidatas mejores que el precio vigente en MeLi.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Descartar sugerencia' })).toBeInTheDocument();
      expect(screen.queryByText(/No hay candidatas aplicables/)).not.toBeInTheDocument();
      expect(onUnavailable).toHaveBeenCalledTimes(1);
    });
  });

  describe('Aplicar sugerencia', () => {
    const smart = {
      status: 'candidate',
      promotion_type: 'SMART',
      promotion_id: 'P-SMART',
      price: 57920.55,
      nuestro_markup: -28.34,
      name: 'Potencia tus ventas',
    };

    beforeEach(() => {
      promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: -28.74 } });
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [smart] } });
    });

    it('shows the suggested card with type, name, price and markup', async () => {
      const onSuggested = vi.fn();
      render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onSuggested={onSuggested} />);
      const card = await screen.findByRole('group', { name: 'Promo sugerida SMART' });
      expect(within(card).getByText('SMART')).toBeInTheDocument();
      expect(within(card).getByText('Potencia tus ventas')).toBeInTheDocument();
      expect(within(card).getByText('$ 57.920,55')).toBeInTheDocument();
      expect(within(card).getByText('-28,34%')).toBeInTheDocument();
      expect(screen.getByText(/Markup vigente ~/)).toHaveTextContent('-28,74%');
      expect(onSuggested).toHaveBeenCalledWith(['P-SMART']);
    });

    it('asks for confirmation before posting, then sends the guarded body', async () => {
      const user = userEvent.setup();
      const onLeavePub = vi.fn();
      const onWritten = vi.fn();
      promocionesAPI.postPromocionItem.mockResolvedValue({
        data: { status: 'submitted', precio_difiere: false },
      });
      render(
        <MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onLeavePub={onLeavePub} onWritten={onWritten} />,
      );
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
      expect(screen.getByText(/¿Aplicar esta promoción\?/)).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      await waitFor(() =>
        expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA9', {
          promotion_id: 'P-SMART',
          promotion_type: 'SMART',
          precio_visto: 57920.55,
          markup_visto: -28.34,
        }),
      );
      expect(onWritten).toHaveBeenCalled();
      expect(onLeavePub).toHaveBeenCalledTimes(1);
    });

    it('never leaves the pub when ML moved the price (409)', async () => {
      const user = userEvent.setup();
      const onLeavePub = vi.fn();
      promocionesAPI.postPromocionItem.mockRejectedValue({
        response: {
          status: 409,
          data: { status: 'rejected_price_changed', precio_actual: 60000, markup_actual: -25, precio_visto: 57920.55 },
        },
      });
      render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onLeavePub={onLeavePub} />);
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      expect(await screen.findByText(/ML cambió el precio/)).toBeInTheDocument();
      expect(onLeavePub).not.toHaveBeenCalled();
    });

    it('outside MODO, a clean apply reloads the candidates so the applied promo drops out', async () => {
      const user = userEvent.setup();
      const onWritten = vi.fn();
      promocionesAPI.getPromocionesItem
        .mockResolvedValueOnce({ data: { promotions: [smart] } })
        .mockResolvedValueOnce({ data: { promotions: [] } });
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted', precio_difiere: false } });
      render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onWritten={onWritten} />);
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      expect(await screen.findByText(/No hay candidatas aplicables/)).toBeInTheDocument();
      expect(screen.queryByRole('group', { name: 'Promo sugerida SMART' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Descartar sugerencia/ })).toBeInTheDocument();
      expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2);
      expect(onWritten).toHaveBeenCalled();
    });

    it('clears the suggested ids when the reload after a clean apply fails, so no row stays Sugerida', async () => {
      const user = userEvent.setup();
      const onSuggested = vi.fn();
      promocionesAPI.getPromocionesItem
        .mockResolvedValueOnce({ data: { promotions: [smart] } })
        .mockRejectedValueOnce(new Error('network'));
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted', precio_difiere: false } });
      render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onSuggested={onSuggested} />);
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      expect(onSuggested).toHaveBeenLastCalledWith([smart.promotion_id]);
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      expect(await screen.findByRole('button', { name: /Descartar sugerencia/ })).toBeInTheDocument();
      await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2));
      expect(onSuggested).toHaveBeenLastCalledWith([]);
    });

    it('keeps the pub open and shows the warning when ML applied another price (precio_difiere)', async () => {
      const user = userEvent.setup();
      const onLeavePub = vi.fn();
      promocionesAPI.postPromocionItem.mockResolvedValue({
        data: {
          status: 'submitted',
          precio_difiere: true,
          precio_aplicado: 58500,
          precio_confirmado: 57920.55,
          markup_aplicado: -27.5,
        },
      });
      render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onLeavePub={onLeavePub} />);
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(/ML aplicó \$\s?58\.500/);
      expect(onLeavePub).not.toHaveBeenCalled();
      expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);
    });

    it('in MODO, a reconciled apply leaves the pub', async () => {
      const user = userEvent.setup();
      const onLeavePub = vi.fn();
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'reconciled_applied' } });
      render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onLeavePub={onLeavePub} />);
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      await waitFor(() => expect(onLeavePub).toHaveBeenCalledTimes(1));
      expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);
    });

    it('never leaves the pub when the apply could not be verified', async () => {
      const user = userEvent.setup();
      const onLeavePub = vi.fn();
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'rejected_by_proxy' } });
      render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} onLeavePub={onLeavePub} />);
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      expect(await screen.findByText('Rechazado por ML.')).toBeInTheDocument();
      expect(onLeavePub).not.toHaveBeenCalled();
    });
  });
});

// pubml-promo-mejor S5 (owner: "tiene que traer también la información de la aplicada actual para verlo a simple vista
// la comparación"): the applied promo sits next to the candidates with the same figures, and each candidate says by
// how much it beats it.
// A figure's whole text, whatever runs it is split into (dates and shares wrap only after their separator).
const figureText = (text) => (_, element) =>
  /mejoresValue/.test(element?.className ?? '') && element.textContent === text;

describe('MejoresCandidatasBlock comparison with the applied promo', () => {
  const candidate = {
    status: 'candidate',
    promotion_type: 'SMART',
    promotion_id: 'P-SMART',
    price: 57000,
    nuestro_markup: 4.5,
    name: 'Potencia tus ventas',
    start_date: '2026-11-05T12:00:00Z',
    finish_date: '2099-11-25T12:00:00Z',
    payload: { seller_percentage: 23.5, meli_percentage: 3.6 },
  };
  const applied = {
    status: 'started',
    application_status: 'active',
    promotion_type: 'DEAL',
    promotion_id: 'P-DEAL',
    price: 59999,
    nuestro_markup: 1.25,
    name: 'MKP T1 CYBER',
    start_date: '2026-11-02T12:00:00Z',
    finish_date: '2099-12-02T12:00:00Z',
    payload: {},
  };

  beforeEach(() => {
    vi.clearAllMocks();
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 1 } });
  });

  it('shows the applied promo with the same figures as the candidates and the markup delta', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [applied, candidate] } });
    render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} />);

    const appliedRow = await screen.findByRole('group', { name: 'Promo aplicada' });
    expect(within(appliedRow).getByText('DEAL')).toBeInTheDocument();
    expect(within(appliedRow).getByText('MKP T1 CYBER')).toBeInTheDocument();
    expect(within(appliedRow).getByText('$ 59.999,00')).toBeInTheDocument();
    expect(within(appliedRow).getByText('1,25%')).toBeInTheDocument();
    expect(within(appliedRow).getByText(figureText('—'))).toBeInTheDocument(); // no seller / ML shares
    expect(within(appliedRow).getByText(figureText('02/11 – 02/12'))).toBeInTheDocument();

    const card = screen.getByRole('group', { name: 'Promo sugerida SMART' });
    expect(within(card).getByText(figureText('23,50% / 3,60%'))).toBeInTheDocument();
    expect(within(card).getByText(figureText('05/11 – 25/11'))).toBeInTheDocument();
    expect(within(card).getByLabelText('+3,25 pp vs aplicada')).toBeInTheDocument();
    // The existing actions stay.
    expect(within(card).getByRole('button', { name: 'Aplicar sugerencia' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Descartar sugerencia' })).toBeInTheDocument();
  });

  it('says Sin promo aplicada with the sale price and its markup when nothing is applied', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [candidate] } });
    render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} />);

    const baseRow = await screen.findByRole('group', { name: 'Sin promo aplicada' });
    expect(within(baseRow).getByText('Sin promo aplicada')).toBeInTheDocument();
    expect(within(baseRow).getByText('$ 59.999,00')).toBeInTheDocument();
    expect(within(baseRow).getByText('1,00%')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Promo aplicada' })).toBeNull();
    const card = screen.getByRole('group', { name: 'Promo sugerida SMART' });
    expect(within(card).getByLabelText('+3,50 pp vs actual')).toBeInTheDocument();
  });

  it('does not suggest a candidate that starts later, even if it is better', async () => {
    const later = { ...candidate, promotion_id: 'P-LATER', start_date: '2099-01-01T00:00:00Z' };
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [applied, later] } });
    render(<MejoresCandidatasBlock itemId="MLA9" baselinePrice={59999} />);
    expect(await screen.findByText(/No hay candidatas aplicables/)).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Promo sugerida SMART' })).toBeNull();
  });
});
