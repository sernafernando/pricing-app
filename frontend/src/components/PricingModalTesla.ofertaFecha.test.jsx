/**
 * "Vigente hasta" shows OfertaML.fecha_hasta, a SQL Date serialized as a bare
 * YYYY-MM-DD. Parsed natively it is UTC midnight, which in Argentina (UTC-3)
 * renders the PREVIOUS day. The zone is pinned so a UTC CI still exercises it.
 */

import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import PricingModalTesla from './PricingModalTesla';
import api from '../services/api';

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }));

beforeAll(() => {
  vi.stubEnv('TZ', 'America/Argentina/Buenos_Aires');
});

afterAll(() => {
  vi.unstubAllEnvs();
});

describe('PricingModalTesla - active offer end date', () => {
  it('shows the offer end date on its calendar day in Argentina', async () => {
    // Guard: without this premise the test would pass without exercising the bug.
    expect(new Date('2026-12-31').toLocaleDateString('es-AR')).toBe('30/12/2026');

    api.get.mockResolvedValue({
      data: {
        con_oferta: 1,
        total_publicaciones: 1,
        publicaciones: [
          {
            mla: 'MLA123',
            lista_nombre: 'Clásica',
            tiene_oferta: true,
            oferta: {
              precio_final: 1000,
              aporte_meli_pesos: 50,
              aporte_meli_porcentaje: null,
              fecha_desde: '2026-12-01',
              fecha_hasta: '2026-12-31',
            },
          },
        ],
      },
    });

    render(<PricingModalTesla isOpen producto={{ item_id: 1 }} onClose={() => {}} onSave={() => {}} />);

    expect(await screen.findByText(/Vigente hasta:/)).toHaveTextContent('Vigente hasta: 31/12/2026');
  });
});
