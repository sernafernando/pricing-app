/**
 * ODD `vistas-tipo-publicacion` T4 (S5): the "Filas finas" toggle of Métricas ML -- off by default, it marks the
 * board as dense and the browser remembers it. How dense looks is the visual suite's job.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api from '../services/api';
import { BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const KEY = 'metricas-ml.filas-finas';
const densityOf = () => screen.getByText('Impresora Multifunción Epson EcoTank L3250 Color Negro').closest('[data-density]').dataset.density;

beforeEach(() => {
  localStorage.removeItem(KEY);
  api.get.mockReset();
  api.get.mockImplementation((url) => Promise.resolve({ data: url === '/ml-metricas/board' ? BOARD_RESPONSE : {} }));
});
afterEach(() => localStorage.removeItem(KEY));

describe('MetricasML "Filas finas"', () => {
  it('starts off, and turning it on presses the toggle and makes the board dense', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    const toggle = screen.getByRole('button', { name: 'Filas finas' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(densityOf()).toBe('normal');

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(densityOf()).toBe('dense');
  });

  it('keeps the choice after a reload', async () => {
    const first = renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    await userEvent.click(screen.getByRole('button', { name: 'Filas finas' }));
    first.unmount();

    renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    expect(screen.getByRole('button', { name: 'Filas finas' })).toHaveAttribute('aria-pressed', 'true');
    expect(densityOf()).toBe('dense');
  });
});
