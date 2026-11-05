import { render, screen, waitFor } from '@testing-library/react';
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
    expect(screen.getByRole('button', { name: /SMART/ })).toBeInTheDocument();
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
});
