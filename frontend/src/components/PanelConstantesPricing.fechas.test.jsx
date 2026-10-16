/**
 * PricingConstants.fecha_desde/hasta are SQL Date columns serialized as bare
 * YYYY-MM-DD. Parsed natively they are UTC midnight, which in Argentina
 * (UTC-3) renders the PREVIOUS day. The zone is pinned so a UTC CI still
 * exercises the bug.
 */

import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import PanelConstantesPricing from './PanelConstantesPricing';
import api from '../services/api';

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));

beforeAll(() => {
  vi.stubEnv('TZ', 'America/Argentina/Buenos_Aires');
});

afterAll(() => {
  vi.unstubAllEnvs();
});

describe('PanelConstantesPricing - version dates', () => {
  it('shows version validity dates on their calendar day in Argentina', async () => {
    // Guard: without this premise the test would pass without exercising the bug.
    expect(new Date('2026-01-01').toLocaleDateString('es-AR')).toBe('31/12/2025');

    const version = { id: 1, fecha_desde: '2026-01-01', fecha_hasta: '2026-06-30' };
    api.get.mockImplementation((url) =>
      Promise.resolve({ data: url === '/pricing-constants' ? [version] : version }),
    );

    render(<PanelConstantesPricing />);

    expect(await screen.findByText(/^Desde:/)).toHaveTextContent('Desde: 1/1/2026');
    expect(screen.getByText(/^Hasta:/)).toHaveTextContent('Hasta: 30/6/2026');
  });
});
