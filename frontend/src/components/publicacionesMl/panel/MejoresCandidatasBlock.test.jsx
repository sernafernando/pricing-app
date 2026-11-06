import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MejoresCandidatasBlock from './MejoresCandidatasBlock';

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
    expect(await screen.findByText(/No hay candidatas SMART \/ DEAL \/ Premium/)).toBeInTheDocument();
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
    expect(await screen.findByText(/No hay candidatas SMART \/ DEAL \/ Premium/)).toBeInTheDocument();
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
      expect(onUnavailable).toHaveBeenCalledTimes(1);
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
      expect(screen.queryByText(/No hay candidatas SMART/)).not.toBeInTheDocument();
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
      expect(await screen.findByText(/No hay candidatas SMART \/ DEAL \/ Premium/)).toBeInTheDocument();
      expect(screen.queryByRole('group', { name: 'Promo sugerida SMART' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Descartar sugerencia/ })).toBeInTheDocument();
      expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2);
      expect(onWritten).toHaveBeenCalled();
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
