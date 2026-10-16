/**
 * ComisionVersion.fecha_desde/hasta are SQL Date columns serialized as bare
 * YYYY-MM-DD. Parsed natively they are UTC midnight, which in Argentina
 * (UTC-3) renders the PREVIOUS day. The unit project pins TZ in
 * vite.config.js so a UTC CI still exercises the bug.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelComisiones from './PanelComisiones';
import api from '../services/api';

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }));

const VERSION = {
  id: 1,
  nombre: 'Versión 2026',
  descripcion: null,
  activo: true,
  fecha_desde: '2026-01-01',
  fecha_hasta: '2026-06-30',
  comisiones_base: [],
  adicionales_cuota: [],
};

describe('PanelComisiones - version dates', () => {
  it('shows current, history and detail validity dates on their calendar day in Argentina', async () => {
    // Guard: without this premise the test would pass without exercising the bug.
    expect(new Date('2026-01-01').toLocaleDateString('es-AR')).toBe('31/12/2025');

    api.get.mockImplementation((url) => {
      if (url === '/comisiones/vigente') return Promise.resolve({ data: VERSION });
      if (url === '/comisiones/versiones') return Promise.resolve({ data: [VERSION] });
      return Promise.resolve({ data: [] });
    });

    const { container } = render(<PanelComisiones />);

    const actual = await screen.findByText(/^Vigencia:/);
    expect(actual).toHaveTextContent('Vigencia: 1/1/2026 - 30/6/2026');

    const historial = container.querySelector('.version-item .version-fechas');
    expect(historial).toHaveTextContent('1/1/2026 -30/6/2026');

    await userEvent.click(container.querySelector('.version-item'));
    const detalle = container.querySelector('.modal-comisiones .version-info');
    expect(detalle).toHaveTextContent('Vigencia: 1/1/2026 - 30/6/2026');
  });
});
