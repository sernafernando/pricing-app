/**
 * /pedidos-local/estadisticas serializes fecha_desde with
 * strftime('%Y-%m-%d'), a bare YYYY-MM-DD. Parsed natively it is UTC midnight,
 * which in Argentina (UTC-3) renders the PREVIOUS day. The unit project pins TZ in
 * vite.config.js so a UTC CI still exercises the bug.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import TabPedidosExport from './TabPedidosExport';
import api from '../services/api';

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true }),
}));

describe('TabPedidosExport - stats window start date', () => {
  it('shows the window start date on its calendar day in Argentina', async () => {
    // Guard: without this premise the test would pass without exercising the bug.
    expect(new Date('2026-08-17').toLocaleDateString('es-AR')).toBe('16/8/2026');

    api.get.mockImplementation((url) => {
      if (url === '/pedidos-local/estadisticas') {
        return Promise.resolve({ data: { total_pedidos: 3, dias_filtro: 60, fecha_desde: '2026-08-17' } });
      }
      return Promise.resolve({ data: [] });
    });

    render(<TabPedidosExport />);

    expect(await screen.findByText('17/8/2026')).toBeInTheDocument();
  });
});
